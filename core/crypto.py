from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Callable

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"AVLT01"
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 4 * 1024 * 1024
HEADER_SIZE = len(MAGIC) + 1 + SALT_SIZE + NONCE_SIZE + 8

# Header:
# magic(6) | version(1) | salt(16) | base_nonce(12) | original_size(8)
HEADER_STRUCT = struct.Struct(">6sB16s12sQ")


def derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("Encryption password/key cannot be empty.")
    return hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=3,
        memory_cost=128 * 1024,  # 128 MiB
        parallelism=2,
        hash_len=32,
        type=Type.ID,
    )


def _nonce(base: bytes, index: int) -> bytes:
    # 96-bit nonce: 32-bit prefix + 64-bit chunk counter.
    return base[:4] + index.to_bytes(8, "big")


def encrypt_file(
    source: Path,
    destination: Path,
    password: str,
    progress: Callable[[int], None] | None = None,
) -> None:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    total = source.stat().st_size
    salt = os.urandom(SALT_SIZE)
    base_nonce = os.urandom(NONCE_SIZE)
    key = derive_key(password, salt)

    processed = 0
    index = 0

    with source.open("rb") as fin, destination.open("wb") as fout:
        fout.write(HEADER_STRUCT.pack(MAGIC, 1, salt, base_nonce, total))

        while True:
            plaintext = fin.read(CHUNK_SIZE)
            if not plaintext:
                break

            nonce = _nonce(base_nonce, index)
            # AAD binds each chunk to its position and the file header.
            aad = MAGIC + struct.pack(">Q", index)

            encryptor = Cipher(
                algorithms.AES(key),
                modes.GCM(nonce),
            ).encryptor()
            encryptor.authenticate_additional_data(aad)

            ciphertext = encryptor.update(plaintext) + encryptor.finalize()
            fout.write(struct.pack(">I", len(ciphertext)))
            fout.write(ciphertext)
            fout.write(encryptor.tag)

            processed += len(plaintext)
            index += 1
            if progress:
                progress(processed)

    # Best effort cleanup of secret material references.
    del key


def decrypt_file(
    source: Path,
    destination: Path,
    password: str,
    progress: Callable[[int], None] | None = None,
) -> None:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    processed = 0

    with source.open("rb") as fin:
        header = fin.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise ValueError("Invalid or truncated AES Vault file.")

        magic, version, salt, base_nonce, original_size = HEADER_STRUCT.unpack(header)
        if magic != MAGIC or version != 1:
            raise ValueError("Unsupported AES Vault file format.")

        key = derive_key(password, salt)

        try:
            with destination.open("wb") as fout:
                index = 0
                while processed < original_size:
                    length_raw = fin.read(4)
                    if len(length_raw) != 4:
                        raise ValueError("Truncated encrypted chunk.")

                    length = struct.unpack(">I", length_raw)[0]
                    if length > CHUNK_SIZE:
                        raise ValueError("Encrypted chunk is unexpectedly large.")

                    ciphertext = fin.read(length)
                    tag = fin.read(TAG_SIZE)
                    if len(ciphertext) != length or len(tag) != TAG_SIZE:
                        raise ValueError("Truncated encrypted data.")

                    nonce = _nonce(base_nonce, index)
                    aad = MAGIC + struct.pack(">Q", index)

                    decryptor = Cipher(
                        algorithms.AES(key),
                        modes.GCM(nonce, tag),
                    ).decryptor()
                    decryptor.authenticate_additional_data(aad)

                    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
                    fout.write(plaintext)

                    processed += len(plaintext)
                    index += 1
                    if progress:
                        progress(min(processed, original_size))

                if processed != original_size:
                    raise ValueError("Decrypted size does not match the original size.")
        except Exception:
            # Do not leave a misleading partial plaintext file.
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            del key
