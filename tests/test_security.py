import os
import tempfile
import unittest
from pathlib import Path

from core.crypto import (
    HEADER_SIZE,
    TAG_SIZE,
    encrypt_file,
    decrypt_file,
    VaultAuthenticationError,
    VaultFormatError,
)
from core.preview import authenticate_vault
from core.preview import secure_preview_file



class VaultSecurityTests(unittest.TestCase):
    def test_roundtrip_and_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "source.bin"
            vault = root / "source.bin.aesvault"
            out = root / "restored.bin"
            src.write_bytes(os.urandom(100_123))
            encrypt_file(src, vault, "test")
            self.assertEqual(vault.read_bytes()[:6], b"AVLT02")
            decrypt_file(vault, out, "test")
            self.assertEqual(src.read_bytes(), out.read_bytes())

            empty = root / "empty.bin"
            empty_vault = root / "empty.aesvault"
            empty_out = root / "empty.restored"
            empty.write_bytes(b"")
            encrypt_file(empty, empty_vault, "test")
            decrypt_file(empty_vault, empty_out, "test")
            self.assertEqual(empty_out.read_bytes(), b"")

    def test_header_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            out = root / "out.bin"
            src.write_bytes(b"hello" * 100)
            encrypt_file(src, vault, "test")
            data = bytearray(vault.read_bytes())
            data[40] ^= 1  # original_size/header byte
            vault.write_bytes(data)
            with self.assertRaises(VaultAuthenticationError):
                decrypt_file(vault, out, "test")
            self.assertFalse(out.exists())

    def test_ciphertext_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            out = root / "out.bin"
            src.write_bytes(b"hello" * 1000)
            encrypt_file(src, vault, "test")
            data = bytearray(vault.read_bytes())
            first_ciphertext = HEADER_SIZE + TAG_SIZE + 4
            data[first_ciphertext] ^= 1
            vault.write_bytes(data)
            with self.assertRaises(VaultAuthenticationError):
                decrypt_file(vault, out, "test")
            self.assertFalse(out.exists())

    def test_trailing_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            out = root / "out.bin"
            src.write_bytes(b"hello")
            encrypt_file(src, vault, "test")
            with vault.open("ab") as f:
                f.write(b"garbage")
            with self.assertRaises(VaultFormatError):
                decrypt_file(vault, out, "test")
            self.assertFalse(out.exists())

    def test_wrong_password_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            out = root / "out.bin"
            src.write_bytes(os.urandom(8192))
            encrypt_file(src, vault, "test")
            with self.assertRaises(VaultAuthenticationError):
                decrypt_file(vault, out, "nope")
            self.assertFalse(out.exists())

    def test_secure_preview_temp_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            src.write_bytes(b"preview-data" * 1000)
            encrypt_file(src, vault, "test")
            with secure_preview_file(vault, password="test", max_bytes=1024 * 1024) as temp_path:
                self.assertTrue(temp_path.exists())
                self.assertEqual(temp_path.read_bytes(), src.read_bytes())
                self.assertEqual(temp_path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(temp_path.exists())

    def test_secure_preview_respects_memory_input_limit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            src.write_bytes(os.urandom(8192))
            encrypt_file(src, vault, "test")
            with self.assertRaises(VaultFormatError):
                with secure_preview_file(vault, password="test", max_bytes=1024):
                    pass

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            out = root / "out.bin"
            src.write_bytes(b"new data")
            encrypt_file(src, vault, "test")
            out.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                decrypt_file(vault, out, "test")
            self.assertEqual(out.read_bytes(), b"original")

    def test_first_chunk_tamper_fails_gallery_authentication(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "a.bin"
            vault = root / "a.aesvault"
            src.write_bytes(os.urandom(9000))
            encrypt_file(src, vault, "test")
            data = bytearray(vault.read_bytes())
            first_ciphertext = HEADER_SIZE + TAG_SIZE + 4
            data[first_ciphertext] ^= 1
            vault.write_bytes(data)
            with self.assertRaises(VaultAuthenticationError):
                key = authenticate_vault(vault, "test")
            self.assertFalse("key" in locals())


if __name__ == "__main__":
    unittest.main()
