import Foundation
import WalletCore
import SwiftProtobuf

enum EngineError: LocalizedError {
    case msg(String)
    var errorDescription: String? { if case .msg(let m) = self { return m }; return nil }
}

private func fail(_ m: String) -> EngineError { .msg(m) }

/// Everything fetched from the network that a signature depends on.
enum SignContext {
    case utxo(BitcoinSigningInput)
    case evm(nonce: BigUInt, maxFee: BigUInt, tip: BigUInt, gas: BigUInt)
    case sol(blockhash: String, senderATA: String?, recipientATA: String?, createATA: Bool)
    case xrp(sequence: UInt32, fee: Int64, ledger: UInt32, tag: UInt32?)
    case ton(seqno: UInt32)
    case tron(TronBlockHeader)
}

struct Quote {
    let asset: Asset
    let from: String
    let to: String
    let amount: BigUInt
    /// Network fee in the chain's native unit (upper bound when `feeIsMax`).
    let fee: BigUInt
    let feeIsMax: Bool
    let memo: String
    let notes: [String]
    let ctx: SignContext
}

struct SendRequest {
    let asset: Asset
    let from: String
    let to: String
    let amount: BigUInt
    let useMax: Bool
    let memo: String
    let nativeBalance: BigUInt
    let assetBalance: BigUInt
}

enum Engine {

    // MARK: - Public API

    static func balance(of asset: Asset, address: String) async throws -> BigUInt {
        switch asset.chain {
        case .bitcoin, .litecoin: return try await UTXO.balance(asset.chain, address)
        case .ethereum: return try await EVM.balance(asset, address)
        case .solana: return try await SOL.balance(asset, address)
        case .xrp: return try await XRPL.balance(address)
        case .ton: return try await TON.balance(address)
        case .tron: return try await TRON.balance(asset, address)
        }
    }

    static func quote(_ r: SendRequest, key: PrivateKey) async throws -> Quote {
        guard AnyAddress.isValid(string: r.to, coin: r.asset.chain.coin) else {
            throw fail("This is not a valid \(r.asset.chain.name) address.")
        }
        if r.to.caseInsensitiveCompare(r.from) == .orderedSame {
            throw fail("You can't send to your own address.")
        }
        if !r.useMax, r.amount.isZero { throw fail("Enter an amount greater than zero.") }
        if !r.asset.isNative, r.amount > r.assetBalance { throw fail("Insufficient \(r.asset.symbol) balance.") }

        let q: Quote
        switch r.asset.chain {
        case .bitcoin, .litecoin: q = try await UTXO.quote(r, key: key)
        case .ethereum: q = try await EVM.quote(r)
        case .solana: q = try await SOL.quote(r)
        case .xrp: q = try await XRPL.quote(r)
        case .ton: q = try await TON.quote(r)
        case .tron: q = try await TRON.quote(r)
        }

        // Final affordability check against the native balance.
        let nativeNeeded = q.asset.isNative ? q.amount + q.fee : q.fee
        if q.amount.isZero { throw fail("Amount is too small after network fees.") }
        let tronToken = q.asset.chain == .tron && !q.asset.isNative // fee_limit is a cap, not a hold
        if nativeNeeded > r.nativeBalance, !tronToken {
            throw fail("Insufficient \(q.asset.chain.symbol) to cover the amount plus network fee.")
        }
        return q
    }

    /// Signs locally and broadcasts. Returns the transaction id / hash.
    static func send(_ q: Quote, key: PrivateKey) async throws -> String {
        switch q.ctx {
        case .utxo(let input): return try await UTXO.send(q, input, key)
        case .evm(let nonce, let maxFee, let tip, let gas): return try await EVM.send(q, nonce, maxFee, tip, gas, key)
        case .sol(let bh, let s, let r, let c): return try await SOL.send(q, bh, s, r, c, key)
        case .xrp(let seq, let fee, let ledger, let tag): return try await XRPL.send(q, seq, fee, ledger, tag, key)
        case .ton(let seqno): return try await TON.send(q, seqno, key)
        case .tron(let header): return try await TRON.send(q, header, key)
        }
    }

    // MARK: - TON extras

    static func tonJettons(_ address: String) async throws -> [(Asset, BigUInt)] {
        try await TON.jettons(address)
    }

    static func tonNFTs(_ address: String) async throws -> [NFTItem] {
        try await TON.nfts(address)
    }
}

// MARK: - Bitcoin / Litecoin (Esplora API: mempool.space / litecoinspace.org)

private enum UTXO {
    static func balance(_ c: Chain, _ a: String) async throws -> BigUInt {
        let j = try await Net.shared.object(endpointURL(c, "/address/\(a)"))
        func net(_ k: String) -> Int64 { (j.d(k)?.i("funded_txo_sum") ?? 0) - (j.d(k)?.i("spent_txo_sum") ?? 0) }
        return BigUInt(max(0, net("chain_stats") + net("mempool_stats")))
    }

    static func quote(_ r: SendRequest, key: PrivateKey) async throws -> Quote {
        let c = r.asset.chain
        let raw = try await Net.shared.json(endpointURL(c, "/address/\(r.from)/utxo")) as? [JSON] ?? []
        let fees = try? await Net.shared.object(endpointURL(c, "/v1/fees/recommended"))
        let rate = max(1, fees?.i("halfHourFee") ?? fees?.i("fastestFee") ?? 2)
        let script = BitcoinScript.lockScriptForAddress(address: r.from, coin: c.coin).data

        let utxos: [BitcoinUnspentTransaction] = raw.compactMap { u in
            guard let txid = u.s("txid"), let h = Data(hexString: txid), let vout = u.i("vout"), let v = u.i("value") else { return nil }
            return BitcoinUnspentTransaction.with {
                $0.outPoint = BitcoinOutPoint.with {
                    $0.hash = Data(h.reversed())
                    $0.index = UInt32(vout)
                    $0.sequence = UInt32.max - 2 // opt-in RBF so a stuck tx can be bumped
                }
                $0.amount = v
                $0.script = script
            }
        }
        guard !utxos.isEmpty else { throw fail("No spendable \(c.symbol) found on this address.") }

        var input = BitcoinSigningInput.with {
            $0.hashType = BitcoinScript.hashTypeForCoin(coinType: c.coin)
            $0.amount = r.amount.int64 ?? 0
            $0.byteFee = rate
            $0.toAddress = r.to
            $0.changeAddress = r.from
            $0.coinType = c.coin.rawValue
            $0.useMaxAmount = r.useMax
            $0.privateKey = [key.data]
            $0.utxo = utxos
        }
        let plan: BitcoinTransactionPlan = AnySigner.plan(input: input, coin: c.coin)
        guard plan.error == .ok else {
            throw fail("Can't build transaction: insufficient funds for amount + fee (\(rate) sat/vB).")
        }
        input.plan = plan
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: BigUInt(plan.amount), fee: BigUInt(plan.fee),
                     feeIsMax: false, memo: "", notes: ["Fee rate: \(rate) sat/vB · RBF enabled"], ctx: .utxo(input))
    }

    static func send(_ q: Quote, _ input: BitcoinSigningInput, _ key: PrivateKey) async throws -> String {
        var input = input
        input.privateKey = [key.data]
        let out: BitcoinSigningOutput = AnySigner.sign(input: input, coin: q.asset.chain.coin)
        guard out.error == .ok, !out.encoded.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        let d = try await Net.shared.request(endpointURL(q.asset.chain, "/tx"), method: "POST",
                                             body: Data(out.encoded.hexString.utf8), contentType: "text/plain")
        let txid = String(decoding: d, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return txid.isEmpty ? out.transactionID : txid
    }
}

// MARK: - Ethereum (JSON-RPC)

private enum EVM {
    static func url() throws -> URL { try endpointURL(.ethereum, "") }

    static func pad(_ addr: String) -> String {
        let h = addr.lowercased().replacingOccurrences(of: "0x", with: "")
        return String(repeating: "0", count: max(0, 64 - h.count)) + h
    }

    static func hexNum(_ any: Any) throws -> BigUInt {
        guard let s = any as? String, let v = BigUInt(hex: s) else { throw fail("Bad numeric response from node.") }
        return v
    }

    static func balance(_ asset: Asset, _ a: String) async throws -> BigUInt {
        if let c = asset.contract {
            let r = try await Net.shared.rpc(url(), "eth_call", [["to": c, "data": "0x70a08231" + pad(a)], "latest"])
            return try hexNum(r)
        }
        return try hexNum(try await Net.shared.rpc(url(), "eth_getBalance", [a, "latest"]))
    }

    static func transferData(_ to: String, _ amount: BigUInt) -> String {
        "0xa9059cbb" + pad(to) + amount.abiWord
    }

    static func quote(_ r: SendRequest) async throws -> Quote {
        let u = try url()
        async let nonceR = Net.shared.rpc(u, "eth_getTransactionCount", [r.from, "pending"])
        async let blockR = Net.shared.rpc(u, "eth_getBlockByNumber", ["latest", false])
        let nonce = try hexNum(try await nonceR)
        guard let block = try await blockR as? JSON, let baseHex = block.s("baseFeePerGas"),
              let base = BigUInt(hex: baseHex) else { throw fail("Could not read Ethereum fee data.") }
        let tipR = try? await Net.shared.rpc(u, "eth_maxPriorityFeePerGas", [])
        var tip = (tipR as? String).flatMap { BigUInt(hex: $0) } ?? BigUInt(1_000_000_000)
        let minTip = BigUInt(100_000_000) // 0.1 gwei
        if tip < minTip { tip = minTip }
        let maxFee = base * BigUInt(2) + tip

        var gas = BigUInt(21_000)
        var amount = r.amount
        if let contract = r.asset.contract {
            let est = try? await Net.shared.rpc(u, "eth_estimateGas",
                                                [["from": r.from, "to": contract, "data": transferData(r.to, r.amount)]])
            let g = est.flatMap { $0 as? String }.flatMap { BigUInt(hex: $0) } ?? BigUInt(90_000)
            gas = g + g / 4
            if r.useMax { amount = r.assetBalance }
        }
        let fee = gas * maxFee
        if r.asset.isNative, r.useMax { amount = r.nativeBalance - fee }
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: fee, feeIsMax: true, memo: "",
                     notes: ["Max fee shown. You're usually charged less (EIP-1559)."],
                     ctx: .evm(nonce: nonce, maxFee: maxFee, tip: tip, gas: gas))
    }

    static func send(_ q: Quote, _ nonce: BigUInt, _ maxFee: BigUInt, _ tip: BigUInt, _ gas: BigUInt,
                     _ key: PrivateKey) async throws -> String {
        let input = EthereumSigningInput.with {
            $0.chainID = BigUInt(1).bigEndianData
            $0.nonce = nonce.bigEndianData
            $0.txMode = .enveloped
            $0.gasLimit = gas.bigEndianData
            $0.maxFeePerGas = maxFee.bigEndianData
            $0.maxInclusionFeePerGas = tip.bigEndianData
            $0.privateKey = key.data
            if let contract = q.asset.contract {
                $0.toAddress = contract
                $0.transaction = EthereumTransaction.with {
                    $0.erc20Transfer = EthereumTransaction.ERC20Transfer.with {
                        $0.to = q.to
                        $0.amount = q.amount.bigEndianData
                    }
                }
            } else {
                $0.toAddress = q.to
                $0.transaction = EthereumTransaction.with {
                    $0.transfer = EthereumTransaction.Transfer.with { $0.amount = q.amount.bigEndianData }
                }
            }
        }
        let out: EthereumSigningOutput = AnySigner.sign(input: input, coin: .ethereum)
        guard out.errorMessage.isEmpty, !out.encoded.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        let r = try await Net.shared.rpc(url(), "eth_sendRawTransaction", ["0x" + out.encoded.hexString])
        return (r as? String) ?? ""
    }
}

// MARK: - Solana (JSON-RPC)

private enum SOL {
    static let baseFee = BigUInt(5_000)
    static let ataRent = BigUInt(2_039_280)

    static func url() throws -> URL { try endpointURL(.solana, "") }

    static func tokenAccounts(_ owner: String, _ mint: String) async throws -> [(String, BigUInt)] {
        let r = try await Net.shared.rpc(url(), "getTokenAccountsByOwner",
                                         [owner, ["mint": mint], ["encoding": "jsonParsed", "commitment": "confirmed"]])
        let list = (r as? JSON)?.a("value") as? [JSON] ?? []
        return list.compactMap { acc in
            guard let pk = acc.s("pubkey"),
                  let amt = acc.d("account")?.d("data")?.d("parsed")?.d("info")?.d("tokenAmount")?.s("amount"),
                  let v = BigUInt(decimal: amt) else { return nil }
            return (pk, v)
        }
    }

    static func balance(_ asset: Asset, _ a: String) async throws -> BigUInt {
        if let mint = asset.contract {
            return try await tokenAccounts(a, mint).reduce(BigUInt()) { $0 + $1.1 }
        }
        let r = try await Net.shared.rpc(url(), "getBalance", [a, ["commitment": "confirmed"]])
        return BigUInt((r as? JSON)?.i("value") ?? 0)
    }

    static func quote(_ r: SendRequest) async throws -> Quote {
        let bh = try await Net.shared.rpc(url(), "getLatestBlockhash", [["commitment": "finalized"]])
        guard let blockhash = (bh as? JSON)?.d("value")?.s("blockhash") else { throw fail("Could not reach Solana.") }

        if let mint = r.asset.contract {
            let accounts = try await tokenAccounts(r.from, mint)
            guard let sender = accounts.max(by: { $0.1 < $1.1 }) else { throw fail("No \(r.asset.symbol) token account.") }
            let amount = r.useMax ? sender.1 : r.amount
            if amount > sender.1 { throw fail("Insufficient \(r.asset.symbol) in a single token account.") }
            guard let recipientATA = SolanaAddress(string: r.to)?.defaultTokenAddress(tokenMintAddress: mint) else {
                throw fail("Invalid Solana recipient.")
            }
            let info = try await Net.shared.rpc(url(), "getAccountInfo", [recipientATA, ["encoding": "base64"]])
            var exists = false
            if let v = (info as? JSON)?["value"], !(v is NSNull) { exists = true }
            let fee = exists ? baseFee : baseFee + ataRent
            var notes: [String] = []
            if !exists { notes.append("Recipient has no \(r.asset.symbol) account yet: includes ~0.00204 SOL to create it.") }
            return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: fee, feeIsMax: false, memo: "",
                         notes: notes, ctx: .sol(blockhash: blockhash, senderATA: sender.0, recipientATA: recipientATA, createATA: !exists))
        }
        let amount = r.useMax ? r.nativeBalance - baseFee : r.amount
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: baseFee, feeIsMax: false, memo: "",
                     notes: ["New Solana accounts need at least ~0.00089 SOL to exist."],
                     ctx: .sol(blockhash: blockhash, senderATA: nil, recipientATA: nil, createATA: false))
    }

    static func send(_ q: Quote, _ blockhash: String, _ senderATA: String?, _ recipientATA: String?,
                     _ create: Bool, _ key: PrivateKey) async throws -> String {
        guard let amount = q.amount.uint64 else { throw fail("Amount too large.") }
        let input = SolanaSigningInput.with {
            $0.privateKey = key.data
            $0.recentBlockhash = blockhash
            if let mint = q.asset.contract, let s = senderATA, let rcpt = recipientATA {
                if create {
                    $0.createAndTransferTokenTransaction = SolanaCreateAndTransferToken.with {
                        $0.recipientMainAddress = q.to
                        $0.tokenMintAddress = mint
                        $0.recipientTokenAddress = rcpt
                        $0.senderTokenAddress = s
                        $0.amount = amount
                        $0.decimals = UInt32(q.asset.decimals)
                    }
                } else {
                    $0.tokenTransferTransaction = SolanaTokenTransfer.with {
                        $0.tokenMintAddress = mint
                        $0.senderTokenAddress = s
                        $0.recipientTokenAddress = rcpt
                        $0.amount = amount
                        $0.decimals = UInt32(q.asset.decimals)
                    }
                }
            } else {
                $0.transferTransaction = SolanaTransfer.with {
                    $0.recipient = q.to
                    $0.value = amount
                }
            }
        }
        let out: SolanaSigningOutput = AnySigner.sign(input: input, coin: .solana)
        guard out.errorMessage.isEmpty, !out.encoded.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        let r = try await Net.shared.rpc(url(), "sendTransaction",
                                         [out.encoded, ["encoding": "base58", "preflightCommitment": "confirmed"]])
        return (r as? String) ?? ""
    }
}

// MARK: - XRP Ledger (rippled JSON-RPC)

private enum XRPL {
    static let reserve = BigUInt(1_000_000) // 1 XRP base reserve

    static func call(_ method: String, _ params: JSON) async throws -> JSON {
        let res = try await Net.shared.object(endpointURL(.xrp, ""), method: "POST", body: ["method": method, "params": [params]])
        guard let r = res.d("result") else { throw fail("Bad XRPL response.") }
        if r.s("status") == "error" { throw fail(r.s("error") ?? "XRPL error") }
        return r
    }

    static func account(_ a: String) async throws -> JSON? {
        do {
            return try await call("account_info", ["account": a, "ledger_index": "current"]).d("account_data")
        } catch EngineError.msg(let m) where m == "actNotFound" {
            return nil
        }
    }

    static func balance(_ a: String) async throws -> BigUInt {
        BigUInt(decimal: try await account(a)?.s("Balance") ?? "0") ?? BigUInt()
    }

    static func quote(_ r: SendRequest) async throws -> Quote {
        guard let acc = try await account(r.from), let seq = acc.i("Sequence") else {
            throw fail("This XRP account is not activated yet (needs 1 XRP).")
        }
        let feeR = try await call("fee", [:])
        let open = Int64(feeR.d("drops")?.s("open_ledger_fee") ?? "12") ?? 12
        let fee = min(max(open, 12), 5_000)
        let ledger = UInt32(feeR.i("ledger_current_index") ?? 0)

        var tag: UInt32?
        let memo = r.memo.trimmingCharacters(in: .whitespaces)
        if !memo.isEmpty {
            guard let t = UInt32(memo) else { throw fail("Destination tag must be a number.") }
            tag = t
        }
        let feeB = BigUInt(fee)
        let spendable = r.nativeBalance - reserve - feeB
        let amount = r.useMax ? spendable : r.amount
        if amount > spendable { throw fail("XRP keeps 1 XRP reserved. Max sendable: \(Amount.format(spendable, decimals: 6)) XRP.") }

        var notes = ["1 XRP stays reserved on your account."]
        if try await account(r.to) == nil {
            if amount < reserve { throw fail("Recipient is not activated: send at least 1 XRP.") }
            notes.append("Recipient account is new and will be activated.")
        }
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: feeB, feeIsMax: false, memo: memo,
                     notes: notes, ctx: .xrp(sequence: UInt32(seq), fee: fee, ledger: ledger, tag: tag))
    }

    static func send(_ q: Quote, _ seq: UInt32, _ fee: Int64, _ ledger: UInt32, _ tag: UInt32?,
                     _ key: PrivateKey) async throws -> String {
        guard let amount = q.amount.int64 else { throw fail("Amount too large.") }
        let input = RippleSigningInput.with {
            $0.fee = fee
            $0.sequence = seq
            $0.lastLedgerSequence = ledger + 20
            $0.account = q.from
            $0.privateKey = key.data
            $0.opPayment = RippleOperationPayment.with {
                $0.destination = q.to
                $0.amount = amount
                if let tag { $0.destinationTag = tag }
            }
        }
        let out: RippleSigningOutput = AnySigner.sign(input: input, coin: .xrp)
        guard out.errorMessage.isEmpty, !out.encoded.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        let r = try await call("submit", ["tx_blob": out.encoded.hexString.uppercased()])
        let result = r.s("engine_result") ?? ""
        guard result.hasPrefix("tes") || result.hasPrefix("ter") else {
            throw fail("Rejected by ledger: \(r.s("engine_result_message") ?? result)")
        }
        return r.d("tx_json")?.s("hash") ?? ""
    }
}

// MARK: - TON (tonapi.io v2) incl. jettons (GRAM, USDT…) and Telegram collectibles

private enum TON {
    static let nativeFee = BigUInt(10_000_000)   // ~0.01 TON upper estimate
    static let jettonGas = BigUInt(50_000_000)   // 0.05 TON attached, excess refunded

    static func balance(_ a: String) async throws -> BigUInt {
        do {
            let j = try await Net.shared.object(endpointURL(.ton, "/v2/accounts/\(a)"))
            return BigUInt(j.i("balance") ?? 0)
        } catch NetError.http(404, _) {
            return BigUInt()
        }
    }

    static func seqno(_ a: String) async -> UInt32 {
        guard let j = try? await Net.shared.object(endpointURL(.ton, "/v2/wallet/\(a)/seqno")) else { return 0 }
        return UInt32(j.i("seqno") ?? 0)
    }

    static func jettons(_ a: String) async throws -> [(Asset, BigUInt)] {
        let j: JSON
        do { j = try await Net.shared.object(endpointURL(.ton, "/v2/accounts/\(a)/jettons")) }
        catch NetError.http(404, _) { return [] }
        let list = j.a("balances") as? [JSON] ?? []
        return list.compactMap { b in
            guard let jet = b.d("jetton"), let master = jet.s("address"),
                  let wallet = b.d("wallet_address")?.s("address"),
                  let bal = BigUInt(decimal: b.s("balance") ?? "0") else { return nil }
            let verified = jet.s("verification") == "whitelist"
            let asset = Asset(id: "ton.\(master)", chain: .ton, symbol: jet.s("symbol") ?? "JETTON",
                              name: jet.s("name") ?? "Jetton", decimals: Int(jet.i("decimals") ?? 9),
                              contract: master, jettonWallet: wallet, verified: verified)
            return (asset, bal)
        }
    }

    static func nfts(_ a: String) async throws -> [NFTItem] {
        let j: JSON
        do { j = try await Net.shared.object(endpointURL(.ton, "/v2/accounts/\(a)/nfts?limit=200&offset=0&indirect_ownership=false")) }
        catch NetError.http(404, _) { return [] }
        let items = j.a("nft_items") as? [JSON] ?? []
        return items.compactMap { n in
            guard let addr = n.s("address") else { return nil }
            if n.s("trust") == "blacklist" { return nil }
            let collection = n.d("collection")?.s("name") ?? "Unknown collection"
            let meta = n.d("metadata") ?? [:]
            let name = meta.s("name") ?? n.s("dns") ?? "NFT"
            let previews = n.a("previews") as? [JSON] ?? []
            let preview = previews.first(where: { $0.s("resolution") == "500x500" })?.s("url") ?? previews.last?.s("url")
            let image = meta.s("image") ?? ""
            let isTG = collection.localizedCaseInsensitiveContains("telegram")
                || image.contains("fragment.com") || image.contains("nft.fragment")
                || (n.s("dns")?.hasSuffix(".t.me") ?? false)
            return NFTItem(id: addr, name: name, collection: collection, image: preview.flatMap(URL.init(string:)), isTelegram: isTG)
        }
    }

    static func quote(_ r: SendRequest) async throws -> Quote {
        let seq = await seqno(r.from)
        let memo = r.memo.trimmingCharacters(in: .whitespacesAndNewlines)
        if r.asset.isNative {
            let amount = r.useMax ? r.nativeBalance - nativeFee - BigUInt(5_000_000) : r.amount
            return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: nativeFee, feeIsMax: true, memo: memo,
                         notes: seq == 0 ? ["First send also deploys your wallet contract."] : [], ctx: .ton(seqno: seq))
        }
        guard r.asset.jettonWallet != nil else { throw fail("Jetton wallet not found.") }
        let amount = r.useMax ? r.assetBalance : r.amount
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: jettonGas, feeIsMax: true, memo: memo,
                     notes: ["0.05 TON is attached for jetton gas; the unused part is refunded."], ctx: .ton(seqno: seq))
    }

    static func send(_ q: Quote, _ seq: UInt32, _ key: PrivateKey) async throws -> String {
        guard let amount = q.amount.uint64 else { throw fail("Amount too large.") }
        let to = q.to
        let bounceable = to.hasPrefix("EQ") || to.hasPrefix("Ef") // respect the address' own bounce flag
        let transfer: TheOpenNetworkTransfer
        if let jw = q.asset.jettonWallet {
            transfer = TheOpenNetworkTransfer.with {
                $0.dest = jw
                $0.amount = jettonGas.uint64 ?? 50_000_000
                $0.mode = 3 // pay fees separately | ignore errors
                $0.bounceable = true
                if !q.memo.isEmpty { $0.comment = q.memo }
                $0.jettonTransfer = TheOpenNetworkJettonTransfer.with {
                    $0.queryID = UInt64(Date().timeIntervalSince1970)
                    $0.jettonAmount = amount
                    $0.toOwner = to
                    $0.responseAddress = q.from
                    $0.forwardAmount = 1
                }
            }
        } else {
            transfer = TheOpenNetworkTransfer.with {
                $0.dest = to
                $0.amount = amount
                $0.mode = 3
                $0.bounceable = bounceable
                if !q.memo.isEmpty { $0.comment = q.memo }
            }
        }
        let input = TheOpenNetworkSigningInput.with {
            $0.privateKey = key.data
            $0.sequenceNumber = seq
            $0.expireAt = UInt32(Date().timeIntervalSince1970) + 600
            $0.walletVersion = .walletV4R2
            $0.messages = [transfer]
        }
        let out: TheOpenNetworkSigningOutput = AnySigner.sign(input: input, coin: .ton)
        guard out.errorMessage.isEmpty, !out.encoded.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        _ = try await Net.shared.request(endpointURL(.ton, "/v2/blockchain/message"), method: "POST",
                                         body: try JSONSerialization.data(withJSONObject: ["boc": out.encoded]))
        return out.hash.hexString
    }
}

// MARK: - TRON (TronGrid HTTP API)

private enum TRON {
    static let trc20FeeLimit: Int64 = 40_000_000 // 40 TRX max energy burn
    static let nativeFeeEstimate = BigUInt(1_100_000)

    static func post(_ path: String, _ body: JSON) async throws -> JSON {
        try await Net.shared.object(endpointURL(.tron, path), method: "POST", body: body)
    }

    static func abiAddress(_ base58: String) -> String? {
        guard let d = Base58.decode(string: base58), d.count == 21 else { return nil }
        let h = d.dropFirst().map { String(format: "%02x", $0) }.joined()
        return String(repeating: "0", count: 24) + h
    }

    static func balance(_ asset: Asset, _ a: String) async throws -> BigUInt {
        if let c = asset.contract {
            guard let p = abiAddress(a) else { return BigUInt() }
            let r = try await post("/wallet/triggerconstantcontract",
                                   ["owner_address": a, "contract_address": c, "function_selector": "balanceOf(address)",
                                    "parameter": p, "visible": true])
            let hex = (r.a("constant_result") as? [String])?.first ?? "0"
            return BigUInt(hex: hex) ?? BigUInt()
        }
        let r = try await post("/wallet/getaccount", ["address": a, "visible": true])
        return BigUInt(r.i("balance") ?? 0)
    }

    static func quote(_ r: SendRequest) async throws -> Quote {
        let b = try await post("/wallet/getnowblock", [:])
        guard let raw = b.d("block_header")?.d("raw_data"),
              let number = raw.i("number"), let ts = raw.i("timestamp"),
              let trie = Data(hexString: raw.s("txTrieRoot") ?? ""),
              let parent = Data(hexString: raw.s("parentHash") ?? ""),
              let witness = Data(hexString: raw.s("witness_address") ?? "") else {
            throw fail("Could not reach TRON.")
        }
        let header = TronBlockHeader.with {
            $0.number = number
            $0.timestamp = ts
            $0.txTrieRoot = trie
            $0.parentHash = parent
            $0.witnessAddress = witness
            $0.version = Int32(raw.i("version") ?? 0)
        }
        if r.asset.isNative {
            let amount = r.useMax ? r.nativeBalance - nativeFeeEstimate : r.amount
            return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: nativeFeeEstimate, feeIsMax: true,
                         memo: "", notes: ["Usually free using daily bandwidth. +1 TRX if the recipient is a new account."],
                         ctx: .tron(header))
        }
        let amount = r.useMax ? r.assetBalance : r.amount
        return Quote(asset: r.asset, from: r.from, to: r.to, amount: amount, fee: BigUInt(trc20FeeLimit), feeIsMax: true,
                     memo: "", notes: ["USDT on TRON burns TRX for energy (typically 13–28 TRX). Keep TRX on this account."],
                     ctx: .tron(header))
    }

    static func send(_ q: Quote, _ header: TronBlockHeader, _ key: PrivateKey) async throws -> String {
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        let input = TronSigningInput.with {
            $0.privateKey = key.data
            $0.transaction = TronTransaction.with {
                $0.timestamp = now
                $0.expiration = now + 60 * 60 * 1000
                $0.blockHeader = header
                if let contract = q.asset.contract {
                    $0.feeLimit = trc20FeeLimit
                    $0.transferTrc20Contract = TronTransferTRC20Contract.with {
                        $0.contractAddress = contract
                        $0.ownerAddress = q.from
                        $0.toAddress = q.to
                        $0.amount = q.amount.bigEndianData
                    }
                } else {
                    $0.transfer = TronTransferContract.with {
                        $0.ownerAddress = q.from
                        $0.toAddress = q.to
                        $0.amount = q.amount.int64 ?? 0
                    }
                }
            }
        }
        let out: TronSigningOutput = AnySigner.sign(input: input, coin: .tron)
        guard out.errorMessage.isEmpty, !out.json.isEmpty else { throw fail("Signing failed: \(out.errorMessage)") }
        guard let body = try JSONSerialization.jsonObject(with: Data(out.json.utf8)) as? JSON else { throw fail("Bad signed tx.") }
        let r = try await post("/wallet/broadcasttransaction", body)
        if (r["result"] as? Bool) == true { return r.s("txid") ?? out.id.hexString }
        var msg = r.s("message") ?? r.s("code") ?? "Broadcast failed"
        if let d = Data(hexString: msg), let s = String(data: d, encoding: .utf8) { msg = s }
        throw fail("TRON rejected: \(msg)")
    }
}
