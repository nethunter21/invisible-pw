"""Monero (XMR) via monero-wallet-rpc.

Monero keys can't be swept without a synced wallet, so this talks to a
`monero-wallet-rpc` you keep ready (local or on a trusted box). Two modes:

* `wallet_file` (+ `wallet_password`): open an existing synced wallet.
* `spend_key` + `view_key` + `address` (+ `restore_height`): restore a wallet
  from keys into the RPC on the fly, then refresh. Slower (needs sync).

Then `sweep_all` at the highest priority to your safe address.

NOTE: only *unlocked* XMR can move (outputs need 10 confirmations). There is
no fee replacement in Monero: the first valid spend of an output wins.
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from .base import Action, SweepError, Sweeper

PICONERO = Decimal(10**12)


class MoneroSweeper(Sweeper):
    chain = "monero"

    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        self.url = entry.get("rpc") or settings.get("rpc", {}).get("monero") or "http://127.0.0.1:18082/json_rpc"
        self.timeout = max(self.timeout, 120)
        auth = entry.get("rpc_login")
        if auth:
            from requests.auth import HTTPDigestAuth
            user, _, pw = auth.partition(":")
            self.http.auth = HTTPDigestAuth(user, pw)

    def addresses(self):
        return [self.entry.get("address") or f"(wallet file {self.entry.get('wallet_file', '?')})"]

    def validate_destination(self):
        if not (self.to[:1] in "48" and len(self.to) in (95, 106)):
            raise SweepError(f"{self.to} doesn't look like a Monero address")

    def call(self, method, params=None):
        return self.rpc(self.url, method, params or {}, retries=2)

    def run(self, dry_run):
        try:
            self._run(dry_run)
        except Exception as exc:
            self.report.errors.append(str(exc))
            self.log(f"FAILED: {exc}", "error")
        return self.report

    def _run(self, dry_run):
        self.validate_destination()
        e = self.entry
        if "wallet_file" in e:
            try:
                self.call("open_wallet", {"filename": e["wallet_file"], "password": e.get("wallet_password", "")})
            except SweepError as exc:
                if "already" not in str(exc).lower():
                    raise
        elif "spend_key" in e:
            name = "lc_" + secrets.token_hex(4)
            self.call("generate_from_keys", {
                "filename": name, "address": e["address"], "spendkey": e["spend_key"], "viewkey": e["view_key"],
                "password": secrets.token_hex(8), "restore_height": int(e.get("restore_height", 0)),
                "autosave_current": False})
            self.log("restored wallet from keys, syncing (this can take a while)...", "warn")
        self.call("refresh", {})
        bal = self.call("get_balance", {"account_index": int(e.get("account_index", 0)), "all_accounts": True})
        total, unlocked = Decimal(bal["balance"]) / PICONERO, Decimal(bal["unlocked_balance"]) / PICONERO
        self.log(f"{total} XMR total, {unlocked} unlocked")
        if total > unlocked:
            self.log(f"{total - unlocked} XMR still locked (needs confirmations) - run again later", "warn")
        if unlocked <= 0:
            return
        accounts = [int(a["account_index"]) for a in bal.get("per_subaddress", [])] or [0]
        if dry_run:
            self.add(Action("XMR", unlocked, "wallet", self.to))
            self.log(f"[drill] would sweep_all {unlocked} XMR -> {self.to}")
            return
        for idx in sorted(set(accounts)):
            try:
                res = self.call("sweep_all", {"address": self.to, "account_index": idx,
                                              "subaddr_indices_all": True, "priority": 4, "ring_size": 16})
            except SweepError as exc:
                if "no unlocked" in str(exc).lower() or "not enough" in str(exc).lower():
                    continue
                raise
            amount = Decimal(sum(res.get("amount_list", []))) / PICONERO
            act = self.add(Action("XMR", amount, f"account {idx}", self.to))
            act.txid, act.status = ", ".join(res.get("tx_hash_list", [])), "sent"
            self.log(f"SENT {amount} XMR -> {self.to}  tx {act.txid}", "ok")
