import SwiftUI
import WalletCore

enum Chain: String, CaseIterable, Identifiable {
    case bitcoin, litecoin, ethereum, solana, xrp, ton, tron

    var id: String { rawValue }

    var coin: CoinType {
        switch self {
        case .bitcoin: return .bitcoin
        case .litecoin: return .litecoin
        case .ethereum: return .ethereum
        case .solana: return .solana
        case .xrp: return .xrp
        case .ton: return .ton
        case .tron: return .tron
        }
    }

    var name: String {
        switch self {
        case .bitcoin: return "Bitcoin"
        case .litecoin: return "Litecoin"
        case .ethereum: return "Ethereum"
        case .solana: return "Solana"
        case .xrp: return "XRP Ledger"
        case .ton: return "TON"
        case .tron: return "TRON"
        }
    }

    var symbol: String {
        switch self {
        case .bitcoin: return "BTC"
        case .litecoin: return "LTC"
        case .ethereum: return "ETH"
        case .solana: return "SOL"
        case .xrp: return "XRP"
        case .ton: return "TON"
        case .tron: return "TRX"
        }
    }

    var decimals: Int {
        switch self {
        case .bitcoin, .litecoin: return 8
        case .ethereum: return 18
        case .solana, .ton: return 9
        case .xrp, .tron: return 6
        }
    }

    var tint: Color {
        switch self {
        case .bitcoin: return Color(red: 0.97, green: 0.58, blue: 0.10)
        case .litecoin: return Color(red: 0.55, green: 0.62, blue: 0.75)
        case .ethereum: return Color(red: 0.46, green: 0.52, blue: 0.95)
        case .solana: return Color(red: 0.60, green: 0.35, blue: 1.00)
        case .xrp: return Color(white: 0.85)
        case .ton: return Color(red: 0.00, green: 0.60, blue: 1.00)
        case .tron: return Color(red: 0.92, green: 0.16, blue: 0.20)
        }
    }

    var defaultEndpoint: String {
        switch self {
        case .bitcoin: return "https://mempool.space/api"
        case .litecoin: return "https://litecoinspace.org/api"
        case .ethereum: return "https://ethereum-rpc.publicnode.com"
        case .solana: return "https://api.mainnet-beta.solana.com"
        case .xrp: return "https://xrplcluster.com"
        case .ton: return "https://tonapi.io"
        case .tron: return "https://api.trongrid.io"
        }
    }

    /// Optional memo / tag field required by some exchanges.
    var memoLabel: String? {
        switch self {
        case .xrp: return "Destination tag"
        case .ton: return "Comment / memo"
        default: return nil
        }
    }

    func explorerURL(tx: String) -> URL? {
        switch self {
        case .bitcoin: return URL(string: "https://mempool.space/tx/\(tx)")
        case .litecoin: return URL(string: "https://litecoinspace.org/tx/\(tx)")
        case .ethereum: return URL(string: "https://etherscan.io/tx/\(tx)")
        case .solana: return URL(string: "https://solscan.io/tx/\(tx)")
        case .xrp: return URL(string: "https://livenet.xrpl.org/transactions/\(tx)")
        case .ton: return URL(string: "https://tonviewer.com/transaction/\(tx)")
        case .tron: return URL(string: "https://tronscan.org/#/transaction/\(tx)")
        }
    }
}

struct Asset: Identifiable, Hashable {
    let id: String
    let chain: Chain
    let symbol: String
    let name: String
    let decimals: Int
    /// ERC-20 contract, SPL mint, TRC-20 contract or TON jetton master.
    let contract: String?
    /// TON only: the holder's jetton wallet address.
    var jettonWallet: String? = nil
    var verified: Bool = true

    var isNative: Bool { contract == nil }
    var standard: String? {
        guard !isNative else { return nil }
        switch chain {
        case .ethereum: return "ERC-20"
        case .solana: return "SPL"
        case .tron: return "TRC-20"
        case .ton: return "Jetton"
        default: return nil
        }
    }

    static func native(_ c: Chain) -> Asset {
        Asset(id: c.rawValue, chain: c, symbol: c.symbol, name: c.name, decimals: c.decimals, contract: nil)
    }

    static let builtIn: [Asset] = [
        .native(.bitcoin),
        .native(.ethereum),
        Asset(id: "eth.usdt", chain: .ethereum, symbol: "USDT", name: "Tether USD", decimals: 6,
              contract: "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
        Asset(id: "eth.usdc", chain: .ethereum, symbol: "USDC", name: "USD Coin", decimals: 6,
              contract: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
        .native(.solana),
        Asset(id: "sol.usdc", chain: .solana, symbol: "USDC", name: "USD Coin", decimals: 6,
              contract: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
        Asset(id: "sol.usdt", chain: .solana, symbol: "USDT", name: "Tether USD", decimals: 6,
              contract: "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"),
        .native(.ton),
        .native(.tron),
        Asset(id: "trx.usdt", chain: .tron, symbol: "USDT", name: "Tether USD", decimals: 6,
              contract: "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
        .native(.xrp),
        .native(.litecoin),
    ]
}

struct NFTItem: Identifiable, Hashable {
    let id: String
    let name: String
    let collection: String
    let image: URL?
    let isTelegram: Bool
}
