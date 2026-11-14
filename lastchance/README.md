# LAST CHANCE — emergency crypto sweeper

You find out a wallet is compromised. Double-click **one file**, type **one passphrase**, and every coin and token you configured moves to your safe wallets **in parallel, at the same time**, with aggressive fees.

```
  ██╗      █████╗ ███████╗████████╗     ██████╗██╗  ██╗ █████╗ ███╗   ██╗ ██████╗███████╗
  ...
   0.91s [    eth-main] 0xAb..: 0.84 ETH, USDC=12500000000
   0.93s [    eth-main] 1 PENDING tx from 0xAb.. (attacker?) -> replacing with higher fee
   1.20s [    eth-main] SENT 12500 USDC -> 0xCold..  tx 0x8f3...
   1.34s [         sol] SENT batch 1/1  tx 4Zk...
   1.52s [         btc] SENT 0.3141 BTC -> bc1q..  tx 9a1...
```

## Supported

| Chain | Assets | Keys it accepts |
|---|---|---|
| Ethereum, BNB Chain, Polygon, Arbitrum, Base, Optimism, Avalanche, + any EVM chain | native coin + USDC, USDT, any ERC-20/BEP-20 | hex key, list of keys, seed phrase (`accounts: N`) |
| Bitcoin | BTC: native segwit, taproot, nested segwit, legacy addresses | WIF / hex, seed phrase (scans receive + change) |
| Litecoin | LTC | WIF / hex, seed phrase |
| Dogecoin | DOGE | WIF / hex, seed phrase |
| Solana | SOL + **every** SPL token (USDC, USDT, memecoins), Token-2022 | Phantom base58 export, `solana-keygen` JSON, seed phrase |
| TRON | TRX + USDT-TRC20, USDC, any TRC-20 | hex key, seed phrase |
| XRP Ledger | XRP (+ optional AccountDelete to recover the reserve) | family seed (`s...`), seed phrase |
| Monero | XMR | via your `monero-wallet-rpc` (wallet file, or spend + view keys) |

Seed-phrase derivation is checked against the standard test vectors (BIP44/49/84/86, Phantom, TronLink, Xumm paths).

## How it tries to beat the attacker

* **Everything at once.** One thread per wallet; a slow or broken chain never blocks the others.
* **Fee boost.** Every fee is the network's current fast fee × `fee_boost` (default 2, set it to 3–10 for a real emergency).
* **Replaces the attacker's pending transactions (EVM).** Nonces start from the *confirmed* count, so a transaction the attacker queued but that hasn't been mined yet gets replaced by yours, which pays a higher fee.
* **Bitcoin/LTC/DOGE use RBF.** One transaction spends every UTXO, and it is replaceable, so you can re-run with a higher boost and outbid.
* **Tokens before gas.** Attackers usually drain ETH/BNB/TRX first so your USDT/USDC is stuck. A small separate **gas tank** wallet tops the account up.
* **Private bundles on Ethereum.** When a gas top-up is needed, the top-up and the token transfers go into one **Flashbots-style bundle** sent to several block builders. It never appears in the public mempool, so the attacker's sweeper bot can't steal the gas.
* **Sends to every RPC.** Each signed transaction goes to all configured RPC endpoints in parallel.
* **Solana in one shot.** Token transfers, account closes (the rent comes back to you) and the SOL sweep go into the fewest possible transactions. The SOL transfer rides in the last one, so it can't take the fees the token transfers need.
* **TRON permission check.** It warns you if the attacker has already changed the account's owner permission (a common TRON hijack).
* **Receipt.** When it finishes, it writes `receipt-<time>.json` with every txid. The receipt has no secrets.

## The `model9x` file

Your config, which holds the keys, lives **only** in `model9x`, encrypted:

* **AES-256-GCM** with a key derived by **scrypt** (128 MiB per guess, so offline brute force is slow).
* **No header or magic bytes.** The file looks like random noise, and nothing in it says what it is.
* **Tamper-evident.** Changing even 1 bit, for example to swap in the attacker's address, makes it refuse to open. **Nobody can change your destinations without your passphrase.**
* It is saved **read-only**. Plaintext configs are overwritten and deleted after sealing.
* When it unlocks, it prints a **destination fingerprint** (e.g. `DD1119D0BB94`). Write it down. If it ever shows something else, stop.

## Setup (do this NOW, before you need it)

```bash
./install.sh                      # Windows: install.bat
.venv/bin/python -m lastchance template > my-config.json
# edit my-config.json: keys, seed phrases, destination addresses
.venv/bin/python -m lastchance seal my-config.json   # -> model9x, plaintext shredded
.venv/bin/python -m lastchance addresses             # check every from/to address
.venv/bin/python -m lastchance drill                 # FULL REHEARSAL: real balances + fees, nothing sent
```

**Emergency:** double-click `LASTCHANCE.bat` (Windows) or `lastchance.sh` (Linux/macOS), type your passphrase, and it fires.

Other commands: `edit` (decrypt → editor → re-seal → shred), `show` (secrets masked), `passwd`.

To build a standalone single exe that needs no Python on the target machine, run `pip install pyinstaller && pyinstaller --onefile --name LASTCHANCE run.py`, then put `model9x` next to the exe.

## Config reference

See `model9x.example.json`. Per wallet entry:

| field | meaning |
|---|---|
| `chain` | `ethereum`/`eth`, `bsc`/`bnb`, `polygon`, `arbitrum`, `base`, `optimism`, `avalanche`, `bitcoin`/`btc`, `litecoin`/`ltc`, `dogecoin`/`doge`, `solana`/`sol`, `tron`/`trx`, `xrp`, `monero`/`xmr`; custom EVM: any name + `chain_id` + `rpc` |
| `to` | your safe address (validated, checksum-checked) |
| `key` / `keys` / `mnemonic` | secrets (+ `path`, `accounts`, `scan`, `bip39_passphrase`) |
| `tokens` | EVM/TRON: `["USDC","USDT", {"symbol":"X","address":"0x.."}]`; Solana: `"all"` (default) or a list |
| `fee_boost` | per-wallet override |
| `rpc` | string or list of endpoints (strongly recommended: your own paid RPCs, since public ones rate-limit) |
| `enabled` | `false` to skip |
| `destination_tag`, `delete_account` | XRP |
| `gas_tank`, `private_relay`, `relays`, `min_tip_gwei` | EVM advanced |

`settings`: `fee_boost`, `confirm` (ask "GO" before firing; default off for speed), `gas_tanks.evm` / `gas_tanks.tron`, `rpc.<chain>`, `api_keys.trongrid`, `receipt_dir`, `timeout`.

## Read this: honest limits

1. **It is a race, not a guarantee.** If the attacker has the same key and an automated sweeper bot, they may be faster. A higher `fee_boost`, private RPCs and a tested config improve your odds. Running `drill` regularly is what makes the real run work first time.
2. **A compromised PC can lie to you.** Encryption stops anyone *editing `model9x`*, but malware on the machine could modify the program or log your passphrase. The safest setup is to keep the tool + `model9x` on a USB stick (ideally write-protected) and run it from a **different, clean** computer. Check the destination fingerprint every time.
3. **`model9x` is a jackpot file.** It holds all your keys. Use a long passphrase (5+ random words), never upload it, and keep it off cloud sync. The `.gitignore` blocks committing it.
4. **Destinations should be fresh**: a hardware wallet, or a seed generated offline that has *never* touched the compromised machine. If you send to an exchange, set `destination_tag` for XRP.
5. **Not covered:** staked/locked positions (Solana stake accounts, ETH staking, DeFi/LP), NFTs, XRP-ledger IOUs, and still-locked Monero outputs (re-run after 10 confirmations). Once the tokens are moved, the attacker's token approvals are worthless, but revoke them anyway.
6. **Monero** needs a running, synced `monero-wallet-rpc`. Restoring from keys at sweep time is slow.
7. Default endpoints are public services. They work, but for a real emergency put your own RPC URLs in `settings.rpc`.

## Tests

```bash
pip install pytest && python -m pytest -q tests
```

The tests are offline. They cover the vault (round-trip, tamper detection), derivation vectors for every chain, and fully signed transactions with verified signatures for BTC (all 4 script types), EVM (nonce replacement, exact fee accounting, private bundle), Solana (batching, size limit) and XRP. They use mocked network responses.
