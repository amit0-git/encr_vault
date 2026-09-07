from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path
from threading import Event, Semaphore
from typing import Callable, BinaryIO

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# AVLT02 is the current hardened container. AVLT01 remains decryptable for
# backward compatibility, but new files are never written in the legacy format.
MAGIC = b"AVLT02"
LEGACY_MAGIC = b"AVLT01"
VERSION = 2
LEGACY_VERSION = 1
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 4 * 1024 * 1024
MAX_CHUNK_SIZE = CHUNK_SIZE
MAX_VAULT_SIZE = (1 << 63) - 1

# AVLT02 header:
# magic(6) | version(1) | flags(1) | salt(16) | base_nonce(12) |
# original_size(8) | chunk_size(4)
HEADER_STRUCT = struct.Struct(">6sBB16s12sQI")
HEADER_SIZE = HEADER_STRUCT.size
HEADER_TAG_LABEL = b"AVLT02-HEADER"
HEADER_NONCE_INDEX = (1 << 64) - 1
CHUNK_AAD_STRUCT = struct.Struct(">QI")
LEGACY_HEADER_STRUCT = struct.Struct(">6sB16s12sQ")
LEGACY_HEADER_SIZE = LEGACY_HEADER_STRUCT.size

# Argon2 is deliberately serialized. Running N 128-MiB KDFs concurrently can
# multiply RAM use dramatically and turn the application into a local DoS.
_KDF_GATE = Semaphore(1)


class VaultError(Exception):
    """Base class for safe, user-facing vault errors."""


class VaultFormatError(VaultError):
    pass


class VaultAuthenticationError(VaultError):
    pass


class VaultCorruptionError(VaultError):
    pass


class VaultCancelledError(VaultError):
    pass


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise VaultCancelledError("Operation cancelled.")


def _derive_key(password: str, salt: bytes) -> bytearray:
    if not password:
        raise ValueError("Encryption password/key cannot be empty.")
    password_bytes = bytearray(password.encode("utf-8"))
    try:
        with _KDF_GATE:
            raw = hash_secret_raw(
                bytes(password_bytes),
                salt,
                time_cost=3,
                memory_cost=128 * 1024,
                parallelism=2,
                hash_len=32,
                type=Type.ID,
            )
        return bytearray(raw)
    finally:
        _wipe(password_bytes)


def derive_key(password: str, salt: bytes) -> bytes:
    """Backward-compatible public API; callers should prefer internal key use."""
    key = _derive_key(password, salt)
    try:
        return bytes(key)
    finally:
        _wipe(key)


def _wipe(buf: bytearray | memoryview | None) -> None:
    if buf is None:
        return
    try:
        if isinstance(buf, memoryview):
            if not buf.readonly:
                buf[:] = b"\x00" * len(buf)
        else:
            buf[:] = b"\x00" * len(buf)
    except (TypeError, ValueError):
        pass


def _nonce(base: bytes, index: int) -> bytes:
    if len(base) != NONCE_SIZE:
        raise VaultFormatError("Invalid nonce.")
    if not 0 <= index <= HEADER_NONCE_INDEX:
        raise VaultFormatError("Chunk index is out of range.")
    return base[:4] + index.to_bytes(8, "big")


def _header_aad(header: bytes, index: int, length: int) -> bytes:
    return header + CHUNK_AAD_STRUCT.pack(index, length)


def _safe_destination(destination: Path) -> tuple[int, Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        os.fchmod(fd, 0o600)
    except (AttributeError, OSError):
        pass
    return fd, Path(tmp_name)


def _fsync_and_replace(fd: int, tmp_path: Path, destination: Path) -> None:
    """Commit a completed file without ever replacing an existing destination.

    A pre-existence check followed by os.replace() is subject to TOCTOU races.
    A same-filesystem hard-link gives us an atomic create-if-absent operation:
    the link creation fails if another process wins the destination first.
    We fail closed if hard links are unavailable rather than falling back to a
    potentially overwriting rename.
    """
    os.fsync(fd)
    os.close(fd)
    try:
        os.link(tmp_path, destination)
    except FileExistsError as exc:
        raise FileExistsError(f"Output already exists: {destination}") from exc
    except OSError as exc:
        raise OSError(
            f"Unable to commit output atomically without replacement: {destination}"
        ) from exc
    else:
        try:
            tmp_path.unlink()
        except OSError:
            # The destination link is already committed. Leaving the temporary
            # hard link behind is harmless and cleanup can remove it later.
            pass

    try:
        dir_fd = os.open(str(destination.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _cleanup_temp(fd: int, tmp_path: Path) -> None:
    if fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _validate_source(source: Path) -> int:
    st = source.stat()
    if not source.is_file():
        raise VaultFormatError("Input is not a regular file.")
    if st.st_size > MAX_VAULT_SIZE:
        raise VaultFormatError("File is too large for this vault format.")
    return st.st_size


def _validate_header(header: bytes):
    if len(header) != HEADER_SIZE:
        raise VaultFormatError("Invalid or truncated AES Vault file.")
    magic, version, flags, salt, base_nonce, original_size, chunk_size = HEADER_STRUCT.unpack(header)
    if magic != MAGIC or version != VERSION:
        raise VaultFormatError("Unsupported AES Vault file format.")
    if flags != 0:
        raise VaultFormatError("Unsupported AES Vault flags.")
    if not 0 < chunk_size <= MAX_CHUNK_SIZE:
        raise VaultFormatError("Invalid chunk size.")
    if original_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Declared file size is too large.")
    return salt, base_nonce, original_size, chunk_size


def _authenticate_header(fin: BinaryIO, header: bytes, key: bytearray, base_nonce: bytes) -> None:
    tag = fin.read(TAG_SIZE)
    if len(tag) != TAG_SIZE:
        raise VaultFormatError("Missing vault header authentication data.")
    try:
        decryptor = Cipher(
            algorithms.AES(key), modes.GCM(_nonce(base_nonce, HEADER_NONCE_INDEX), tag)
        ).decryptor()
        decryptor.authenticate_additional_data(header + HEADER_TAG_LABEL)
        decryptor.finalize()
    except InvalidTag as exc:
        raise VaultAuthenticationError("Unable to authenticate the vault.") from exc


def _encrypt_header_tag(header: bytes, key: bytearray, base_nonce: bytes) -> bytes:
    encryptor = Cipher(
        algorithms.AES(key), modes.GCM(_nonce(base_nonce, HEADER_NONCE_INDEX))
    ).encryptor()
    encryptor.authenticate_additional_data(header + HEADER_TAG_LABEL)
    encryptor.finalize()
    return encryptor.tag


def _decrypt_avlt02(
    fin: BinaryIO,
    fout: BinaryIO,
    password: str,
    progress: Callable[[int], None] | None,
    cancel_event: Event | None,
    source_size: int,
) -> None:
    header = fin.read(HEADER_SIZE)
    salt, base_nonce, original_size, chunk_size = _validate_header(header)
    if source_size < HEADER_SIZE + TAG_SIZE:
        raise VaultFormatError("Truncated AES Vault file.")

    key = _derive_key(password, salt)
    try:
        _authenticate_header(fin, header, key, base_nonce)
        processed = 0
        index = 0
        expected_chunks = (original_size + chunk_size - 1) // chunk_size

        while index < expected_chunks:
            _check_cancel(cancel_event)
            raw = fin.read(4)
            if len(raw) != 4:
                raise VaultFormatError("Truncated encrypted chunk length.")
            length = struct.unpack(">I", raw)[0]
            expected = min(chunk_size, original_size - processed)
            if length != expected or length <= 0:
                raise VaultFormatError("Invalid encrypted chunk length.")
            ciphertext = fin.read(length)
            tag = fin.read(TAG_SIZE)
            if len(ciphertext) != length or len(tag) != TAG_SIZE:
                raise VaultFormatError("Truncated encrypted data.")

            decryptor = Cipher(
                algorithms.AES(key), modes.GCM(_nonce(base_nonce, index), tag)
            ).decryptor()
            decryptor.authenticate_additional_data(_header_aad(header, index, length))
            try:
                plaintext = decryptor.update(ciphertext)
                decryptor.finalize()
            except InvalidTag as exc:
                raise VaultAuthenticationError("Unable to authenticate the vault.") from exc

            if len(plaintext) != length:
                raise VaultCorruptionError("Decrypted chunk size is invalid.")
            fout.write(plaintext)
            processed += len(plaintext)
            index += 1
            if progress:
                progress(processed)

        if processed != original_size:
            raise VaultCorruptionError("Decrypted size does not match the vault header.")
        if fin.read(1):
            raise VaultFormatError("Unexpected trailing data in AES Vault file.")
    finally:
        _wipe(key)


def _decrypt_avlt01(
    fin: BinaryIO,
    fout: BinaryIO,
    password: str,
    progress: Callable[[int], None] | None,
    cancel_event: Event | None,
    source_size: int,
) -> None:
    """Strict legacy reader. AVLT01 is not rewritten; AVLT02 is recommended."""
    header = fin.read(LEGACY_HEADER_SIZE)
    if len(header) != LEGACY_HEADER_SIZE:
        raise VaultFormatError("Invalid or truncated legacy AES Vault file.")
    magic, version, salt, base_nonce, original_size = LEGACY_HEADER_STRUCT.unpack(header)
    if magic != LEGACY_MAGIC or version != LEGACY_VERSION:
        raise VaultFormatError("Unsupported AES Vault file format.")
    if original_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Declared file size is too large.")

    key = _derive_key(password, salt)
    try:
        processed = 0
        index = 0
        expected_chunks = (original_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        while index < expected_chunks:
            _check_cancel(cancel_event)
            raw = fin.read(4)
            if len(raw) != 4:
                raise VaultFormatError("Truncated encrypted chunk.")
            length = struct.unpack(">I", raw)[0]
            expected = min(CHUNK_SIZE, original_size - processed)
            if length != expected or length <= 0:
                raise VaultFormatError("Invalid encrypted chunk length.")
            ciphertext = fin.read(length)
            tag = fin.read(TAG_SIZE)
            if len(ciphertext) != length or len(tag) != TAG_SIZE:
                raise VaultFormatError("Truncated encrypted data.")
            decryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, index), tag)).decryptor()
            decryptor.authenticate_additional_data(LEGACY_MAGIC + struct.pack(">Q", index))
            try:
                plaintext = decryptor.update(ciphertext)
                decryptor.finalize()
            except InvalidTag as exc:
                raise VaultAuthenticationError("Unable to authenticate the vault.") from exc
            fout.write(plaintext)
            processed += len(plaintext)
            index += 1
            if progress:
                progress(processed)
        if processed != original_size or fin.read(1):
            raise VaultFormatError("Invalid or trailing data in legacy AES Vault file.")
    finally:
        _wipe(key)


def encrypt_file(
    source: Path,
    destination: Path,
    password: str,
    progress: Callable[[int], None] | None = None,
    cancel_event: Event | None = None,
) -> None:
    source = Path(source)
    destination = Path(destination)
    total = _validate_source(source)
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must be different files.")

    # Detect source replacement/size changes before committing the result.
    initial_stat = source.stat()
    salt = os.urandom(SALT_SIZE)
    base_nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(password, salt)
    fd, tmp_path = _safe_destination(destination)
    committed = False
    try:
        header = HEADER_STRUCT.pack(MAGIC, VERSION, 0, salt, base_nonce, total, CHUNK_SIZE)
        with source.open("rb") as fin, os.fdopen(fd, "wb", closefd=False) as fout:
            fout.write(header)
            fout.write(_encrypt_header_tag(header, key, base_nonce))
            processed = 0
            index = 0
            while True:
                _check_cancel(cancel_event)
                plaintext = fin.read(CHUNK_SIZE)
                if not plaintext:
                    break
                length = len(plaintext)
                encryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, index))).encryptor()
                encryptor.authenticate_additional_data(_header_aad(header, index, length))
                ciphertext = encryptor.update(plaintext)
                encryptor.finalize()
                fout.write(struct.pack(">I", length))
                fout.write(ciphertext)
                fout.write(encryptor.tag)
                processed += length
                index += 1
                if progress:
                    progress(processed)
            fout.flush()

        final_stat = source.stat()
        if final_stat.st_size != initial_stat.st_size or final_stat.st_mtime_ns != initial_stat.st_mtime_ns:
            raise VaultCorruptionError("Input file changed while it was being encrypted.")
        if processed != total:
            raise VaultCorruptionError("Source size changed during encryption.")
        _fsync_and_replace(fd, tmp_path, destination)
        fd = -1
        committed = True
    finally:
        _wipe(key)
        if not committed:
            _cleanup_temp(fd, tmp_path)


def decrypt_file(
    source: Path,
    destination: Path,
    password: str,
    progress: Callable[[int], None] | None = None,
    cancel_event: Event | None = None,
) -> None:
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise VaultFormatError("Input vault is not a regular file.")
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must be different files.")

    source_size = source.stat().st_size
    fd, tmp_path = _safe_destination(destination)
    committed = False
    try:
        with source.open("rb") as fin, os.fdopen(fd, "wb", closefd=False) as fout:
            prefix = fin.read(6)
            fin.seek(0)
            if prefix == MAGIC:
                _decrypt_avlt02(fin, fout, password, progress, cancel_event, source_size)
            elif prefix == LEGACY_MAGIC:
                _decrypt_avlt01(fin, fout, password, progress, cancel_event, source_size)
            else:
                raise VaultFormatError("Unsupported or invalid AES Vault file.")
            fout.flush()
        _fsync_and_replace(fd, tmp_path, destination)
        fd = -1
        committed = True
    finally:
        if not committed:
            _cleanup_temp(fd, tmp_path)
