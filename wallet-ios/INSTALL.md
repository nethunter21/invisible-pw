# Install Unseen Vault on your iPhone (free)

Unseen Vault isn't on the App Store. You install it yourself with **SideStore**, a free open-source sideloading tool that signs apps with your normal Apple ID. You don't need a paid developer account.

Requirements: an iPhone on **iOS 15 or later**, a free Apple ID, and a Mac or Windows PC **once** for the initial SideStore setup. After that, everything happens on the phone.

---

## 1. Download the app file (.ipa)

1. Open **https://github.com/nethunter21/invisible-pw/releases** in Safari on your iPhone.
2. Open the newest **"Unseen Vault build N"** release and download **`UnseenVault.ipa`**. It saves to Files → Downloads.
3. *(Optional, recommended)* Check that the file wasn't tampered with. On a computer, run
   `shasum -a 256 UnseenVault.ipa` and compare the result with `UnseenVault.ipa.sha256` from the same release.
   Only download from this repository's Releases page. Never install a "wallet IPA" someone sends you.

## 2. Install SideStore (one-time, about 15 min)

Follow the official guide: **https://docs.sidestore.io**. Its steps change from time to time, so trust it over this summary. At the time of writing:

1. On the iPhone: **Settings → Privacy & Security → Developer Mode → On** (the phone restarts).
2. On your computer, use **iloader** (linked in the SideStore docs) to install SideStore onto the iPhone over USB and create its pairing file.
3. Install **LocalDevVPN** (formerly StosVPN) from the App Store. SideStore uses it to sign apps on-device without a computer.
4. Open SideStore and sign in with your Apple ID. Your password goes only to Apple. Using a secondary Apple ID is fine.

> AltStore Classic (https://altstore.io) works too, but it needs AltServer running on a computer on the same Wi-Fi every 7 days. SideStore doesn't.

## 3. Install Unseen Vault

1. Turn on LocalDevVPN, then open **SideStore → My Apps → "+"**.
2. Pick `UnseenVault.ipa` from Files. SideStore signs and installs it (about 30 s).
3. On the first launch, if iOS says "Untrusted Developer": **Settings → General → VPN & Device Management → your Apple ID → Trust**.

## 4. Keep it running: refresh every 7 days

Free Apple IDs sign apps for **7 days**. Before that runs out, open SideStore (with LocalDevVPN on) and tap **Refresh All**. SideStore also refreshes in the background when it can.

**If it expires, nothing is lost.** The app just won't open until you refresh it. Your encrypted wallet stays in the iPhone's keychain. Refresh and it opens again with the same PIN.

**What would lose the vault on this phone:** deleting the app, erasing or resetting the iPhone, or installing it with a *different* Apple ID. In all of those cases you restore with your **recovery phrase**. That's why step 5 matters.

## 5. First setup (do this carefully)

1. **Create new wallet**, tick the three checks, then tap **Tap to reveal**.
2. Write the **24 words on paper**, in order. Don't take a screenshot, use the camera, or save them in Notes, iCloud or a password manager.
3. Pass the 4-word check, then choose a **6-digit PIN** (it can't be 000000, 123456 or similar).
4. Optionally turn on Face ID.
5. **Test your backup before you deposit real money.** Send a small amount, then go to Settings → Show recovery phrase and check it against your paper. Ideally, restore on a second device to confirm the phrase works.

Store the paper somewhere safe from fire and water, and never type the words into any website. Unseen will never ask you for them.

## 6. Use it like a hardware wallet

- **Receive:** tap an asset → Receive → show the QR code or copy the address. Copied addresses clear from the clipboard after 60 s.
- **Send:** tap an asset → Send → paste or scan an address → Review. On the review screen, **check every character of the address** (it's split into groups of 4), then **hold to sign** and confirm with Face ID or your PIN.
- **Offline mode** (Settings → Privacy) blocks all network traffic. Turn it on whenever you're only storing funds.
- **Your own node:** Settings → Endpoints. Use a VPN or Orbot (Tor) if you want to hide your IP from public nodes.

## Supported in this build

| Network | Assets | Notes |
|---|---|---|
| Bitcoin | BTC | Native SegWit (bc1…), BIP84, RBF on |
| Ethereum | ETH, USDT, USDC | EIP-1559 |
| Solana | SOL, USDC, USDT (SPL) | creates the recipient's token account if needed |
| TON | TON, all jettons incl. **GRAM** and USDT | comments/memos supported |
| Telegram | usernames, anonymous numbers, gifts | **view only** in this build |
| TRON | TRX, USDT (TRC-20) | keep TRX for energy |
| XRP Ledger | XRP | destination tags; 1 XRP reserve |
| Litecoin | LTC | Native SegWit (ltc1…) |

Derivation paths follow the standard defaults used by Trust Wallet and most wallets (BIP44/84), so you can restore the same 24 words in another wallet if you ever need to.

**Not in this build yet:** Monero, swaps, Tornado Cash / Privacy Pools, sending Telegram collectibles, and multiple addresses per chain.

## Security model, in one paragraph

Your 24 words are generated on-device. They're encrypted with AES-256-GCM using a key derived from your PIN (PBKDF2, 310k rounds) **combined with a Secure Enclave hardware key that can't be exported**. That means the encrypted phrase can't be brute-forced off the phone even if the keychain is copied. Data is stored "this device only" and never syncs to iCloud. Wrong PINs trigger escalating lockouts (optional erase after 10). The app switcher shows a blank screen, the phrase hides during screen recording, and there are no analytics, trackers or accounts. Transactions are built and signed locally with Trust Wallet Core; only the signed transaction goes to the network.

**Honest limits:** a phone is a "hot" device compared with a dedicated hardware wallet. This app hasn't had an independent audit. Start with small amounts.
