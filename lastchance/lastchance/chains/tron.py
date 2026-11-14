"""TRON: TRX + TRC-20 tokens (USDT-TRC20, USDC...).

TRC-20 transfers burn energy (paid in TRX). If the account has no TRX left,
an optional gas tank wallet tops it up first. Tokens are sent before TRX.
"""

from __future__ import annotations

import time
from decimal import Decimal

from .. import keys as K
from .base import Action, SweepError, Sweeper

TRC20 = {
    "USDT": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "USDC": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",
}
ENERGY_PER_TRANSFER = 135_000  # worst case (recipient has never held the token)
SUN = 1_000_000


class TronSweeper(Sweeper):
    chain = "tron"

    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        from tronpy import Tron
        from tronpy.keys import PrivateKey
        from tronpy.providers import HTTPProvider

        self.PK = PrivateKey
        url = entry.get("rpc") or settings.get("rpc", {}).get("tron")
        api_key = entry.get("api_key") or settings.get("api_keys", {}).get("trongrid")
        provider = HTTPProvider(url, timeout=self.timeout, api_key=api_key) if (url or api_key) else None
        self.client = Tron(provider) if provider else Tron()
        self.tokens = [(t.upper(), TRC20[t.upper()]) if isinstance(t, str) and t.upper() in TRC20
                       else (t["symbol"], t["address"]) for t in entry.get("tokens", list(TRC20))]
        tank = entry.get("gas_tank") or settings.get("gas_tanks", {}).get("tron")
        self.tank = PrivateKey(K.parse_hex_key(tank)) if tank else None

    def keys(self):
        e = self.entry
        if "mnemonic" in e:
            base = e.get("path", "m/44'/195'/0'/0")
            return [self.PK(K.secp_from_mnemonic(e, f"{base}/{i}")) for i in range(int(e.get("accounts", 1)))]
        return [self.PK(K.parse_hex_key(k)) for k in (e.get("keys") or [e["key"]])]

    def addresses(self):
        return [k.public_key.to_base58check_address() for k in self.keys()]

    def validate_destination(self):
        if not self.client.is_base58check_address(self.to):
            raise SweepError(f"{self.to} is not a TRON address")

    def run(self, dry_run):
        self.validate_destination()
        for key in self.keys():
            try:
                self.sweep(key, dry_run)
            except Exception as exc:
                self.report.errors.append(str(exc))
                self.log(f"FAILED: {exc}", "error")
        return self.report

    def sun_balance(self, addr):
        try:
            return int(self.client.get_account(addr).get("balance", 0))
        except Exception:
            return 0

    def sweep(self, key, dry_run):
        src = key.public_key.to_base58check_address()
        trx = self.sun_balance(src)
        holdings = []
        for sym, caddr in self.tokens:
            c = self.client.get_contract(caddr)
            bal = int(c.functions.balanceOf(src))
            if bal > 0:
                holdings.append((sym, c, bal, int(c.functions.decimals())))
        self.log(f"{src}: {Decimal(trx) / SUN} TRX, " + (", ".join(f"{s}" for s, *_ in holdings) or "no tokens"))

        try:
            perms = self.client.get_account_permission(src)
            owner_keys = perms.get("owner", {}).get("keys", [])
            if owner_keys and all(k["address"] != src for k in owner_keys):
                self.log("WARNING: owner permission was changed (attacker multisig trick) - "
                         "transactions from this key will be rejected", "error")
        except Exception:
            pass

        if holdings:
            energy_fee = self._energy_price()
            need = len(holdings) * ENERGY_PER_TRANSFER * energy_fee
            try:
                res = self.client.get_account_resource(src)
                have_energy = res.get("EnergyLimit", 0) - res.get("EnergyUsed", 0)
            except Exception:
                have_energy = 0
            need = max(0, need - have_energy * energy_fee)
            if trx < need:
                trx = self._top_up(src, need - trx, dry_run) or trx

        for sym, c, bal, dec in holdings:
            act = self.add(Action(sym, Decimal(bal) / 10**dec, src, self.to))
            if dry_run:
                self.log(f"[drill] would send {act.amount} {sym} -> {self.to}")
                continue
            try:
                txn = (c.functions.transfer(self.to, bal).with_owner(src)
                       .fee_limit(int(self.entry.get("fee_limit_trx", 150)) * SUN).build().sign(key))
                act.txid = txn.broadcast()["txid"]
                act.status = "sent"
                self.log(f"SENT {act.amount} {sym} -> {self.to}  tx {act.txid}", "ok")
            except Exception as exc:
                act.status, act.note = "failed", str(exc)
                self.log(f"{sym} failed: {exc}", "error")

        if holdings and not dry_run:
            time.sleep(3.5)  # let token txs land so the TRX balance reflects burned energy
            trx = self.sun_balance(src)
        self._sweep_trx(key, src, trx, dry_run)

    def _energy_price(self):
        try:
            for p in self.client.get_chain_parameters():
                if p["key"] == "getEnergyFee":
                    return int(p["value"])
        except Exception:
            pass
        return 210

    def _sweep_trx(self, key, src, trx, dry_run):
        reserve = 0
        try:
            if self.client.get_bandwidth(src) < 300:
                reserve += 300_000
        except Exception:
            reserve += 300_000
        try:
            self.client.get_account(self.to)
        except Exception:
            reserve += 1_100_000  # destination not activated yet
        amount = trx - reserve
        if amount <= 0:
            if trx:
                self.log("TRX balance too small to cover the network fee", "warn")
            return
        act = self.add(Action("TRX", Decimal(amount) / SUN, src, self.to))
        if dry_run:
            self.log(f"[drill] would send {act.amount} TRX -> {self.to}")
            return
        for extra in (0, 300_000, 1_100_000):
            try:
                amt = amount - extra
                act.amount = Decimal(amt) / SUN
                act.txid = self.client.trx.transfer(src, self.to, amt).build().sign(key).broadcast()["txid"]
                act.status = "sent"
                self.log(f"SENT {act.amount} TRX -> {self.to}  tx {act.txid}", "ok")
                return
            except Exception as exc:
                act.status, act.note = "failed", str(exc)
        self.log(f"TRX failed: {act.note}", "error")

    def _top_up(self, src, shortfall, dry_run):
        if not self.tank:
            self.log("no TRX to pay token energy and no gas_tank configured", "warn")
            return None
        amt = int(shortfall * 1.1)
        tank_addr = self.tank.public_key.to_base58check_address()
        act = self.add(Action("TRX (gas top-up)", Decimal(amt) / SUN, tank_addr, src))
        if dry_run:
            self.log(f"[drill] gas tank would send {act.amount} TRX for energy")
            return None
        txn = self.client.trx.transfer(tank_addr, src, amt).build().sign(self.tank).broadcast()
        act.txid, act.status = txn["txid"], "sent"
        txn.wait(timeout=60)
        self.log(f"gas top-up landed {act.txid}", "warn")
        return self.sun_balance(src)
