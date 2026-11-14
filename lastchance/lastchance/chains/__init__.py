"""Chain registry: maps the `chain` field of a config entry to a sweeper."""

from __future__ import annotations

ALIASES = {
    "eth": "ethereum", "erc20": "ethereum",
    "bnb": "bsc", "bep20": "bsc", "binance": "bsc",
    "matic": "polygon", "pol": "polygon", "arb": "arbitrum", "op": "optimism", "avax": "avalanche",
    "btc": "bitcoin", "ltc": "litecoin", "doge": "dogecoin",
    "sol": "solana", "trx": "tron", "trc20": "tron",
    "xrp": "xrp", "ripple": "xrp", "xmr": "monero",
}
UTXO = {"bitcoin", "litecoin", "dogecoin"}


def canonical(chain: str) -> str:
    c = chain.strip().lower()
    return ALIASES.get(c, c)


def make_sweeper(entry: dict, settings: dict, log):
    entry = {**entry, "chain": canonical(entry["chain"])}
    c = entry["chain"]
    if c in UTXO:
        from .utxo import UtxoSweeper as S
    elif c == "solana":
        from .solana import SolanaSweeper as S
    elif c == "tron":
        from .tron import TronSweeper as S
    elif c == "xrp":
        from .xrp import XrpSweeper as S
    elif c == "monero":
        from .monero import MoneroSweeper as S
    else:  # ethereum, bsc, polygon, ... or any custom EVM chain with chain_id + rpc
        from .evm import EvmSweeper as S
    return S(entry, settings, log)
