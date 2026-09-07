# AES Vault

Professional PySide6 desktop media encryption starter.

- AES-256-GCM authenticated encryption
- Argon2id password/key derivation
- Streaming/chunked processing with bounded memory
- Parallel file processing using a ThreadPoolExecutor
- PySide6 GUI with cancellation and progress
- Originals are never modified

Run:
    python -m venv .venv
    # activate the environment
    pip install -r requirements.txt
    python main.py
