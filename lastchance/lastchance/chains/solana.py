"""Solana: SOL + every SPL token (USDC, USDT, memecoins...) in as few
transactions as possible.

* Each batch transaction: create the destination token account if missing,
  transfer_checked the full balance, close the emptied account (its rent goes
  to your safe wallet too).
* The SOL sweep rides inside the LAST batch so it can never starve the token
  transfers of fees.
* Priority fee = recent network priority fees * fee_boost (with a floor).
"""

from __future__ import annotations

import base64
import time
from decimal import Decimal

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from .. import keys as K
from .base import Action, SweepError, Sweeper

TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
KNOWN_MINTS = {
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}
ATA_RENT = 2_039_280
SIG_FEE = 5_000
TOKENS_PER_TX = 4
DEFAULT_RPC = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]


def ata(owner: Pubkey, mint: Pubkey, program: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([bytes(owner), bytes(program), bytes(mint)], ATA_PROGRAM)[0]


class SolanaSweeper(Sweeper):
    chain = "solana"

    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        rpc = entry.get("rpc") or settings.get("rpc", {}).get("solana") or DEFAULT_RPC
        self.rpcs = [rpc] if isinstance(rpc, str) else list(rpc)
        self.kp = Keypair.from_seed(K.solana_secret(entry))
        self.min_cu_price = int(entry.get("min_cu_price", 200_000))  # micro-lamports
        want = entry.get("tokens", "all")
        self.token_filter = None if want == "all" else {KNOWN_MINTS.get(t.upper(), t) for t in want}

    def addresses(self):
        return [str(self.kp.pubkey())]

    def validate_destination(self):
        try:
            self.dest = Pubkey.from_string(self.to)
        except Exception:
            raise SweepError(f"{self.to} is not a Solana address") from None
        if not self.dest.is_on_curve():
            raise SweepError("destination must be a normal wallet address (not a token/program account)")

    def call(self, method, params=None):
        last = None
        for url in self.rpcs:
            try:
                return self.rpc(url, method, params, retries=2)
            except SweepError as exc:
                last = exc
        raise last

    # ------------------------------------------------------------------
    def run(self, dry_run):
        try:
            self._run(dry_run)
        except Exception as exc:
            self.report.errors.append(str(exc))
            self.log(f"FAILED: {exc}", "error")
        return self.report

    def token_accounts(self, owner: Pubkey):
        out = []
        for program in (TOKEN_PROGRAM, TOKEN_2022):
            res = self.call("getTokenAccountsByOwner",
                            [str(owner), {"programId": str(program)}, {"encoding": "jsonParsed"}])
            for acc in res["value"]:
                info = acc["account"]["data"]["parsed"]["info"]
                if self.token_filter and info["mint"] not in self.token_filter:
                    continue
                amt = info["tokenAmount"]
                out.append({
                    "account": Pubkey.from_string(acc["pubkey"]), "mint": Pubkey.from_string(info["mint"]),
                    "program": program, "amount": int(amt["amount"]), "decimals": int(amt["decimals"]),
                    "frozen": info.get("state") == "frozen",
                })
        return out

    def cu_price(self) -> int:
        try:
            fees = [f["prioritizationFee"] for f in self.call("getRecentPrioritizationFees", [[]])]
            fees.sort()
            p90 = fees[int(len(fees) * 0.9)] if fees else 0
        except SweepError:
            p90 = 0
        return max(int(p90 * self.boost), self.min_cu_price)

    def _run(self, dry_run):
        self.validate_destination()
        me = self.kp.pubkey()
        lamports = self.call("getBalance", [str(me)])["value"]
        toks = [t for t in self.token_accounts(me) if not t["frozen"]]
        price = self.cu_price()
        sym = {v: k for k, v in KNOWN_MINTS.items()}
        self.log(f"{me}: {Decimal(lamports) / 10**9} SOL, {sum(1 for t in toks if t['amount'])} token(s) with balance")

        # which destination token accounts already exist?
        dest_atas = [ata(self.dest, t["mint"], t["program"]) for t in toks]
        exists = []
        if dest_atas:
            infos = self.call("getMultipleAccounts", [[str(a) for a in dest_atas], {"encoding": "base64"}])["value"]
            exists = [i is not None for i in infos]

        batches: list[list[Instruction]] = []
        batch_acts: list[list[Action]] = []
        current: list[Instruction] = []
        cur_acts: list[Action] = []
        budget_tokens = 0
        rent_spent = 0
        for t, dest_ata, ok in zip(toks, dest_atas, exists):
            ixs = []
            if t["amount"] > 0:
                if not ok:
                    rent_spent += ATA_RENT
                    ixs.append(Instruction(ATA_PROGRAM, bytes([1]), [
                        AccountMeta(me, True, True), AccountMeta(dest_ata, False, True),
                        AccountMeta(self.dest, False, False), AccountMeta(t["mint"], False, False),
                        AccountMeta(SYSTEM_PROGRAM, False, False), AccountMeta(t["program"], False, False)]))
                ixs.append(Instruction(t["program"],
                                       bytes([12]) + t["amount"].to_bytes(8, "little") + bytes([t["decimals"]]), [
                    AccountMeta(t["account"], False, True), AccountMeta(t["mint"], False, False),
                    AccountMeta(dest_ata, False, True), AccountMeta(me, True, False)]))
                name = sym.get(str(t["mint"]), str(t["mint"])[:6] + "..")
                cur_acts.append(self.add(Action(name, Decimal(t["amount"]) / 10 ** t["decimals"], str(me), self.to)))
            if t["program"] == TOKEN_PROGRAM:  # reclaim rent (Token-2022 may hold withheld fees)
                ixs.append(Instruction(TOKEN_PROGRAM, bytes([9]), [
                    AccountMeta(t["account"], False, True), AccountMeta(self.dest, False, True),
                    AccountMeta(me, True, False)]))
            current.extend(ixs)
            budget_tokens += 1
            if budget_tokens == TOKENS_PER_TX:
                batches.append(current)
                batch_acts.append(cur_acts)
                current, cur_acts, budget_tokens = [], [], 0
        if current or not batches:
            batches.append(current)
            batch_acts.append(cur_acts)

        def cu_limit(ixs):
            return 3_000 + 45_000 * sum(1 for i in ixs if i.program_id != SYSTEM_PROGRAM)

        fees = [SIG_FEE + (price * cu_limit(b) + 999_999) // 1_000_000 for b in batches]
        # last batch also carries the SOL transfer; budget an extra 1k CU for it
        fees[-1] = SIG_FEE + (price * (cu_limit(batches[-1]) + 1_000) + 999_999) // 1_000_000
        sol_out = lamports - sum(fees) - rent_spent
        if sol_out > 0:
            batches[-1].append(transfer(TransferParams(from_pubkey=me, to_pubkey=self.dest, lamports=sol_out)))
            batch_acts[-1].append(self.add(Action("SOL", Decimal(sol_out) / 10**9, str(me), self.to)))
        elif not toks:
            self.log("nothing to move")
            return
        if lamports < sum(fees) + rent_spent:
            self.log("not enough SOL for fees - fund this address with ~0.01 SOL and retry", "error")

        if dry_run:
            for a in self.report.actions:
                self.log(f"[drill] would send {a.amount} {a.asset} -> {a.dest}")
            self.log(f"[drill] {len(batches)} transaction(s), priority {price} µlamports/CU")
            return

        for i, ixs in enumerate(batches):
            if not ixs:
                continue
            last = i == len(batches) - 1
            limit = cu_limit(ixs) + (1_000 if last else 0)
            try:
                sig = self.send([set_compute_unit_limit(limit), set_compute_unit_price(price)] + ixs)
                if not last:
                    self.confirm(sig)
            except Exception as exc:
                for a in batch_acts[i]:
                    a.status, a.note = "failed", str(exc)[:200]
                self.log(f"batch {i + 1} failed: {exc}", "error")
                if last and any(a.asset != "SOL" for a in batch_acts[i]):
                    self.sweep_sol_only(price)
                continue
            for a in batch_acts[i]:
                a.txid, a.status = sig, "sent"
            self.log(f"SENT batch {i + 1}/{len(batches)}  tx {sig}", "ok")

    def sweep_sol_only(self, price: int):
        """Fallback when a token batch is rejected: at least get the SOL out."""
        me = self.kp.pubkey()
        lamports = self.call("getBalance", [str(me), {"commitment": "processed"}])["value"]
        fee = SIG_FEE + (price * 3_000 + 999_999) // 1_000_000
        if lamports <= fee:
            return
        act = self.add(Action("SOL", Decimal(lamports - fee) / 10**9, str(me), self.to))
        ix = transfer(TransferParams(from_pubkey=me, to_pubkey=self.dest, lamports=lamports - fee))
        act.txid = self.send([set_compute_unit_limit(3_000), set_compute_unit_price(price), ix])
        act.status = "sent"
        self.log(f"SENT {act.amount} SOL (fallback)  tx {act.txid}", "ok")

    def send(self, ixs) -> str:
        bh = Hash.from_string(self.call("getLatestBlockhash", [{"commitment": "processed"}])["value"]["blockhash"])
        tx = Transaction([self.kp], Message.new_with_blockhash(ixs, self.kp.pubkey(), bh), bh)
        raw = base64.b64encode(bytes(tx)).decode()
        opts = {"encoding": "base64", "preflightCommitment": "processed", "maxRetries": 10}
        sig, last = None, None
        for url in self.rpcs:  # spray to every RPC
            try:
                sig = self.rpc(url, "sendTransaction", [raw, opts], retries=1)
            except SweepError as exc:
                last = exc
        if not sig:
            raise last
        return sig

    def confirm(self, sig: str, limit: float = 45):
        end = time.time() + limit
        while time.time() < end:
            st = self.call("getSignatureStatuses", [[sig]])["value"][0]
            if st and st.get("err"):
                raise SweepError(f"tx {sig} failed: {st['err']}")
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return
            time.sleep(0.4)
        raise SweepError(f"tx {sig} not confirmed in {limit}s")
