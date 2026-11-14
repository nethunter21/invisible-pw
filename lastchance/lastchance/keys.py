"""Turn whatever you have (raw key, WIF, seed phrase...) into signing keys."""

from __future__ import annotations

import hashlib
import hmac
import json
import struct

from embit import bip32, bip39

HARDENED = 0x80000000


def mnemonic_seed(entry: dict) -> bytes:
    words = " ".join(entry["mnemonic"].split())
    return bip39.mnemonic_to_seed(words, password=entry.get("bip39_passphrase", ""))


def secp_from_mnemonic(entry: dict, path: str) -> bytes:
    """32-byte secp256k1 secret at a BIP32 path."""
    root = bip32.HDKey.from_seed(mnemonic_seed(entry))
    return root.derive(path).key.secret


def secp_account(entry: dict, account_path: str) -> bip32.HDKey:
    root = bip32.HDKey.from_seed(mnemonic_seed(entry))
    return root.derive(account_path)


def parse_hex_key(value: str) -> bytes:
    v = value.strip().lower()
    if v.startswith("0x"):
        v = v[2:]
    raw = bytes.fromhex(v)
    if len(raw) != 32:
        raise ValueError("expected a 32-byte hex private key")
    return raw


# ---------------------------------------------------------------- ed25519 (Solana)
def _parse_path(path: str) -> list[int]:
    parts = path.strip().split("/")
    if parts[0] != "m":
        raise ValueError(f"bad derivation path {path!r}")
    out = []
    for p in parts[1:]:
        if p.endswith("'") or p.endswith("h"):
            out.append(int(p[:-1]) + HARDENED)
        else:
            out.append(int(p))
    return out


def slip10_ed25519(seed: bytes, path: str) -> bytes:
    """SLIP-0010 ed25519 derivation (what Phantom/Solflare/Ledger use)."""
    digest = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    key, chain = digest[:32], digest[32:]
    for idx in _parse_path(path):
        if idx < HARDENED:
            raise ValueError("ed25519 derivation only supports hardened indexes")
        data = b"\x00" + key + struct.pack(">I", idx)
        digest = hmac.new(chain, data, hashlib.sha512).digest()
        key, chain = digest[:32], digest[32:]
    return key


def solana_secret(entry: dict) -> bytes:
    """Return a 32-byte ed25519 seed for a Solana wallet entry."""
    if "mnemonic" in entry:
        path = entry.get("path", "m/44'/501'/0'/0'")
        return slip10_ed25519(mnemonic_seed(entry), path)
    key = entry["key"]
    if isinstance(key, list):  # solana-keygen JSON array
        raw = bytes(key)
    else:
        key = key.strip()
        if key.startswith("["):
            raw = bytes(json.loads(key))
        else:
            from solders.keypair import Keypair

            return bytes(Keypair.from_base58_string(key).secret())
    return raw[:32]
