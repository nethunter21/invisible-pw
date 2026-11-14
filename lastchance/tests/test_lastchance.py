"""Offline tests: vault crypto, key derivation vectors, and fully signed
transactions for each chain against mocked network responses."""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lastchance import engine, vault  # noqa: E402
from lastchance.chains import make_sweeper  # noqa: E402

M = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
NOLOG = lambda *a, **k: None  # noqa: E731


# ------------------------------------------------------------------ vault
def test_vault_roundtrip_and_tamper(tmp_path):
    path = str(tmp_path / "model9x")
    cfg = {"wallets": [{"chain": "eth", "to": "0xabc"}]}
    vault.seal_config(cfg, "correct horse battery", path)
    assert vault.open_config(path, "correct horse battery") == cfg
    with pytest.raises(vault.VaultError):
        vault.open_config(path, "wrong passphrase!!")
    blob = bytearray(open(path, "rb").read())
    blob[40] ^= 1  # attacker flips one bit
    os.chmod(path, 0o600)
    open(path, "wb").write(bytes(blob))
    with pytest.raises(vault.VaultError, match="tamper"):
        vault.open_config(path, "correct horse battery")


def test_vault_has_no_recognisable_header(tmp_path):
    path = str(tmp_path / "model9x")
    vault.seal_config({"wallets": []}, "correct horse battery", path)
    data = open(path, "rb").read()
    assert b"wallets" not in data and b"chain" not in data


def test_shred(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text("secret")
    vault.shred(str(p))
    assert not p.exists()


# ------------------------------------------------------------------ keys
@pytest.mark.parametrize("chain,expected", [
    ("eth", "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"),
    ("btc", "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"),
    ("ltc", "ltc1qjmxnz78nmc8nq77wuxh25n2es7rzm5c2rkk4wh"),
    ("doge", "DBus3bamQjgJULBJtYXpEzDWQRwF5iwxgC"),
    ("sol", "HAgk14JpMQLgt6rVgv7cBQFJWFto5Dqxi472uT3DKpqk"),
    ("trx", "TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH"),
    ("xrp", "rHsMGQEkVNJmpGWs8XUBoTBiAAbwxZN5v3"),
])
def test_mnemonic_vectors(chain, expected):
    s = make_sweeper({"chain": chain, "mnemonic": M, "scan": 1, "to": "x"}, {}, NOLOG)
    assert s.addresses()[0] == expected


# ------------------------------------------------------------------ UTXO
def test_bitcoin_sweep_signs_all_script_types(monkeypatch):
    from embit.transaction import SIGHASH, Transaction
    from embit import script
    s = make_sweeper({"chain": "btc", "mnemonic": M, "scan": 1, "fee_boost": 1,
                      "to": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}, {}, NOLOG)
    cands = s.candidates()
    funded = {c[2].address(s.net) for c in cands if c[1] is cands[0][1] or True}
    utxo_by_addr = {a: [{"txid": f"{i:064x}", "vout": i, "value": 100_000}] for i, a in enumerate(sorted(funded))}
    monkeypatch.setattr(s, "utxos", lambda sc: utxo_by_addr.get(sc.address(s.net), []))
    monkeypatch.setattr(s, "fee_rate", lambda: 10.0)
    pushed = []
    monkeypatch.setattr(s, "push", lambda raw: pushed.append(raw) or "txid123")
    rep = s.run(dry_run=False)
    assert not rep.errors, rep.errors
    tx = Transaction.from_string(pushed[0])
    assert len(tx.vin) == 8 and len(tx.vout) == 1  # 4 types x (receive + change)
    assert tx.vout[0].script_pubkey == script.address_to_scriptpubkey(s.to)
    total = 8 * 100_000
    assert total - tx.vout[0].value < 10_000  # sane fee
    # verify every signature
    spks, vals = [], []
    for i, vin in enumerate(tx.vin):
        addr = sorted(funded)[vin.vout]
        c = next(c for c in cands if c[2].address(s.net) == addr)
        spks.append(c[2]); vals.append(100_000)
    for i, vin in enumerate(tx.vin):
        kind, pk, spk = next(c for c in cands if c[2] == spks[i])
        pub = pk.get_public_key()
        if kind == "p2tr":
            from embit.ec import SchnorrSig
            h = tx.sighash_taproot(i, script_pubkeys=spks, values=vals, sighash=SIGHASH.DEFAULT)
            assert pk.taproot_tweak(b"").get_public_key().schnorr_verify(SchnorrSig.parse(vin.witness.items[0]), h)
        elif kind in ("p2wpkh", "p2sh-p2wpkh"):
            from embit.ec import Signature
            h = tx.sighash_segwit(i, script.p2pkh(pub), 100_000)
            assert pub.verify(Signature.parse(vin.witness.items[0][:-1]), h)
        else:
            from embit.ec import Signature
            h = tx.sighash_legacy(i, spk)
            sig = vin.script_sig.data[1:1 + vin.script_sig.data[0] - 1]
            assert pub.verify(Signature.parse(sig), h)


# ------------------------------------------------------------------ EVM
class FakeEvm:
    def __init__(self, native, tokens, pending_extra=0, tip=10**9, base=20 * 10**9):
        self.native, self.tokens, self.pending_extra = native, tokens, pending_extra
        self.tip, self.base, self.sent = tip, base, []

    def __call__(self, url, method, params=None, retries=3):
        if method == "eth_getTransactionCount":
            return hex(5 + (self.pending_extra if params[1] == "pending" else 0))
        if method == "eth_getBalance":
            return hex(self.native)
        if method == "eth_getBlockByNumber":
            return {"baseFeePerGas": hex(self.base)}
        if method == "eth_maxPriorityFeePerGas":
            return hex(self.tip)
        if method == "eth_gasPrice":
            return hex(3 * 10**9)
        if method == "eth_getCode":
            return "0x"
        if method == "eth_estimateGas":
            return hex(50_000)
        if method == "eth_call":
            d = params[0]["data"]
            if d.startswith("0x70a08231"):
                return hex(self.tokens.get(params[0]["to"], 0))
            return hex(6)
        if method == "eth_sendRawTransaction":
            self.sent.append(params[0])
            return "0x" + "ab" * 32
        raise AssertionError(method)


def test_evm_sweeps_tokens_then_native_and_replaces_pending(monkeypatch):
    from eth_account import Account
    key = "0x" + "11" * 32
    usdt = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    s = make_sweeper({"chain": "eth", "key": key, "to": "0x000000000000000000000000000000000000dEaD",
                      "tokens": ["USDT"], "fee_boost": 2}, {}, NOLOG)
    fake = FakeEvm(native=10**17, tokens={usdt: 1234_000000}, pending_extra=1)
    monkeypatch.setattr(s, "rpc", fake)
    rep = s.run(dry_run=False)
    assert not rep.errors, rep.errors
    assert [a.asset for a in rep.actions] == ["USDT", "ETH"]
    assert all(a.status == "sent" for a in rep.actions)
    raws = sorted(set(fake.sent), key=fake.sent.index)
    from eth_account.typed_transactions import TypedTransaction
    from hexbytes import HexBytes
    tok = TypedTransaction.from_bytes(HexBytes(raws[0])).as_dict()
    nat = TypedTransaction.from_bytes(HexBytes(raws[1])).as_dict()
    assert tok["nonce"] == 5 and nat["nonce"] == 6  # starts at confirmed nonce -> replaces attacker's pending
    assert tok["maxPriorityFeePerGas"] == 2 * 10**9
    assert tok["data"].hex().startswith("a9059cbb")
    assert Account.recover_transaction(raws[0]) == Account.from_key(key).address
    spent = tok["gas"] * tok["maxFeePerGas"] + nat["gas"] * nat["maxFeePerGas"] + nat["value"]
    assert spent == 10**17  # nothing left behind at max fee


def test_evm_without_gas_reports_failure(monkeypatch):
    s = make_sweeper({"chain": "bsc", "key": "0x" + "22" * 32, "to": "0x000000000000000000000000000000000000dEaD",
                      "tokens": ["USDT"]}, {}, NOLOG)
    fake = FakeEvm(native=0, tokens={"0x55d398326f99059fF775485246999027B3197955": 10**18})
    monkeypatch.setattr(s, "rpc", fake)
    rep = s.run(dry_run=False)
    assert rep.actions[0].status == "failed" and not fake.sent


def test_evm_gas_tank_uses_private_bundle_on_ethereum(monkeypatch):
    usdt = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    s = make_sweeper({"chain": "eth", "key": "0x" + "33" * 32, "to": "0x000000000000000000000000000000000000dEaD",
                      "tokens": ["USDT"]}, {"gas_tanks": {"evm": "0x" + "44" * 32}}, NOLOG)
    fake = FakeEvm(native=0, tokens={usdt: 5_000000})
    orig = fake.__call__
    monkeypatch.setattr(s, "rpc", lambda u, m, p=None, retries=3: hex(100) if m == "eth_blockNumber" else
                        ({"status": "0x1"} if m == "eth_getTransactionReceipt" else orig(u, m, p)))
    bundles = []

    class R:
        ok, text = True, '{"result":{}}'
    monkeypatch.setattr(s.http, "post", lambda url, data=None, headers=None, timeout=None:
                        bundles.append((url, json.loads(data), headers)) or R())
    rep = s.run(dry_run=False)
    assert not rep.errors, rep.errors
    assert not fake.sent  # nothing touched the public mempool
    url, body, hdr = bundles[0]
    assert body["method"] == "eth_sendBundle" and len(body["params"][0]["txs"]) == 3  # top-up, USDT, leftover ETH
    assert "X-Flashbots-Signature" in hdr


# ------------------------------------------------------------------ Solana
def test_solana_batches_tokens_and_sol(monkeypatch):
    from solders.transaction import Transaction
    from lastchance.chains import solana as S
    dest = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    s = make_sweeper({"chain": "sol", "mnemonic": M, "to": dest}, {}, NOLOG)
    mints = [S.KNOWN_MINTS["USDC"], S.KNOWN_MINTS["USDT"]] + [str(S.ata(s.kp.pubkey(), s.kp.pubkey(), S.TOKEN_PROGRAM))] * 3
    sent = []

    def rpc(url, method, params=None, retries=3):
        if method == "getBalance":
            return {"value": 50_000_000}
        if method == "getTokenAccountsByOwner":
            if params[1]["programId"] != str(S.TOKEN_PROGRAM):
                return {"value": []}
            return {"value": [{"pubkey": str(S.ata(s.kp.pubkey(), S.Pubkey.from_string(m), S.TOKEN_PROGRAM)),
                               "account": {"data": {"parsed": {"info": {
                                   "mint": m, "state": "initialized",
                                   "tokenAmount": {"amount": str(1000 * (i + 1)), "decimals": 6}}}}}}
                              for i, m in enumerate(mints)]}
        if method == "getRecentPrioritizationFees":
            return [{"prioritizationFee": 1000, "slot": 1}]
        if method == "getMultipleAccounts":
            return {"value": [None] * len(params[0])}
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": "11111111111111111111111111111111"}}
        if method == "sendTransaction":
            sent.append(params[0])
            return f"sig{len(sent)}"
        if method == "getSignatureStatuses":
            return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
        raise AssertionError(method)
    monkeypatch.setattr(s, "rpc", rpc)
    rep = s.run(dry_run=False)
    assert not rep.errors, rep.errors
    assert len(set(sent)) == 2  # 5 tokens -> batch of 4 + batch of 1 (+SOL)
    txs = [Transaction.from_bytes(base64.b64decode(r)) for r in dict.fromkeys(sent)]
    for tx in txs:
        tx.verify()
        assert len(bytes(tx)) <= 1232
    assert rep.actions[-1].asset == "SOL" and rep.actions[-1].status == "sent"
    assert all(a.status == "sent" for a in rep.actions)


# ------------------------------------------------------------------ XRP
def test_xrp_payment_leaves_reserve(monkeypatch):
    from xrpl.core.binarycodec import decode
    s = make_sweeper({"chain": "xrp", "mnemonic": M, "to": "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
                      "destination_tag": 42}, {}, NOLOG)
    blobs = []

    def call(method, params):
        if method == "account_info":
            return {"account_data": {"Balance": "25000000", "Sequence": 7, "OwnerCount": 1}}
        if method == "server_state":
            return {"state": {"load_factor": 256, "load_base": 256, "validated_ledger":
                              {"reserve_base": 1_000_000, "reserve_inc": 200_000, "base_fee": 10, "seq": 1000}}}
        if method == "submit":
            blobs.append(params["tx_blob"])
            return {"engine_result": "tesSUCCESS", "tx_json": {"hash": "H"}}
    monkeypatch.setattr(s, "call", call)
    rep = s.run(dry_run=False)
    assert not rep.errors, rep.errors
    tx = decode(blobs[0])
    assert tx["TransactionType"] == "Payment" and tx["DestinationTag"] == 42
    assert int(tx["Amount"]) == 25_000_000 - 1_200_000 - int(tx["Fee"])
    assert "TxnSignature" in tx


# ------------------------------------------------------------------ engine
def test_one_broken_chain_does_not_stop_others(monkeypatch):
    cfg = {"wallets": [{"chain": "nonsense-chain", "key": "x", "to": "y"},
                       {"chain": "xmr", "wallet_file": "w", "to": "bad"}]}
    assert engine.fire(cfg, dry_run=True) == 1


# ------------------------------------------------------------------ prompts / ask-mode
from lastchance import prompts  # noqa: E402


def test_one_seed_fills_every_ask_wallet():
    cfg = {"wallets": [
        {"name": "eth", "chain": "eth", "to": "0x1", "ask": "main"},
        {"name": "btc", "chain": "btc", "to": "bc1", "ask": "main"},
        {"name": "stored", "chain": "sol", "to": "x", "key": "abc"},
    ]}
    assert prompts.labels(cfg) == ["main"]  # one prompt, shared label; stored wallet excluded
    out = prompts.inject(cfg, {"main": M})
    assert out["wallets"][0]["mnemonic"] == M and "ask" not in out["wallets"][0]
    assert out["wallets"][1]["mnemonic"] == M
    assert out["wallets"][2]["key"] == "abc"  # untouched


def test_inject_detects_key_vs_mnemonic():
    cfg = {"wallets": [{"chain": "eth", "to": "0x1", "ask": "k"}]}
    out = prompts.inject(cfg, {"k": "0x" + "11" * 32})
    assert out["wallets"][0]["key"].startswith("0x") and "mnemonic" not in out["wallets"][0]


def test_validate_accepts_ask_mode_without_keys():
    from lastchance import cli
    cfg = {"wallets": [{"name": "e", "chain": "eth", "to": "0x000000000000000000000000000000000000dEaD",
                        "ask": "main"}]}
    assert cli.validate(cfg) == []
    bad = {"wallets": [{"name": "e", "chain": "eth", "to": "nope", "ask": "main"}]}
    assert bad and cli.validate(bad)  # bad destination still caught via probe


# ------------------------------------------------------------------ kit builder
def test_kit_build_has_no_keys_when_ask_mode(tmp_path):
    from lastchance import kit, vault
    cfg = {"settings": {"fee_boost": 3}, "wallets": [
        {"name": "eth", "chain": "eth", "to": "0x000000000000000000000000000000000000dEaD", "ask": "main"},
    ]}
    out = str(tmp_path / "kit")
    info = kit.build_kit(cfg, "supersecret123", out, make_zip=True)
    import os
    for f in ("model9x", "run.py", "LASTCHANCE.bat", "lastchance.sh", "lastchance/cli.py", "lastchance/chains"):
        assert os.path.exists(os.path.join(out, f)), f
    assert not os.path.exists(os.path.join(out, "lastchance", "tests"))
    assert os.path.isfile(info["zip"]) and len(info["fingerprint"]) == 12
    reopened = vault.open_config(os.path.join(out, "model9x"), "supersecret123")
    w = reopened["wallets"][0]
    assert "ask" in w and "key" not in w and "mnemonic" not in w  # kit carries NO secret


# ------------------------------------------------------------------ dashboard (offline)
def test_dashboard_preview_and_build(tmp_path):
    from lastchance import dashboard
    p = dashboard.preview({"chain": "btc", "mnemonic": M, "scan": 1,
                           "to": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"})
    assert p["dest_ok"] and p["addresses"]
    bad = dashboard.preview({"chain": "eth", "mnemonic": M, "to": "not-an-addr"})
    assert not bad["dest_ok"]
    res = dashboard.build({"passphrase": "supersecret123", "out_dir": str(tmp_path / "k"),
                           "settings": {}, "wallets": [
                               {"name": "x", "chain": "eth",
                                "to": "0x000000000000000000000000000000000000dEaD", "ask": "main"}]})
    assert res["ok"] and res["fingerprint"]
