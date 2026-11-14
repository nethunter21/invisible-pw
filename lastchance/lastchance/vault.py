"""Encrypted, tamper-evident storage for the `model9x` file.

File layout (no header, no magic bytes -> indistinguishable from random data):

    salt (16 bytes) | nonce (12 bytes) | AES-256-GCM ciphertext + tag

The key is derived from your passphrase with scrypt (n=2^17, r=8, p=1,
~128 MiB of RAM per guess), which makes offline brute-forcing slow.

AES-GCM is *authenticated*: flipping a single bit anywhere in the file (for
example an attacker trying to swap your destination address) makes decryption
fail loudly. Nobody can change the config without knowing the passphrase.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SALT_LEN = 16
NONCE_LEN = 12
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
# Bound to the ciphertext as associated data so the blob can't be
# repurposed for another format/version.
AAD = b"lc/v1"


class VaultError(Exception):
    pass


def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def seal_bytes(plaintext: bytes, passphrase: str) -> bytes:
    if len(passphrase) < 10:
        raise VaultError("passphrase must be at least 10 characters")
    salt = secrets.token_bytes(SALT_LEN)
    nonce = secrets.token_bytes(NONCE_LEN)
    key = _derive(passphrase, salt)
    return salt + nonce + AESGCM(key).encrypt(nonce, plaintext, AAD)


def open_bytes(blob: bytes, passphrase: str) -> bytes:
    if len(blob) < SALT_LEN + NONCE_LEN + 16:
        raise VaultError("vault file is truncated or not a vault")
    salt, nonce, ct = blob[:SALT_LEN], blob[SALT_LEN:SALT_LEN + NONCE_LEN], blob[SALT_LEN + NONCE_LEN:]
    key = _derive(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, AAD)
    except InvalidTag:
        raise VaultError(
            "wrong passphrase OR the file was modified (tamper detected)"
        ) from None


def seal_config(config: dict, passphrase: str, path: str) -> None:
    data = json.dumps(config, separators=(",", ":")).encode("utf-8")
    blob = seal_bytes(data, passphrase)
    atomic_write(path, blob)


def open_config(path: str, passphrase: str) -> dict:
    with open(path, "rb") as fh:
        blob = fh.read()
    return json.loads(open_bytes(blob, passphrase).decode("utf-8"))


def atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(path):
            os.chmod(path, 0o600)  # make writable so replace works on Windows
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    try:
        os.chmod(path, 0o400)  # read-only (also sets the Windows read-only flag)
    except OSError:
        pass


def shred(path: str, passes: int = 3) -> None:
    """Best-effort overwrite + delete of a plaintext file.

    On SSDs / copy-on-write filesystems this can't guarantee the old blocks are
    gone, so prefer writing plaintext configs to a RAM disk or never to disk.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as fh:
            for _ in range(passes):
                fh.seek(0)
                fh.write(secrets.token_bytes(size))
                fh.flush()
                os.fsync(fh.fileno())
    finally:
        if os.path.exists(path):
            os.unlink(path)
