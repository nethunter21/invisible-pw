import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var app: AppState
    @AppStorage(Prefs.Key.hideBalances) private var hide = false
    @AppStorage(Prefs.Key.offline) private var offline = false
    @State private var tab = 0
    @State private var settings = false

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                header
                Picker("", selection: $tab) {
                    Text("Assets").tag(0)
                    Text("Collectibles").tag(1)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 20).padding(.bottom, 10)

                if tab == 0 { assets } else { CollectiblesView() }
            }
            .screen()
            .navigationBarHidden(true)
            .sheet(isPresented: $settings) { SettingsView().environmentObject(app) }
        }
        .navigationViewStyle(.stack)
    }

    private var header: some View {
        HStack(spacing: 6) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Vault").font(.system(size: 30, weight: .bold)).foregroundColor(Theme.text)
                HStack(spacing: 6) {
                    Circle().fill(offline ? Theme.warn : (app.refreshing ? Theme.dim : Theme.accent)).frame(width: 7, height: 7)
                    Text(offline ? "Offline mode: no network" : (app.refreshing ? "Syncing…" : "Connected · keys on device"))
                        .font(.system(size: 12)).foregroundColor(Theme.dim)
                }
            }
            Spacer()
            iconButton(hide ? "eye.slash" : "eye") { hide.toggle() }
            iconButton("gearshape") { settings = true }
            iconButton("lock") { app.lock() }
        }
        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 14)
    }

    private func iconButton(_ name: String, _ action: @escaping () -> Void) -> some View {
        Button(action: { Haptic.tap(); action() }) {
            Image(systemName: name).font(.system(size: 17, weight: .medium)).foregroundColor(Theme.text)
                .frame(width: 40, height: 40)
                .background(Circle().fill(Theme.surface2))
        }
    }

    private var assets: some View {
        ScrollView {
            LazyVStack(spacing: 8) {
                ForEach(app.assets) { a in
                    NavigationLink(destination: AssetDetailView(asset: a)) {
                        AssetRow(asset: a, hide: hide)
                    }
                    .buttonStyle(.plain)
                }
                Text("Balances are read from public nodes you can change in Settings → Endpoints.")
                    .font(.system(size: 11)).foregroundColor(Theme.faint).multilineTextAlignment(.center)
                    .padding(.top, 14).padding(.horizontal, 30)
            }
            .padding(.horizontal, 16).padding(.bottom, 30)
        }
        .refreshable { await app.refresh() }
    }
}

struct AssetRow: View {
    @EnvironmentObject private var app: AppState
    let asset: Asset
    let hide: Bool

    var body: some View {
        HStack(spacing: 14) {
            AssetIcon(asset: asset)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(asset.symbol).font(.system(size: 16, weight: .semibold)).foregroundColor(Theme.text)
                    if let s = asset.standard { Pill(text: s) }
                    if !asset.verified { Pill(text: "Unverified", color: Theme.warn) }
                }
                Text(asset.isNative ? asset.name : "\(asset.name) · \(asset.chain.name)")
                    .font(.system(size: 13)).foregroundColor(Theme.dim).lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                if hide {
                    Text("••••••").font(.mono(16, .medium)).foregroundColor(Theme.dim)
                } else if let b = app.balance(asset) {
                    Text(Amount.format(b, decimals: asset.decimals, maxFraction: 6))
                        .font(.mono(16, .medium)).foregroundColor(b.isZero ? Theme.dim : Theme.text)
                        .lineLimit(1).minimumScaleFactor(0.6)
                } else if app.failures[asset.id] != nil {
                    Image(systemName: "exclamationmark.triangle").foregroundColor(Theme.warn)
                } else {
                    ProgressView().scaleEffect(0.7).tint(Theme.dim)
                }
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 16).fill(Theme.surface))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.stroke))
        .contentShape(Rectangle())
    }
}

struct CollectiblesView: View {
    @EnvironmentObject private var app: AppState
    @AppStorage(Prefs.Key.loadImages) private var loadImages = true

    var body: some View {
        let tg = app.nfts.filter(\.isTelegram)
        let other = app.nfts.filter { !$0.isTelegram }
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if app.nfts.isEmpty {
                    VStack(spacing: 10) {
                        Image(systemName: "paperplane").font(.system(size: 34)).foregroundColor(Theme.dim)
                        Text("No collectibles yet").font(.system(size: 17, weight: .semibold)).foregroundColor(Theme.text)
                        Text("Telegram usernames, anonymous numbers and gifts sent to your TON address appear here.")
                            .font(.system(size: 14)).foregroundColor(Theme.dim).multilineTextAlignment(.center)
                        if let a = app.addresses[.ton] {
                            Text(shortAddress(a)).font(.mono(13)).foregroundColor(Theme.dim)
                        }
                    }
                    .frame(maxWidth: .infinity).padding(.top, 60).padding(.horizontal, 30)
                }
                if !tg.isEmpty { section("Telegram Collectibles", tg) }
                if !other.isEmpty { section("Other TON NFTs", other) }
            }
            .padding(.horizontal, 16).padding(.bottom, 30)
        }
        .refreshable { await app.refresh() }
    }

    private func section(_ title: String, _ items: [NFTItem]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased()).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim).tracking(1)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(items) { n in
                    VStack(alignment: .leading, spacing: 8) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 12).fill(Theme.surface2)
                            if loadImages, let url = n.image {
                                AsyncImage(url: url) { img in img.resizable().scaledToFill() } placeholder: { ProgressView().tint(Theme.dim) }
                            } else {
                                Image(systemName: n.isTelegram ? "paperplane.fill" : "photo").font(.system(size: 28)).foregroundColor(Theme.faint)
                            }
                        }
                        .aspectRatio(1, contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        Text(n.name).font(.system(size: 14, weight: .semibold)).foregroundColor(Theme.text).lineLimit(1)
                        Text(n.collection).font(.system(size: 12)).foregroundColor(Theme.dim).lineLimit(1)
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 16).fill(Theme.surface))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.stroke))
                    .contextMenu { Button("Copy NFT address") { Clip.copy(n.id) } }
                }
            }
        }
    }
}
