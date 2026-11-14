"""Ethereum, BNB Smart Chain and every other EVM chain (+ ERC-20/BEP-20 tokens).

Strategy per compromised account:
  1. Read native + token balances.
  2. Price gas aggressively (network fee * fee_boost).
  3. If there isn't enough native coin to pay gas for the token transfers
     (attackers usually drain ETH/BNB first to strand your tokens), a
     separate *gas tank* wallet tops the account up just enough.
  4. Fire all token transfers back-to-back with consecutive nonces, then
     sweep the remaining native coin. Nonces start at the *confirmed* count,
     so any pending transaction an attacker queued gets REPLACED by ours
     (we bid a higher fee).
  5. Every raw transaction is broadcast to all configured RPCs at once.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from eth_account import Account
from eth_utils import is_address, is_checksum_address, to_checksum_address

from .. import keys as K
from .base import Action, SweepError, Sweeper

EVM_CHAINS = {
    "ethereum": {
        "chain_id": 1, "symbol": "ETH",
        "rpc": ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com", "https://rpc.ankr.com/eth"],
        "tokens": {"USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                   "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
    },
    "bsc": {
        "chain_id": 56, "symbol": "BNB", "legacy": True,
        "rpc": ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org", "https://rpc.ankr.com/bsc"],
        "tokens": {"USDT": "0x55d398326f99059fF775485246999027B3197955",
                   "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"},
    },
    "polygon": {
        "chain_id": 137, "symbol": "POL",
        "rpc": ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"],
        "tokens": {"USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                   "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"},
    },
    "arbitrum": {
        "chain_id": 42161, "symbol": "ETH",
        "rpc": ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"],
        "tokens": {"USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                   "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"},
    },
    "base": {
        "chain_id": 8453, "symbol": "ETH",
        "rpc": ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
        "tokens": {"USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
    },
    "optimism": {
        "chain_id": 10, "symbol": "ETH",
        "rpc": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"],
        "tokens": {"USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                   "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58"},
    },
    "avalanche": {
        "chain_id": 43114, "symbol": "AVAX",
        "rpc": ["https://avalanche-c-chain-rpc.publicnode.com", "https://api.avax.network/ext/bc/C/rpc"],
        "tokens": {"USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
                   "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7"},
    },
}

# Block builders accepting eth_sendBundle (private, never hits the public mempool)
PRIVATE_RELAYS = {
    "ethereum": ["https://relay.flashbots.net", "https://rpc.titanbuilder.xyz",
                 "https://rpc.beaverbuild.org", "https://rsync-builder.xyz"],
}

SEL_BALANCE_OF = "0x70a08231"
SEL_TRANSFER = "a9059cbb"
SEL_DECIMALS = "0x313ce567"
NATIVE_GAS = 21_000
TOKEN_GAS_FALLBACK = 120_000


def _pad(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


class EvmSweeper(Sweeper):
    def __init__(self, entry, settings, log):
        super().__init__(entry, settings, log)
        chain = entry["chain"].lower()
        preset = EVM_CHAINS.get(chain, {})
        if not preset and "chain_id" not in entry:
            raise SweepError(f"unknown EVM chain {chain!r}: give chain_id + rpc")
        self.chain = chain
        self.chain_id = int(entry.get("chain_id", preset.get("chain_id", 0)))
        self.symbol = entry.get("symbol", preset.get("symbol", "NATIVE"))
        self.legacy = bool(entry.get("legacy", preset.get("legacy", False)))
        rpc = entry.get("rpc") or settings.get("rpc", {}).get(chain) or preset.get("rpc")
        self.rpcs = [rpc] if isinstance(rpc, str) else list(rpc or [])
        if not self.rpcs:
            raise SweepError("no RPC endpoint configured")
        self.tokens = self._resolve_tokens(entry.get("tokens", list(preset.get("tokens", {}))), preset)
        self.min_tip = int(Decimal(str(entry.get("min_tip_gwei", 0))) * 10**9)
        funder = entry.get("gas_tank") or settings.get("gas_tanks", {}).get("evm")
        self.funder = K.parse_hex_key(funder) if funder else None
        default_relays = PRIVATE_RELAYS.get(chain, []) if entry.get("private_relay", True) else []
        self.relays = entry.get("relays", default_relays)

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_tokens(spec, preset):
        out = []
        for t in spec:
            if isinstance(t, dict):
                out.append((t.get("symbol", t["address"][:8]), to_checksum_address(t["address"])))
            elif t.startswith("0x"):
                out.append((t[:8], to_checksum_address(t)))
            else:
                addr = preset.get("tokens", {}).get(t.upper())
                if not addr:
                    raise SweepError(f"token {t} unknown on this chain: give {{symbol, address}}")
                out.append((t.upper(), addr))
        return out

    def private_keys(self) -> list[bytes]:
        e = self.entry
        if "mnemonic" in e:
            n = int(e.get("accounts", 1))
            base = e.get("path", "m/44'/60'/0'/0")
            return [K.secp_from_mnemonic(e, f"{base}/{i}") for i in range(n)]
        ks = e.get("keys") or [e["key"]]
        return [K.parse_hex_key(k) for k in ks]

    def addresses(self):
        return [Account.from_key(k).address for k in self.private_keys()]

    def validate_destination(self):
        if not is_address(self.to):
            raise SweepError(f"destination {self.to} is not an EVM address")
        if self.to != self.to.lower() and not is_checksum_address(self.to):
            raise SweepError(f"destination {self.to} has a bad checksum (typo?)")
        self.to = to_checksum_address(self.to)

    # -- RPC helpers ---------------------------------------------------
    def call(self, method, params=None):
        last = None
        for url in self.rpcs:
            try:
                return self.rpc(url, method, params, retries=2)
            except SweepError as exc:
                last = exc
        raise last

    def broadcast(self, raw: bytes) -> str:
        """Spray the signed tx at every RPC simultaneously; first hash wins."""
        hexraw = "0x" + raw.hex()

        def send(url):
            try:
                return self.rpc(url, "eth_sendRawTransaction", [hexraw], retries=1), None
            except Exception as exc:
                return None, str(exc)

        with ThreadPoolExecutor(len(self.rpcs)) as pool:
            results = list(pool.map(send, self.rpcs))
        for txh, _ in results:
            if txh:
                return txh
        errors = "; ".join(e for _, e in results if e)
        if "already known" in errors.lower():
            from eth_utils import keccak
            return "0x" + keccak(raw).hex()
        raise SweepError(errors)

    def fees(self) -> dict:
        if self.legacy:
            gp = int(int(self.call("eth_gasPrice"), 16) * self.boost)
            return {"gasPrice": gp, "_max": gp}
        block = self.call("eth_getBlockByNumber", ["latest", False])
        base = int(block.get("baseFeePerGas", "0x0"), 16)
        try:
            tip = int(self.call("eth_maxPriorityFeePerGas"), 16)
        except SweepError:
            tip = 10**9
        tip = max(int(tip * self.boost), self.min_tip, 1)
        max_fee = int(base * 2 * max(1.0, self.boost / 1.5)) + tip
        return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip, "type": 2, "_max": max_fee}

    def token_balance(self, token: str, owner: str) -> int:
        res = self.call("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _pad(owner)}, "latest"])
        return int(res, 16) if res and res != "0x" else 0

    def token_decimals(self, token: str) -> int:
        try:
            return int(self.call("eth_call", [{"to": token, "data": SEL_DECIMALS}, "latest"]), 16)
        except Exception:
            return 18

    def sign(self, key: bytes, tx: dict) -> bytes:
        tx = {k: v for k, v in tx.items() if not k.startswith("_")}
        tx["chainId"] = self.chain_id
        return Account.sign_transaction(tx, key).raw_transaction

    def wait_receipt(self, txh: str, limit: float = 180) -> bool:
        end = time.time() + limit
        while time.time() < end:
            try:
                r = self.call("eth_getTransactionReceipt", [txh])
                if r:
                    return r.get("status") == "0x1"
            except SweepError:
                pass
            time.sleep(1)
        return False

    # ------------------------------------------------------------------
    def run(self, dry_run):
        self.validate_destination()
        for key in self.private_keys():
            try:
                self.sweep_account(key, dry_run)
            except Exception as exc:
                self.report.errors.append(str(exc))
                self.log(f"FAILED: {exc}", "error")
        return self.report

    def sweep_account(self, key: bytes, dry_run: bool):
        src = Account.from_key(key).address
        with ThreadPoolExecutor(8) as pool:
            f_nonce = pool.submit(self.call, "eth_getTransactionCount", [src, "latest"])
            f_pend = pool.submit(self.call, "eth_getTransactionCount", [src, "pending"])
            f_bal = pool.submit(self.call, "eth_getBalance", [src, "latest"])
            f_fee = pool.submit(self.fees)
            f_tok = {sym: pool.submit(self.token_balance, addr, src) for sym, addr in self.tokens}
            f_code = pool.submit(self.call, "eth_getCode", [self.to, "latest"])
        nonce = int(f_nonce.result(), 16)
        pending = int(f_pend.result(), 16)
        native = int(f_bal.result(), 16)
        fee = f_fee.result()
        dest_is_contract = f_code.result() not in ("0x", "0x0", None)
        native_gas = 60_000 if dest_is_contract else NATIVE_GAS
        tok_bal = {sym: f.result() for sym, f in f_tok.items()}
        token_addr = dict(self.tokens)

        if pending > nonce:
            self.log(f"{pending - nonce} PENDING tx from {src} (attacker?) -> replacing with higher fee", "warn")

        toks = ", ".join(f"{s}={v}" for s, v in tok_bal.items() if v) or "no tokens"
        self.log(f"{src}: {Decimal(native) / 10**18} {self.symbol}, {toks}")

        # gas for each token transfer
        token_txs = []
        for sym, bal in tok_bal.items():
            if bal <= 0:
                continue
            data = "0x" + SEL_TRANSFER + _pad(self.to) + hex(bal)[2:].rjust(64, "0")
            try:
                est = int(self.call("eth_estimateGas", [{"from": src, "to": token_addr[sym], "data": data}]), 16)
                gas = int(est * 1.3)
            except SweepError:
                gas = TOKEN_GAS_FALLBACK
            token_txs.append((sym, bal, data, gas))

        max_fee = fee["_max"]
        token_cost = sum(g for *_, g in token_txs) * max_fee
        bundle: list[bytes] = []
        if token_txs and native < token_cost:
            raw_topup = self.top_up(src, token_cost - native + native_gas * max_fee, fee, dry_run)
            if raw_topup is not None:
                native += raw_topup[1]
                if raw_topup[0]:
                    bundle.append(raw_topup[0])

        # build: token transfers first, then the native remainder
        planned: list[tuple[Action, dict]] = []
        for sym, bal, data, gas in token_txs:
            act = self.add(Action(sym, Decimal(bal) / 10 ** self.token_decimals(token_addr[sym]), src, self.to))
            if native < gas * max_fee:
                act.status, act.note = "failed", "not enough gas (configure a gas_tank)"
                self.log(f"{sym}: {act.note}", "error")
                continue
            native -= gas * max_fee
            planned.append((act, {"nonce": nonce, "to": token_addr[sym], "value": 0, "gas": gas, "data": data, **fee}))
            nonce += 1
        value = native - native_gas * max_fee
        if value > 0:
            act = self.add(Action(self.symbol, Decimal(value) / 10**18, src, self.to))
            planned.append((act, {"nonce": nonce, "to": self.to, "value": value, "gas": native_gas, "data": b"", **fee}))
        elif native > 0 and not token_txs:
            self.log(f"{self.symbol} balance is below the gas cost, nothing to move", "warn")

        if dry_run:
            for act, tx in planned:
                self.log(f"[drill] would send {act.amount} {act.asset} -> {act.dest} (nonce {tx['nonce']})"
                         + (" via private bundle" if bundle else ""))
            return
        signed = [(act, self.sign(key, tx)) for act, tx in planned]
        if bundle:
            self.send_private_bundle(bundle + [raw for _, raw in signed], [a for a, _ in signed])
            return
        for act, raw in signed:
            try:
                act.txid = self.broadcast(raw)
                act.status = "sent"
                self.log(f"SENT {act.amount} {act.asset} -> {act.dest}  tx {act.txid}", "ok")
            except Exception as exc:
                act.status, act.note = "failed", str(exc)
                self.log(f"{act.asset} send failed: {exc}", "error")
                break  # later nonces would be stuck anyway

    # -- gas tank ------------------------------------------------------
    def top_up(self, src: str, shortfall: int, fee: dict, dry_run: bool):
        """Returns (raw_tx_for_bundle_or_None, amount) or None if impossible.

        On chains with a private relay (Ethereum -> Flashbots & co) the top-up is
        put in the SAME private bundle as the token transfers, so attacker
        sweeper bots never see the gas arrive and can't steal it. Elsewhere it
        is broadcast publicly and we wait for it to confirm.
        """
        if not self.funder:
            self.log("not enough native coin to pay token gas and no gas_tank configured", "warn")
            return None
        amount = int(shortfall * 1.15)
        tank = Account.from_key(self.funder).address
        act = self.add(Action(self.symbol + " (gas top-up)", Decimal(amount) / 10**18, tank, src))
        private = bool(self.relays)
        if dry_run:
            self.log(f"[drill] gas tank {tank} would send {act.amount} {self.symbol}"
                     + (" inside a private bundle" if private else " publicly"))
            return (b"bundle" if private else None, amount)
        n = int(self.call("eth_getTransactionCount", [tank, "pending"]), 16)
        raw = self.sign(self.funder, {"nonce": n, "to": src, "value": amount, "gas": NATIVE_GAS, "data": b"", **fee})
        if private:
            act.status, act.note = "sent", "private bundle"
            return (raw, amount)
        act.txid = self.broadcast(raw)
        act.status = "sent"
        self.log(f"gas top-up sent {act.txid}, waiting for it to land...", "warn")
        if not self.wait_receipt(act.txid):
            raise SweepError("gas top-up did not confirm in time")
        return (None, amount)

    def send_private_bundle(self, raws: list[bytes], acts: list[Action]):
        from eth_account.messages import encode_defunct
        from eth_utils import keccak
        import json as _json

        head = int(self.call("eth_blockNumber"), 16)
        signer = Account.create()  # throwaway reputation key for the relay header
        txs = ["0x" + r.hex() for r in raws]
        for a, r in zip(acts, raws[-len(acts):]):
            a.txid = "0x" + keccak(r).hex()
            a.status, a.note = "sent", "private bundle"
        sent_any = False
        for blk in range(head + 1, head + 1 + int(self.entry.get("bundle_blocks", 20))):
            body = _json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_sendBundle",
                                "params": [{"txs": txs, "blockNumber": hex(blk)}]})
            sig = Account.sign_message(encode_defunct(text="0x" + keccak(text=body).hex()), signer.key).signature.hex()
            hdr = {"Content-Type": "application/json",
                   "X-Flashbots-Signature": f"{signer.address}:0x{sig.removeprefix('0x')}"}
            for relay in self.relays:
                try:
                    r = self.http.post(relay, data=body, headers=hdr, timeout=self.timeout)
                    sent_any |= r.ok and "error" not in r.text[:200].lower()
                except Exception:
                    pass
        if not sent_any:
            raise SweepError("every private relay rejected the bundle")
        self.log(f"private bundle submitted to {len(self.relays)} builders for the next blocks, waiting...", "warn")
        if self.wait_receipt(acts[0].txid, limit=12 * int(self.entry.get("bundle_blocks", 20))):
            for a in acts:
                self.log(f"LANDED {a.amount} {a.asset} -> {a.dest}  tx {a.txid}", "ok")
        else:
            for a in acts:
                a.status, a.note = "failed", "bundle not included (raise fee_boost)"
            raise SweepError("bundle was not included; rerun with a higher fee_boost")
