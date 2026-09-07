# AES Vault — PySide6

Professional local media encryption/decryption application.

## Features
- AES-256-GCM authenticated encryption
- Argon2id password-based key derivation
- Chunked streaming processing for large files
- Parallel processing across files
- Photo/video encryption
- Batch `.aesvault` decryption
- Authentication failure and partial-output cleanup
- Progress and cancellation
- Encrypt / Decrypt GUI modes
- Dark / Light theme toggle
- Responsive Qt layouts
- Originals are never overwritten

## Install
```bash
python -m venv .venv
# activate the environment
pip install -r requirements.txt
python main.py
```

Never lose the encryption password. It is not stored or recoverable by AES Vault.
