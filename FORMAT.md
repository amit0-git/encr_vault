# Encrvault File Format

## Current format: AVLT02

Newly encrypted files use **AVLT02**. AVLT01 files remain readable for backward
compatibility, but are never produced by the current application.

### Cryptography

- Cipher: AES-256-GCM
- Key derivation: Argon2id
- Salt: 16 bytes, random per vault
- Base nonce: 12 bytes, random per vault
- GCM tag: 16 bytes
- Chunk size: 4 MiB
- Argon2id: time=3, memory=128 MiB, parallelism=2, output=32 bytes

The application serializes Argon2 derivation across concurrent file workers to
prevent the configured 128 MiB KDF memory from being multiplied by the number of
workers.

## AVLT02 layout

```text
header(48) | header_tag(16) | repeated chunks

header:
  magic          6 bytes   ASCII AVLT02
  version        1 byte    0x02
  flags          1 byte    0x00
  salt          16 bytes
  base_nonce    12 bytes
  original_size  8 bytes   unsigned big-endian
  chunk_size     4 bytes   unsigned big-endian (currently 4 MiB)

header_tag      16 bytes   AES-GCM authentication tag

chunk:
  ciphertext_length  4 bytes, big-endian
  ciphertext         N bytes
  authentication_tag 16 bytes
```

The complete 48-byte fixed header is authenticated with an AES-GCM empty plaintext
operation using a reserved nonce index (`2^64-1`). Chunk indices therefore use
`0 .. 2^64-2`.

For each chunk, the AES-GCM AAD is:

```text
complete AVLT02 header || chunk_index(uint64, big-endian) || ciphertext_length(uint32, big-endian)
```

The chunk nonce is:

```text
base_nonce[0:4] || chunk_index(uint64, big-endian)
```

This binds the header, chunk position and exact chunk length to authentication.

## Validation rules

A production decryptor must:

1. Validate magic, version and flags.
2. Validate all fixed-length reads.
3. Reject unsupported chunk sizes.
4. Reject sizes above the application maximum.
5. Authenticate the header before processing chunks.
6. Require each chunk length to equal the expected plaintext length.
7. Reject zero-length chunks.
8. Authenticate every chunk before committing its plaintext to the final file.
9. Verify recovered size equals `original_size`.
10. Reject any trailing bytes after the expected final chunk.
11. Write to a restricted temporary file and atomically replace the destination
    only after complete successful authentication.

An empty file is represented by a valid authenticated header and header tag with
no chunks.

## AVLT01 compatibility

AVLT01 used the following legacy structure:

```text
magic(6) | version(1) | salt(16) | base_nonce(12) | original_size(8)
chunks...
```

Its chunk AAD was `AVLT01 || chunk_index(uint64)`. AVLT01 does not authenticate
its header, so it cannot provide the same tamper resistance as AVLT02. The current
implementation reads AVLT01 only to preserve recovery of existing user files.

## Atomic storage

Encryption and decryption are performed into a randomly named temporary file in
the destination directory with restrictive permissions where supported. The
file is flushed and fsynced before an atomic rename. Failed or cancelled
operations remove the temporary artifact.

## Security boundaries

The format protects encrypted files against offline plaintext recovery without
the correct key and against undetected AVLT02 modification. It does not protect
a machine that is already compromised by malware/root/administrator access, a
keylogger, or an attacker able to inspect a running process.

Python/Qt cannot guarantee that every historical copy of plaintext or a key is
erased from physical RAM. The implementation therefore minimizes secret lifetime,
shares one bounded preview-session key rather than repeatedly passing passwords,
and clears managed mutable key buffers when the session ends.
