"""XRP Ledger.

1. Payment of everything above the reserve (fast, works for every account).
2. Optional AccountDelete (`delete_account: true`) to also recover the
   reserve (~1 XRP + 0.2 per owned object). Only works if the account owns no
   objects (trust lines, offers...) and is older than 256 ledgers.
"""

from __future__ import annotations

from decimal import Decimal

from .. import keys as K
from .base import Action, SweepError, Sweeper

DEFAULT_RPC = ["https://xrplcluster.com/", "https://s1.ripple.com:51234/", "https://s2.ripple.com:51234/"]
DROPS = 1_000_000


class XrpSweeper(Sweeper):
    chain = "xrp"

    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        rpc = entry.get("rpc") or settings.get("rpc", {}).get("xrp") or DEFAULT_RPC
        self.rpcs = [rpc] if isinstance(rpc, str) else list(rpc)
        self.wallet = self._wallet()

    def _wallet(self):
        from xrpl.constants import CryptoAlgorithm
        from xrpl.core.keypairs import derive_keypair
        from xrpl.wallet import Wallet

        e = self.entry
        if "mnemonic" in e:
            secret = K.secp_from_mnemonic(e, e.get("path", "m/44'/144'/0'/0/0"))
            from embit.ec import PrivateKey
            pub = PrivateKey(secret).get_public_key().sec().hex().upper()
            return Wallet(pub, "00" + secret.hex().upper(), algorithm=CryptoAlgorithm.SECP256K1)
        seed = e["key"].strip()
        algo = CryptoAlgorithm.ED25519 if seed.startswith("sEd") else CryptoAlgorithm.SECP256K1
        derive_keypair(seed, algorithm=algo)  # raises on a bad seed
        return Wallet.from_seed(seed, algorithm=algo)

    def addresses(self):
        return [self.wallet.address]

    def validate_destination(self):
        from xrpl.core.addresscodec import is_valid_classic_address, is_valid_xaddress
        if not (is_valid_classic_address(self.to) or is_valid_xaddress(self.to)):
            raise SweepError(f"{self.to} is not an XRP address")
        if self.to == self.wallet.address:
            raise SweepError("destination equals source")

    def call(self, method, params):
        last = None
        for url in self.rpcs:
            try:
                r = self.http.post(url, json={"method": method, "params": [params]}, timeout=self.timeout).json()
                res = r["result"]
                if res.get("status") == "error" and res.get("error") != "actNotFound":
                    raise SweepError(f"{method}: {res.get('error_message') or res.get('error')}")
                return res
            except Exception as exc:
                last = exc
        raise SweepError(str(last))

    def run(self, dry_run):
        try:
            self._run(dry_run)
        except Exception as exc:
            self.report.errors.append(str(exc))
            self.log(f"FAILED: {exc}", "error")
        return self.report

    def _run(self, dry_run):
        from xrpl.core.binarycodec import encode
        from xrpl.models.transactions import AccountDelete, Payment
        from xrpl.transaction import sign

        self.validate_destination()
        src = self.wallet.address
        info = self.call("account_info", {"account": src, "ledger_index": "current"})
        if info.get("error") == "actNotFound":
            self.log("account not activated / empty")
            return
        acct = info["account_data"]
        balance, seq, owners = int(acct["Balance"]), acct["Sequence"], acct.get("OwnerCount", 0)
        state = self.call("server_state", {})["state"]
        vl = state["validated_ledger"]
        reserve = vl["reserve_base"] + owners * vl["reserve_inc"]
        load = state.get("load_factor", 256) / max(state.get("load_base", 256), 1)
        fee = max(int(vl["base_fee"] * load * self.boost), 12)
        fee = min(fee, int(self.entry.get("max_fee_drops", 200_000)))
        ledger = vl["seq"]
        amount = balance - reserve - fee
        self.log(f"{src}: {Decimal(balance) / DROPS} XRP (reserve {Decimal(reserve) / DROPS}), fee {fee} drops")
        tag = self.entry.get("destination_tag")
        common = {"account": src, "destination": self.to, "sequence": seq, "fee": str(fee),
                  "last_ledger_sequence": ledger + 20, "signing_pub_key": self.wallet.public_key}
        if tag is not None:
            common["destination_tag"] = int(tag)

        if amount > 0:
            act = self.add(Action("XRP", Decimal(amount) / DROPS, src, self.to))
            if dry_run:
                self.log(f"[drill] would send {act.amount} XRP -> {self.to}")
            else:
                tx = sign(Payment(amount=str(amount), **common), self.wallet)
                self._submit(act, encode(tx.to_xrpl()))
            seq += 1

        if self.entry.get("delete_account"):
            if owners:
                self.log(f"can't AccountDelete: account owns {owners} object(s) (trust lines/offers)", "warn")
                return
            act = self.add(Action("XRP (reserve via AccountDelete)", Decimal(reserve) / DROPS, src, self.to))
            del_fee = vl["reserve_inc"]
            if dry_run:
                self.log(f"[drill] would AccountDelete -> {self.to} (fee {Decimal(del_fee) / DROPS} XRP)")
                return
            tx = sign(AccountDelete(**{**common, "sequence": seq, "fee": str(del_fee)}), self.wallet)
            self._submit(act, encode(tx.to_xrpl()))

    def _submit(self, act, blob):
        res = self.call("submit", {"tx_blob": blob})
        code = res.get("engine_result", "")
        act.txid = res.get("tx_json", {}).get("hash")
        if code.startswith("tes") or code in ("terQUEUED",):
            act.status = "sent"
            self.log(f"SENT {act.amount} {act.asset} -> {act.dest}  tx {act.txid}", "ok")
        else:
            act.status, act.note = "failed", f"{code}: {res.get('engine_result_message', '')}"
            self.log(f"{act.asset} rejected: {act.note}", "error")
