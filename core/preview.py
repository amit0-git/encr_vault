from __future__ import annotations

import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .crypto import HEADER_SIZE, HEADER_STRUCT, MAGIC, TAG_SIZE, CHUNK_SIZE, _nonce, derive_key


def decrypt_preview(source: Path, password: str, max_bytes: int | None = None) -> bytes:
    """Authenticate/decrypt an encrypted media file into memory for preview.

    No plaintext file is created. The optional max_bytes is useful for image previews;
    video playback should use the temporary streaming path instead.
    """
    source = Path(source)
    with source.open("rb") as fin:
        header = fin.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise ValueError("Invalid or truncated AES Vault file.")
        magic, version, salt, base_nonce, original_size = HEADER_STRUCT.unpack(header)
        if magic != MAGIC or version != 1:
            raise ValueError("Unsupported AES Vault file format.")
        if max_bytes is not None and original_size > max_bytes:
            raise ValueError("Preview is too large to load into memory.")

        key = derive_key(password, salt)
        try:
            output = bytearray()
            processed = 0
            index = 0
            while processed < original_size:
                raw = fin.read(4)
                if len(raw) != 4:
                    raise ValueError("Truncated encrypted chunk.")
                length = struct.unpack(">I", raw)[0]
                if length > CHUNK_SIZE:
                    raise ValueError("Encrypted chunk is unexpectedly large.")
                ciphertext = fin.read(length)
                tag = fin.read(TAG_SIZE)
                if len(ciphertext) != length or len(tag) != TAG_SIZE:
                    raise ValueError("Truncated encrypted data.")
                nonce = _nonce(base_nonce, index)
                aad = MAGIC + struct.pack(">Q", index)
                decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(aad)
                plaintext = decryptor.update(ciphertext) + decryptor.finalize()
                output.extend(plaintext)
                processed += len(plaintext)
                index += 1
            if processed != original_size:
                raise ValueError("Decrypted size does not match the original size.")
            return bytes(output)
        finally:
            del key


def decrypt_to_temp(source: Path, password: str, temp_path: Path) -> None:
    """Decrypt to a caller-owned temporary file for QMediaPlayer compatibility."""
    from .crypto import decrypt_file
    decrypt_file(source, temp_path, password)
