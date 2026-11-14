"""Fire-time secret entry.

A wallet entry can carry an `ask` label instead of a stored key. At fire time
the tool asks once per distinct label for the seed phrase (or private key) and
injects it into every wallet that shares that label. So one seed phrase typed
once can cover ETH, BNB, BTC, SOL, ... — the `model9x` file itself never holds
the key.
"""

from __future__ import annotations

import copy

# BIP39 test vector — used only to *probe* a config at build/seal time (checks
# chain + path + destination are valid) and then thrown away. Never swept.
TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

_STORED = ("key", "keys", "mnemonic", "wallet_file", "spend_key")


def looks_like_mnemonic(secret: str) -> bool:
    words = secret.strip().split()
    return len(words) >= 12 and all(w.isalpha() for w in words)


def has_stored_secret(entry: dict) -> bool:
    return any(k in entry for k in _STORED)


def labels(config: dict) -> list[str]:
    """Distinct `ask` labels, in first-seen order, for enabled wallets that
    don't already carry a stored secret."""
    out: list[str] = []
    for w in config.get("wallets", []):
        if w.get("enabled", True) is False:
            continue
        lbl = w.get("ask")
        if lbl and not has_stored_secret(w) and lbl not in out:
            out.append(lbl)
    return out


def _apply(entry: dict, secret: str) -> None:
    if looks_like_mnemonic(secret):
        entry["mnemonic"] = secret.strip()
    else:
        entry["key"] = secret.strip()
    entry.pop("ask", None)


def inject(config: dict, secrets_map: dict[str, str]) -> dict:
    """Return a copy of config with typed secrets filled into `ask` entries."""
    cfg = copy.deepcopy(config)
    for w in cfg.get("wallets", []):
        lbl = w.get("ask")
        if lbl and lbl in secrets_map and not has_stored_secret(w):
            _apply(w, secrets_map[lbl])
    return cfg


def probe(config: dict) -> dict:
    """Return a copy where every `ask` entry gets the throwaway test mnemonic,
    so the config can be structurally validated without the real key."""
    cfg = copy.deepcopy(config)
    for w in cfg.get("wallets", []):
        if w.get("ask") and not has_stored_secret(w):
            w["mnemonic"] = TEST_MNEMONIC
            w["_probe"] = True
            w.pop("ask", None)
    return cfg


def resolve_interactive(config: dict, asker) -> dict:
    """asker(label) -> secret string. Asks once per distinct label."""
    needed = labels(config)
    smap = {lbl: asker(lbl) for lbl in needed}
    return inject(config, smap)
