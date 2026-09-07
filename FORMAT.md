# AVLT01 Encryption File Format

## Purpose

This document specifies the on-disk format used by the Encryption App for encrypted
files. It is intended to make the encrypted data recoverable even if the original
Python/PySide6 GUI application is lost.

The format identifier is `AVLT01`.

> **Security note:** The password/key is never stored in an encrypted file. If the
> correct password is permanently lost, the encrypted data cannot be decrypted by
> this format.

---

## Cryptography

### Encryption algorithm

- **Cipher:** AES-256-GCM
- **Key size:** 32 bytes (256 bits)
- **Authentication:** GCM authentication tag, 16 bytes per encrypted chunk
- **Chunk size:** 4 MiB (`4 * 1024 * 1024` bytes)

### Password-based key derivation

The application derives the AES-256 key from the user's password using **Argon2id**.

Parameters:

| Parameter | Value |
|---|---:|
| Algorithm | Argon2id |
| Time cost | 3 |
| Memory cost | 128 MiB |
| Parallelism | 2 |
| Output length | 32 bytes |
| Salt length | 16 bytes |

The salt is random and is stored in the file header. It is not secret.

A compatible implementation must use the exact parameters above.

---

## File Layout

All integer fields use **big-endian** byte order unless otherwise stated.

```text
+----------------------+-----------------------------+
| Field                | Size                        |
+----------------------+-----------------------------+
| Magic                | 6 bytes                     |
| Version              | 1 byte                      |
| Salt                 | 16 bytes                    |
| Base nonce           | 12 bytes                    |
| Original file size   | 8 bytes                     |
| Repeated chunk data  | variable                   |
+----------------------+-----------------------------+
```

### 1. Magic

The first 6 bytes are the ASCII string:

```text
AVLT01
```

Hexadecimal:

```text
41 56 4C 54 30 31
```

A decryptor should reject files whose magic does not match.

### 2. Version

One byte identifying the format version.

Current value:

```text
0x01
```

A decryptor should reject unsupported versions rather than silently interpreting
them as version 1.

### 3. Salt

16 random bytes used by Argon2id.

```text
offset: 7
size:   16 bytes
```

The salt is required to reproduce the encryption key from the password.

### 4. Base nonce

12 random bytes used as the base nonce for AES-GCM.

```text
offset: 23
size:   12 bytes
```

The nonce is not secret, but nonce uniqueness is security-critical.

### 5. Original file size

An unsigned 64-bit little-endian integer containing the original plaintext size
in bytes.

```text
offset: 35
size:   8 bytes
```

This value allows the decryptor to restore the original file size exactly.

---

## Chunk Format

After the fixed 43-byte header, encrypted data is stored as a sequence of chunks.

Each chunk has:

```text
+----------------------+-----------------------------+
| Field                | Size                        |
+----------------------+-----------------------------+
| Chunk length         | 4 bytes, big-endian     |
| Ciphertext            | variable                   |
| GCM authentication tag| 16 bytes                    |
+----------------------+-----------------------------+
```

The `chunk length` is the number of ciphertext bytes in that chunk.

For normal encryption:

- Maximum chunk length = 4 MiB.
- All chunks except the final chunk are normally 4 MiB.
- The final chunk may be smaller.
- A zero-length final plaintext file has no plaintext chunks.

A compatible decryptor must validate chunk lengths before allocating memory.

---

## Nonce Construction

AES-GCM requires a unique nonce for every encryption operation performed with
the same key.

The application starts with the 12-byte `base nonce` from the header.

Each chunk derives its nonce from the base nonce and the chunk index.

Conceptually:

```text
nonce(chunk_index) =
    base_nonce with the final 8 bytes replaced with the big-endian chunk index
```

The chunk index is encoded as an unsigned 64-bit big-endian integer.

For example:

```text
chunk 0 -> base nonce + 0
chunk 1 -> base nonce + 1
chunk 2 -> base nonce + 2
...
```

The current implementation constructs each nonce as:

```python
nonce = base_nonce[:4] + chunk_index.to_bytes(8, "big")
```

The nonce must never be reused with the same AES key.

A replacement implementation must reproduce this construction exactly.

---

## Authentication

AES-GCM authenticates both the ciphertext and its associated data.

Each chunk has its own 16-byte authentication tag.

A wrong password normally results in authentication failure during the first
chunk rather than producing silently corrupted plaintext.

A decryptor **must not write unauthenticated plaintext to the final destination
file**. Prefer writing to a temporary file and replacing/renaming it only after
the complete file has authenticated successfully.

---

## Decryption Procedure

A compatible decryptor should perform these steps:

1. Open the `.aesvault` file in binary mode.
2. Read and validate the 6-byte magic.
3. Read and validate the version.
4. Read the 16-byte salt.
5. Read the 12-byte base nonce.
6. Read the 8-byte original plaintext size.
7. Derive the 32-byte AES key with Argon2id using the parameters above.
8. Read chunks until the encrypted file ends.
9. For each chunk:
   - Read the 4-byte ciphertext length.
   - Validate that the length is within the supported range.
   - Read exactly that many ciphertext bytes.
   - Read exactly 16 bytes of GCM tag.
   - Derive the nonce for the chunk index.
   - AES-GCM decrypt and authenticate the chunk.
10. Verify that the total recovered plaintext size equals the stored original
    file size.
11. Only after successful completion, finalize the output file.

If authentication fails, treat the password/key or file as invalid and stop
decryption.

---

## Wrong Password Behavior

A wrong password produces a different AES key because Argon2id derives the key
from the password and stored salt.

AES-GCM authentication should therefore fail.

A GUI should display **one** user-facing error for a failed decryption operation,
even when a folder contains many encrypted files. It should not display one
message box per failed file.

---

## File Naming

The application uses the `.aesvault` extension for encrypted files.

The encrypted file should retain enough metadata to restore the original
contents, but the original filename/path should not be assumed to be stored in
the cryptographic header unless the current application implementation explicitly
adds such metadata.

---

## Compatibility Requirements

A future recovery tool must preserve all of the following:

```text
Magic             = AVLT01
Version           = 1
Salt              = 16 bytes
Nonce              = 12 bytes
Original size      = uint64 big-endian
KDF                = Argon2id
KDF time cost      = 3
KDF memory cost    = 128 MiB
KDF parallelism    = 2
KDF output         = 32 bytes
Cipher             = AES-256-GCM
GCM tag             = 16 bytes
Chunk size          = 4 MiB
Nonce increment     = final 8 nonce bytes, big-endian
```

Changing any of these values can make an implementation incompatible with
existing encrypted files.

---

## Preview Behavior

The Secure Gallery may open an authenticated full-size preview in memory. The
default preview lifetime is **10 minutes** and can be changed in the UI from
**1 to 120 minutes**. The timer starts only after the preview has been
successfully authenticated and decoded.

A failed password/authentication must not open the large preview and must not
show a per-file error popup. The gallery should remain closed/locked until a
valid password is supplied.

## Long-Term Recovery Recommendations

Keep at least two independent copies of this specification.

For long-term recovery, preserve:

1. Encrypted `.aesvault` files.
2. The correct password/key.
3. This `FORMAT.md` specification.
4. A standalone recovery/decryption script.
5. A copy of the Python dependency versions used for cryptography.

Do **not** store the password inside the project source code or inside the
encrypted files.

It is also advisable to test recovery periodically using a small known test
file. For example:

```text
original.txt
    -> encrypt
    -> original.txt.aesvault
    -> decrypt
    -> recovered original.txt
```

Compare the recovered file byte-for-byte with the original.

---

## Reference Header Parser

The fixed header is 43 bytes:

```python
MAGIC = b"AVLT01"
HEADER_SIZE = 43

magic = f.read(6)
version = f.read(1)
salt = f.read(16)
base_nonce = f.read(12)
original_size = int.from_bytes(f.read(8), "little")
```

A production recovery tool should additionally check for truncated reads,
unsupported versions, invalid sizes, malformed chunk boundaries, authentication
failures, and output-size mismatches.

---

## Format Evolution

If the encryption format is changed in the future, create a new version rather
than changing the meaning of version 1 fields.

For example:

```text
AVLT01  -> current format
AVLT02  -> future incompatible format
```

A recovery application should dispatch to the correct parser based on the magic
and version.

Never silently treat an unknown version as `AVLT01`.

---

## Important Recovery Principle

The encrypted file and this specification are sufficient to describe how a
compatible decryptor should interpret the container, but **the password remains
essential**.

AES-256-GCM is designed so that knowing the algorithm and file format does not
allow someone to recover the plaintext without the correct encryption key.

## Preview Timer UI

The preview timeout is a single global session timer. The sidebar timer mirrors
that same remaining time; opening another large preview does not reset it.
When the global timer expires, the sidebar timer is removed along with the
preview session.

## Preview Session Timer

The preview timeout is a single global gallery-session timer.

- The timer starts immediately after a successful **Unlock gallery** action.
- A wrong password does not start the timer.
- Opening or closing individual large previews does not reset the timer.
- The sidebar displays the same remaining time as the global session timer.
- The large preview also displays the same remaining time.
- When the global timer expires, the preview session and sidebar timer are cleared.
