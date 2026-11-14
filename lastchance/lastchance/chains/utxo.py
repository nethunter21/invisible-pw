"""Bitcoin, Litecoin and Dogecoin.

Every UTXO the keys control (native segwit, nested segwit, legacy and taproot
addresses are all scanned) is spent in ONE transaction with a single output to
your safe address. The transaction signals RBF and pays the network's
"fastest" fee rate * fee_boost. If an attacker already broadcast a spend of
the same coins, a higher-fee replacement is the only way to win, so the boost
matters here.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from embit import base58, bech32, script
from embit.ec import PrivateKey
from embit.script import Script, Witness
from embit.transaction import SIGHASH, Transaction, TransactionInput, TransactionOutput

from .. import keys as K
from .base import Action, SweepError, Sweeper

NETWORKS = {
    "bitcoin": {
        "symbol": "BTC", "wif": b"\x80", "p2pkh": b"\x00", "p2sh": b"\x05", "bech32": "bc",
        "types": ["p2wpkh", "p2tr", "p2sh-p2wpkh", "p2pkh"], "coin": 0,
        "api": "esplora", "url": ["https://mempool.space/api", "https://blockstream.info/api"],
        "dust": 546,
    },
    "litecoin": {
        "symbol": "LTC", "wif": b"\xb0", "p2pkh": b"\x30", "p2sh": b"\x32", "bech32": "ltc",
        "types": ["p2wpkh", "p2sh-p2wpkh", "p2pkh"], "coin": 2,
        "api": "esplora", "url": ["https://litecoinspace.org/api"],
        "dust": 5460,
    },
    "dogecoin": {
        "symbol": "DOGE", "wif": b"\x9e", "p2pkh": b"\x1e", "p2sh": b"\x16", "bech32": None,
        "types": ["p2pkh"], "coin": 3,
        "api": "blockcypher", "url": ["https://api.blockcypher.com/v1/doge/main"],
        "dust": 1_000_000, "min_rate": 10_000,  # sat/vB = 0.1 DOGE/kB min relay ~ 0.01, be generous
    },
}
DEFAULT_PURPOSE = {"p2pkh": 44, "p2sh-p2wpkh": 49, "p2wpkh": 84, "p2tr": 86}
INPUT_VBYTES = {"p2wpkh": 68, "p2sh-p2wpkh": 91, "p2pkh": 148, "p2tr": 58}


def address_to_script(addr: str, net: dict) -> Script:
    if net["bech32"] and addr.lower().startswith(net["bech32"] + "1"):
        ver, prog = bech32.decode(net["bech32"], addr)
        if ver is None:
            raise SweepError(f"invalid bech32 address {addr}")
        return Script(bytes([0x50 + ver if ver else 0, len(prog)]) + bytes(prog))
    try:
        data = base58.decode_check(addr)
    except Exception:
        raise SweepError(f"invalid address {addr} (bad checksum?)") from None
    if data[:1] == net["p2pkh"] and len(data) == 21:
        return Script(b"\x76\xa9\x14" + data[1:] + b"\x88\xac")
    if data[:1] == net["p2sh"] and len(data) == 21:
        return Script(b"\xa9\x14" + data[1:] + b"\x87")
    raise SweepError(f"{addr} is not a {net['symbol']} address")


def script_for(kind: str, pk: PrivateKey) -> Script:
    pub = pk.get_public_key()
    if kind == "p2wpkh":
        return script.p2wpkh(pub)
    if kind == "p2pkh":
        return script.p2pkh(pub)
    if kind == "p2sh-p2wpkh":
        return script.p2sh(script.p2wpkh(pub))
    if kind == "p2tr":
        return script.p2tr(pub)
    raise ValueError(kind)


class UtxoSweeper(Sweeper):
    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        self.chain = entry["chain"].lower()
        self.net = NETWORKS[self.chain]
        url = entry.get("api_url") or settings.get("rpc", {}).get(self.chain) or self.net["url"]
        self.urls = [url] if isinstance(url, str) else list(url)
        self.api = entry.get("api", self.net["api"])
        self.symbol = self.net["symbol"]

    # -- keys ----------------------------------------------------------
    def _parse_key(self, k: str) -> PrivateKey:
        k = k.strip()
        if len(k) in (64, 66):
            return PrivateKey(K.parse_hex_key(k))
        raw = base58.decode_check(k)
        if raw[:1] != self.net["wif"]:
            raise SweepError(f"WIF key is not for {self.symbol}")
        return PrivateKey(raw[1:33], compressed=len(raw) == 34)

    def candidates(self) -> list[tuple[str, PrivateKey, Script]]:
        """(kind, key, scriptPubKey) for every address we should look at."""
        e, out = self.entry, []
        types = e.get("address_types", self.net["types"])
        if "mnemonic" in e:
            scan = int(e.get("scan", 10))
            for kind in types:
                path = e.get("paths", {}).get(kind) or f"m/{DEFAULT_PURPOSE[kind]}'/{self.net['coin']}'/0'"
                acct = K.secp_account(e, path)
                for change in (0, 1):
                    for i in range(scan):
                        pk = acct.derive([change, i]).key
                        out.append((kind, pk, script_for(kind, pk)))
        else:
            for k in e.get("keys") or [e["key"]]:
                pk = self._parse_key(k)
                kinds = types if pk.compressed else ["p2pkh"]
                out.extend((kind, pk, script_for(kind, pk)) for kind in kinds)
        return out

    def addresses(self):
        return [s.address(self.net) for _, _, s in self.candidates()]

    def validate_destination(self):
        self.dest_script = address_to_script(self.to, self.net)

    # -- API -----------------------------------------------------------
    def utxos(self, sc: Script) -> list[dict]:
        addr = sc.address(self.net)
        if self.api == "esplora":
            for url in self.urls:
                try:
                    return [{"txid": u["txid"], "vout": u["vout"], "value": u["value"]}
                            for u in self.get(f"{url}/address/{addr}/utxo")]
                except SweepError:
                    continue
            raise SweepError(f"could not fetch UTXOs for {addr}")
        data = self.get(f"{self.urls[0]}/addrs/{addr}?unspentOnly=true&includeScript=true&limit=2000")
        refs = (data.get("txrefs") or []) + (data.get("unconfirmed_txrefs") or [])
        return [{"txid": r["tx_hash"], "vout": r["tx_output_n"], "value": r["value"]} for r in refs]

    def fee_rate(self) -> float:
        """sat/vB"""
        if self.api == "esplora":
            for url in self.urls:
                try:
                    rec = self.get(f"{url}/v1/fees/recommended")
                    return float(rec["fastestFee"])
                except SweepError:
                    try:
                        return float(self.get(f"{url}/fee-estimates")["1"])
                    except Exception:
                        continue
            return 50.0
        info = self.get(self.urls[0])
        return info.get("high_fee_per_kb", 1_000_000) / 1000

    def push(self, raw_hex: str) -> str:
        errors = []
        if self.api == "esplora":
            for url in self.urls:
                try:
                    r = self.http.post(f"{url}/tx", data=raw_hex, timeout=self.timeout)
                    if r.ok:
                        return r.text.strip()
                    errors.append(r.text[:200])
                except Exception as exc:
                    errors.append(str(exc))
        else:
            r = self.http.post(f"{self.urls[0]}/txs/push", json={"tx": raw_hex}, timeout=self.timeout)
            if r.ok:
                return r.json()["tx"]["hash"]
            errors.append(r.text[:200])
        raise SweepError("broadcast rejected: " + " | ".join(errors))

    # ------------------------------------------------------------------
    def run(self, dry_run):
        try:
            self._run(dry_run)
        except Exception as exc:
            self.report.errors.append(str(exc))
            self.log(f"FAILED: {exc}", "error")
        return self.report

    def _run(self, dry_run):
        self.validate_destination()
        cands = self.candidates()
        with ThreadPoolExecutor(min(16, len(cands))) as pool:
            f_rate = pool.submit(self.fee_rate)
            found = list(pool.map(lambda c: (c, self.utxos(c[2])), cands))
        inputs = [(c, u) for c, us in found for u in us]
        if not inputs:
            self.log("no coins found")
            return
        total = sum(u["value"] for _, u in inputs)
        rate = max(f_rate.result() * self.boost, self.net.get("min_rate", 1))
        vsize = 11 + 43 + sum(INPUT_VBYTES[c[0]] for c, _ in inputs)
        fee = math.ceil(vsize * rate)
        send = total - fee
        div = Decimal(10**8)
        self.log(f"{len(inputs)} UTXO(s), {Decimal(total) / div} {self.symbol}, fee {Decimal(fee) / div} @ {rate:.1f} sat/vB")
        if send < self.net["dust"]:
            raise SweepError("balance does not cover the fee")
        srcs = sorted({c[2].address(self.net) for c, _ in inputs})
        act = self.add(Action(self.symbol, Decimal(send) / div, ", ".join(srcs), self.to))
        if dry_run:
            self.log(f"[drill] would send {act.amount} {self.symbol} -> {self.to}")
            return

        tx = Transaction(
            version=2,
            vin=[TransactionInput(bytes.fromhex(u["txid"]), u["vout"], sequence=0xFFFFFFFD) for _, u in inputs],
            vout=[TransactionOutput(send, self.dest_script)],
        )
        spks = [c[2] for c, _ in inputs]
        values = [u["value"] for _, u in inputs]
        for i, ((kind, pk, spk), u) in enumerate(inputs):
            pub = pk.get_public_key()
            if kind == "p2tr":
                h = tx.sighash_taproot(i, script_pubkeys=spks, values=values, sighash=SIGHASH.DEFAULT)
                tx.vin[i].witness = Witness([pk.taproot_tweak(b"").schnorr_sign(h).serialize()])
            elif kind in ("p2wpkh", "p2sh-p2wpkh"):
                h = tx.sighash_segwit(i, script.p2pkh(pub), u["value"])
                tx.vin[i].witness = script.witness_p2wpkh(pk.sign(h), pub)
                if kind == "p2sh-p2wpkh":
                    tx.vin[i].script_sig = script.script_sig_p2sh(script.p2wpkh(pub))
            else:
                h = tx.sighash_legacy(i, spk)
                tx.vin[i].script_sig = script.script_sig_p2pkh(pk.sign(h), pub)
        act.txid = self.push(tx.serialize().hex())
        act.status = "sent"
        self.log(f"SENT {act.amount} {self.symbol} -> {self.to}  tx {act.txid}", "ok")
