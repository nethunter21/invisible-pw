import SwiftUI
import WalletCore

@MainActor
final class AppState: ObservableObject {
    enum Phase { case onboarding, locked, unlocked }

    @Published var phase: Phase
    @Published private(set) var addresses: [Chain: String] = [:]
    @Published private(set) var balances: [String: BigUInt] = [:]
    @Published private(set) var failures: [String: String] = [:]
    @Published private(set) var tonJettons: [Asset] = []
    @Published private(set) var nfts: [NFTItem] = []
    @Published private(set) var refreshing = false
    @Published private(set) var lastRefresh: Date?

    private var wallet: HDWallet?
    private var backgroundedAt: Date?

    init() {
        phase = Vault.hasWallet ? .locked : .onboarding
    }

    // MARK: Session

    func open(mnemonic: String) {
        guard let w = HDWallet(mnemonic: mnemonic, passphrase: "") else { return }
        wallet = w
        var a: [Chain: String] = [:]
        for c in Chain.allCases { a[c] = w.getAddressForCoin(coin: c.coin) }
        addresses = a
        phase = .unlocked
        Task { await refresh() }
    }

    func lock() {
        wallet = nil
        addresses = [:]
        balances = [:]
        failures = [:]
        tonJettons = []
        nfts = []
        phase = Vault.hasWallet ? .locked : .onboarding
    }

    func erase() {
        lock()
        Vault.wipe()
        phase = .onboarding
    }

    func scene(_ p: ScenePhase) {
        switch p {
        case .background:
            backgroundedAt = Date()
            if Prefs.autoLock == 0 { lock() }
        case .active:
            if let t = backgroundedAt, phase == .unlocked, Date().timeIntervalSince(t) >= Double(Prefs.autoLock) { lock() }
            backgroundedAt = nil
        default: break
        }
    }

    func privateKey(for chain: Chain) -> PrivateKey? { wallet?.getKeyForCoin(coin: chain.coin) }

    // MARK: Data

    var assets: [Asset] {
        let showUnverified = UserDefaults.standard.bool(forKey: Prefs.Key.showUnverified)
        return Asset.builtIn + tonJettons.filter { $0.verified || showUnverified }
    }

    func balance(_ a: Asset) -> BigUInt? { balances[a.id] }
    func nativeBalance(_ c: Chain) -> BigUInt { balances[c.rawValue] ?? BigUInt() }

    func refresh() async {
        guard phase == .unlocked, !refreshing else { return }
        refreshing = true
        defer { refreshing = false; lastRefresh = Date() }
        let addrs = addresses

        await withTaskGroup(of: (String, Result<BigUInt, Error>).self) { g in
            for asset in Asset.builtIn {
                guard let a = addrs[asset.chain] else { continue }
                g.addTask {
                    do { return (asset.id, .success(try await Engine.balance(of: asset, address: a))) }
                    catch { return (asset.id, .failure(error)) }
                }
            }
            for await (id, res) in g {
                switch res {
                case .success(let v): balances[id] = v; failures[id] = nil
                case .failure(let e): failures[id] = e.localizedDescription
                }
            }
        }

        // TON indexer is rate-limited without an API key: query sequentially.
        if let ton = addrs[.ton] {
            if let jets = try? await Engine.tonJettons(ton) {
                tonJettons = jets.map { $0.0 }
                for (asset, bal) in jets { balances[asset.id] = bal }
            }
            if let items = try? await Engine.tonNFTs(ton) { nfts = items }
        }
    }

    func quote(_ r: SendRequest) async throws -> Quote {
        guard let key = privateKey(for: r.asset.chain) else { throw EngineError.msg("Vault is locked.") }
        return try await Engine.quote(r, key: key)
    }

    func send(_ q: Quote) async throws -> String {
        guard let key = privateKey(for: q.asset.chain) else { throw EngineError.msg("Vault is locked.") }
        let id = try await Engine.send(q, key: key)
        Task { try? await Task.sleep(nanoseconds: 4_000_000_000); await refresh() }
        return id
    }
}
