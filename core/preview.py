from __future__ import annotations

import os
import shutil
import struct
import tempfile
import getpass
import re
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .crypto import (
    CHUNK_AAD_STRUCT,
    CHUNK_SIZE,
    HEADER_SIZE,
    HEADER_STRUCT,
    HEADER_TAG_LABEL,
    LEGACY_HEADER_SIZE,
    LEGACY_HEADER_STRUCT,
    LEGACY_MAGIC,
    MAGIC,
    MAX_VAULT_SIZE,
    TAG_SIZE,
    VERSION,
    VaultAuthenticationError,
    VaultFormatError,
    _derive_key,
    _nonce,
    _wipe,
    _header_aad,
    _validate_header,
    _authenticate_header,
    _check_cancel,
)


PREVIEW_MAX_SOURCE_PIXELS = 50_000_000
PREVIEW_MAX_SOURCE_DIMENSION = 32_768


def _preview_root() -> Path:
    """Return an Encrvault-private temp root, never a shared glob target."""
    base = Path(tempfile.gettempdir())
    if hasattr(os, "getuid"):
        suffix = str(os.getuid())
    else:
        suffix = re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser() or "user")
    root = base / f"encvault-previews-{suffix}"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _validate_preview_source_dimensions(reader, max_pixels: int = PREVIEW_MAX_SOURCE_PIXELS) -> tuple[int, int]:
    """Validate dimensions before asking Qt to allocate decoded pixels."""
    size = reader.size()
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        raise VaultFormatError("Unable to determine preview image dimensions safely.")
    width, height = int(size.width()), int(size.height())
    if width > PREVIEW_MAX_SOURCE_DIMENSION or height > PREVIEW_MAX_SOURCE_DIMENSION:
        raise VaultFormatError("Preview image dimensions exceed the security limit.")
    if width * height > max_pixels:
        raise VaultFormatError("Preview image exceeds the decoded pixel limit.")
    return width, height


def _decrypt_preview_v2(fin, password: str | None, max_bytes: int | None, key: bytearray | bytes | None = None) -> bytes:
    header = fin.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        raise VaultFormatError("Invalid or truncated AES Vault file.")
    magic, version, flags, salt, base_nonce, original_size, chunk_size = HEADER_STRUCT.unpack(header)
    if magic != MAGIC or version != VERSION or flags != 0:
        raise VaultFormatError("Unsupported AES Vault file format.")
    if not 0 < chunk_size <= CHUNK_SIZE or original_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Invalid AES Vault header.")
    if max_bytes is not None and original_size > max_bytes:
        raise VaultFormatError("Preview is too large to load into memory.")

    owned_key = key is None
    key = _derive_key(password, salt) if owned_key else key
    try:
        header_tag = fin.read(TAG_SIZE)
        if len(header_tag) != TAG_SIZE:
            raise VaultFormatError("Missing vault header authentication data.")
        try:
            verifier = Cipher(
                algorithms.AES(key), modes.GCM(_nonce(base_nonce, (1 << 64) - 1), header_tag)
            ).decryptor()
            verifier.authenticate_additional_data(header + HEADER_TAG_LABEL)
            verifier.finalize()
        except InvalidTag as exc:
            raise VaultAuthenticationError("Unable to authenticate the vault.") from exc

        output = bytearray()
        processed = 0
        expected_chunks = (original_size + chunk_size - 1) // chunk_size
        for index in range(expected_chunks):
            raw = fin.read(4)
            if len(raw) != 4:
                raise VaultFormatError("Truncated encrypted chunk.")
            length = struct.unpack(">I", raw)[0]
            expected = min(chunk_size, original_size - processed)
            if length != expected or length <= 0:
                raise VaultFormatError("Invalid encrypted chunk length.")
            ciphertext = fin.read(length)
            tag = fin.read(TAG_SIZE)
            if len(ciphertext) != length or len(tag) != TAG_SIZE:
                raise VaultFormatError("Truncated encrypted data.")
            decryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, index), tag)).decryptor()
            decryptor.authenticate_additional_data(_header_aad(header, index, length))
            try:
                plaintext = decryptor.update(ciphertext)
                decryptor.finalize()
            except InvalidTag as exc:
                raise VaultAuthenticationError("Unable to authenticate the vault.") from exc
            output.extend(plaintext)
            processed += len(plaintext)

        if processed != original_size or fin.read(1):
            raise VaultFormatError("Invalid or trailing data in AES Vault file.")
        return bytes(output)
    finally:
        if owned_key:
            _wipe(key)


def _decrypt_preview_v1(fin, password: str | None, max_bytes: int | None, key: bytearray | bytes | None = None) -> bytes:
    header = fin.read(LEGACY_HEADER_SIZE)
    if len(header) != LEGACY_HEADER_SIZE:
        raise VaultFormatError("Invalid or truncated legacy AES Vault file.")
    magic, version, salt, base_nonce, original_size = LEGACY_HEADER_STRUCT.unpack(header)
    if magic != LEGACY_MAGIC or version != 1:
        raise VaultFormatError("Unsupported AES Vault file format.")
    if original_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Invalid declared file size.")
    if max_bytes is not None and original_size > max_bytes:
        raise VaultFormatError("Preview is too large to load into memory.")

    owned_key = key is None
    key = _derive_key(password, salt) if owned_key else key
    try:
        output = bytearray()
        processed = 0
        expected_chunks = (original_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        for index in range(expected_chunks):
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
            output.extend(plaintext)
            processed += len(plaintext)
        if processed != original_size or fin.read(1):
            raise VaultFormatError("Invalid or trailing data in legacy AES Vault file.")
        return bytes(output)
    finally:
        if owned_key:
            _wipe(key)


def decrypt_preview(source: Path, password: str | None = None, max_bytes: int | None = None, key: bytearray | bytes | None = None) -> bytes:
    """Legacy compatibility API; prefer secure_preview_file for GUI/media use.

    This function necessarily returns plaintext bytes and therefore should only
    be used for small, explicitly bounded callers.
    """
    if password is None and key is None:
        raise ValueError("Password or derived key is required.")
    if password is not None and key is not None:
        raise ValueError("Provide password or derived key, not both.")
    source = Path(source)
    if not source.is_file():
        raise VaultFormatError("Preview source is not a regular file.")
    if source.stat().st_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Vault is too large.")
    with source.open("rb") as fin:
        magic = fin.read(6)
        fin.seek(0)
        if magic == MAGIC:
            return _decrypt_preview_v2(fin, password, max_bytes, key)
        if magic == LEGACY_MAGIC:
            return _decrypt_preview_v1(fin, password, max_bytes, key)
        raise VaultFormatError("Unsupported or invalid AES Vault file.")


def cleanup_stale_preview_files(max_age_seconds: int = 3600) -> None:
    """Remove abandoned preview directories belonging to this user."""
    root = _preview_root()
    now = time.time()
    try:
        for item in root.iterdir():
            try:
                if item.is_dir() and now - item.stat().st_mtime > max_age_seconds:
                    shutil.rmtree(item, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


@contextmanager
def secure_preview_file(
    source: Path,
    password: str | None = None,
    max_bytes: int | None = None,
    key: bytearray | bytes | None = None,
    cancel_event: Event | None = None,
):
    """Materialize an authenticated preview only in a private 0700 temp dir.

    This is deliberately used instead of returning a large plaintext bytes
    object.  The caller can let Qt's image reader stream/decode the file and
    the plaintext is removed immediately when the context exits.
    """
    if password is None and key is None:
        raise ValueError("Password or derived key is required.")
    if password is not None and key is not None:
        raise ValueError("Provide password or derived key, not both.")
    source = Path(source)
    if not source.is_file():
        raise VaultFormatError("Preview source is not a regular file.")
    if source.stat().st_size > MAX_VAULT_SIZE:
        raise VaultFormatError("Vault is too large.")

    temp_dir = Path(tempfile.mkdtemp(prefix="preview-", dir=str(_preview_root())))
    try:
        try:
            os.chmod(temp_dir, 0o700)
        except OSError:
            pass
        target = temp_dir / "preview.bin"
        # Reuse the authenticated streaming decryptors.  A private temp file
        # avoids the large plaintext byte[]/QImage/QPixmap duplication.
        with source.open("rb") as fin, target.open("wb") as fout:
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            prefix = fin.read(6)
            fin.seek(0)
            if prefix == MAGIC:
                header = fin.read(HEADER_SIZE)
                salt, base_nonce, original_size, chunk_size = _validate_header(header)
                if max_bytes is not None and original_size > max_bytes:
                    raise VaultFormatError("Preview is too large to load.")
                owned = key is None
                work_key = _derive_key(password, salt) if owned else key
                try:
                    _authenticate_header(fin, header, work_key, base_nonce)
                    _decrypt_stream_v2(fin, fout, header, base_nonce, original_size, chunk_size, work_key, cancel_event)
                finally:
                    if owned:
                        _wipe(work_key)
            elif prefix == LEGACY_MAGIC:
                header = fin.read(LEGACY_HEADER_SIZE)
                magic, version, salt, base_nonce, original_size = LEGACY_HEADER_STRUCT.unpack(header)
                if magic != LEGACY_MAGIC or version != LEGACY_VERSION:
                    raise VaultFormatError("Unsupported AES Vault file format.")
                if original_size > MAX_VAULT_SIZE:
                    raise VaultFormatError("Declared file size is too large.")
                if max_bytes is not None and original_size > max_bytes:
                    raise VaultFormatError("Preview is too large to load.")
                owned = key is None
                work_key = _derive_key(password, salt) if owned else key
                try:
                    _decrypt_stream_v1(fin, fout, base_nonce, original_size, work_key, cancel_event)
                finally:
                    if owned:
                        _wipe(work_key)
            else:
                raise VaultFormatError("Unsupported or invalid AES Vault file.")
            fout.flush()
            os.fsync(fout.fileno())
        yield target
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _decrypt_stream_v2(fin, fout, header, base_nonce, original_size, chunk_size, key, cancel_event):
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
        decryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, index), tag)).decryptor()
        decryptor.authenticate_additional_data(_header_aad(header, index, length))
        try:
            plaintext = decryptor.update(ciphertext)
            decryptor.finalize()
        except InvalidTag as exc:
            raise VaultAuthenticationError("Unable to authenticate the vault.") from exc
        try:
            if len(plaintext) != length:
                raise VaultCorruptionError("Decrypted chunk size is invalid.")
            fout.write(plaintext)
        finally:
            # bytes returned by cryptography cannot be reliably zeroized, but
            # dropping the reference immediately minimizes its lifetime.
            del plaintext
        processed += length
        index += 1
    if processed != original_size or fin.read(1):
        raise VaultFormatError("Invalid or trailing data in AES Vault file.")


def _decrypt_stream_v1(fin, fout, base_nonce, original_size, key, cancel_event):
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
        try:
            fout.write(plaintext)
        finally:
            del plaintext
        processed += length
        index += 1
    if processed != original_size or fin.read(1):
        raise VaultFormatError("Invalid or trailing data in legacy AES Vault file.")


def authenticate_vault(source: Path, password: str) -> bytearray:
    """Authenticate a vault without materializing plaintext; return session key."""
    source = Path(source)
    if not source.is_file():
        raise VaultFormatError("Vault is not a regular file.")
    with source.open("rb") as fin:
        magic = fin.read(6)
        fin.seek(0)
        if magic == MAGIC:
            header = fin.read(HEADER_SIZE)
            magic, version, flags, salt, base_nonce, original_size, chunk_size = HEADER_STRUCT.unpack(header)
            if magic != MAGIC or version != VERSION or flags != 0 or not 0 < chunk_size <= CHUNK_SIZE or original_size > MAX_VAULT_SIZE:
                raise VaultFormatError("Invalid AES Vault header.")
            key = _derive_key(password, salt)
            try:
                tag = fin.read(TAG_SIZE)
                if len(tag) != TAG_SIZE:
                    raise VaultFormatError("Missing vault header authentication data.")
                try:
                    verifier = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, (1 << 64) - 1), tag)).decryptor()
                    verifier.authenticate_additional_data(header + HEADER_TAG_LABEL)
                    verifier.finalize()
                except InvalidTag as exc:
                    raise VaultAuthenticationError("Unable to authenticate the vault.") from exc

                # Authenticate one real chunk before accepting the gallery as
                # unlocked. This catches a corrupted first chunk immediately
                # rather than reporting an apparently unlocked but unusable vault.
                if original_size:
                    raw = fin.read(4)
                    if len(raw) != 4:
                        raise VaultFormatError("Truncated encrypted chunk.")
                    length = struct.unpack(">I", raw)[0]
                    expected = min(chunk_size, original_size)
                    if length != expected or length <= 0:
                        raise VaultFormatError("Invalid encrypted chunk length.")
                    ciphertext = fin.read(length)
                    tag = fin.read(TAG_SIZE)
                    if len(ciphertext) != length or len(tag) != TAG_SIZE:
                        raise VaultFormatError("Truncated encrypted data.")
                    decryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, 0), tag)).decryptor()
                    decryptor.authenticate_additional_data(_header_aad(header, 0, length))
                    try:
                        plaintext = decryptor.update(ciphertext)
                        decryptor.finalize()
                    except InvalidTag as exc:
                        raise VaultAuthenticationError("Unable to authenticate the vault.") from exc
                    finally:
                        try:
                            del plaintext
                        except UnboundLocalError:
                            pass
                return key
            except Exception:
                _wipe(key)
                raise

        if magic == LEGACY_MAGIC:
            # Legacy containers have no authenticated header. Authenticate the
            # first chunk (or the empty-file representation) before retaining key.
            header = fin.read(LEGACY_HEADER_SIZE)
            if len(header) != LEGACY_HEADER_SIZE:
                raise VaultFormatError("Invalid or truncated legacy AES Vault file.")
            _, version, salt, base_nonce, original_size = LEGACY_HEADER_STRUCT.unpack(header)
            if version != 1 or original_size > MAX_VAULT_SIZE:
                raise VaultFormatError("Invalid legacy AES Vault header.")
            key = _derive_key(password, salt)
            try:
                if original_size == 0:
                    return key
                raw = fin.read(4)
                if len(raw) != 4:
                    raise VaultFormatError("Truncated encrypted chunk.")
                length = struct.unpack(">I", raw)[0]
                expected = min(CHUNK_SIZE, original_size)
                if length != expected or length <= 0:
                    raise VaultFormatError("Invalid encrypted chunk length.")
                ciphertext = fin.read(length)
                tag = fin.read(TAG_SIZE)
                if len(ciphertext) != length or len(tag) != TAG_SIZE:
                    raise VaultFormatError("Truncated encrypted data.")
                decryptor = Cipher(algorithms.AES(key), modes.GCM(_nonce(base_nonce, 0), tag)).decryptor()
                decryptor.authenticate_additional_data(LEGACY_MAGIC + struct.pack(">Q", 0))
                try:
                    decryptor.update(ciphertext) + decryptor.finalize()
                except InvalidTag as exc:
                    raise VaultAuthenticationError("Unable to authenticate the vault.") from exc
                return key
            except Exception:
                _wipe(key)
                raise
        raise VaultFormatError("Unsupported or invalid AES Vault file.")


def decrypt_to_temp(source: Path, password: str, temp_path: Path) -> None:
    """Decrypt using the same authenticated, atomic core used by normal restore."""
    from .crypto import decrypt_file
    decrypt_file(source, temp_path, password)
