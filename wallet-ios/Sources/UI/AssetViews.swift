import SwiftUI

struct AssetDetailView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation
    @AppStorage(Prefs.Key.hideBalances) private var hide = false
    let asset: Asset
    @State private var sheet: Sheet?
    enum Sheet: Identifiable { case receive, send; var id: Int { hashValue } }

    var body: some View {
        VStack(spacing: 0) {
            FlowHeader(title: asset.isNative ? asset.name : "\(asset.symbol) · \(asset.chain.name)") {
                presentation.wrappedValue.dismiss()
            }
            ScrollView {
                VStack(spacing: 22) {
                    AssetIcon(asset: asset, size: 64).padding(.top, 20)
                    VStack(spacing: 6) {
                        Text(balanceText).font(.mono(34, .semibold)).foregroundColor(Theme.text)
                            .lineLimit(1).minimumScaleFactor(0.4)
                        Text(asset.symbol).font(.system(size: 15, weight: .medium)).foregroundColor(Theme.dim)
                    }
                    if let f = app.failures[asset.id] {
                        Text(f).font(.system(size: 12)).foregroundColor(Theme.warn).multilineTextAlignment(.center)
                    }
                    HStack(spacing: 12) {
                        Button { sheet = .receive } label: { Label("Receive", systemImage: "arrow.down") }
                            .buttonStyle(SecondaryButton())
                        Button { sheet = .send } label: { Label("Send", systemImage: "arrow.up") }
                            .buttonStyle(PrimaryButton())
                    }
                    if let addr = app.addresses[asset.chain] {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("YOUR \(asset.chain.name.uppercased()) ADDRESS").font(.system(size: 11, weight: .semibold))
                                .foregroundColor(Theme.dim).tracking(1)
                            ChunkedAddress(address: addr, size: 14)
                            Button { Clip.copy(addr) } label: {
                                Label("Copy (clears in 60s)", systemImage: "doc.on.doc").font(.system(size: 13, weight: .medium))
                            }
                            .foregroundColor(Theme.accent)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .card()
                    }
                    if let c = asset.contract {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("TOKEN CONTRACT").font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.dim).tracking(1)
                            Text(c).font(.mono(12)).foregroundColor(Theme.dim).textSelection(.enabled)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .card()
                    }
                }
                .padding(.horizontal, 20).padding(.bottom, 30)
            }
            .refreshable { await app.refresh() }
        }
        .screen()
        .navigationBarHidden(true)
        .sheet(item: $sheet) { s in
            switch s {
            case .receive: ReceiveView(asset: asset).environmentObject(app)
            case .send: SendView(asset: asset).environmentObject(app)
            }
        }
    }

    private var balanceText: String {
        if hide { return "••••••" }
        guard let b = app.balance(asset) else { return "—" }
        return Amount.format(b, decimals: asset.decimals, maxFraction: 8)
    }
}

// MARK: - Receive

struct ReceiveView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation
    let asset: Asset
    @State private var copied = false

    var body: some View {
        let addr = app.addresses[asset.chain] ?? ""
        VStack(spacing: 20) {
            Capsule().fill(Theme.faint).frame(width: 40, height: 5).padding(.top, 8)
            Text("Receive \(asset.symbol)").font(.system(size: 20, weight: .semibold)).foregroundColor(Theme.text)
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundColor(Theme.warn)
                Text("Only send \(asset.symbol) on the \(asset.chain.name) network to this address.")
                    .font(.system(size: 13)).foregroundColor(Theme.text)
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12).fill(Theme.warn.opacity(0.12)))

            QRCodeView(text: addr)
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 20).fill(Color.white))
                .frame(width: 250, height: 250)

            ChunkedAddress(address: addr, size: 16).padding(.horizontal, 10)

            Spacer()
            Button(copied ? "Copied, clears in 60s" : "Copy address") {
                Clip.copy(addr); copied = true
            }
            .buttonStyle(PrimaryButton())
            .padding(.horizontal, 20).padding(.bottom, 16)
        }
        .padding(.horizontal, 20)
        .screen()
    }
}

// MARK: - Send

struct SendView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation
    let asset: Asset

    @State private var to = ""
    @State private var amount = ""
    @State private var memo = ""
    @State private var useMax = false
    @State private var scanning = false
    @State private var loading = false
    @State private var error: String?
    @State private var quote: QuoteBox?

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    field("RECIPIENT") {
                        HStack(spacing: 8) {
                            TextField("\(asset.chain.name) address", text: $to)
                                .font(.mono(15))
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            Button { if let s = UIPasteboard.general.string { to = cleanAddress(s) } } label: {
                                Image(systemName: "doc.on.clipboard")
                            }
                            Button { scanning = true } label: { Image(systemName: "qrcode.viewfinder") }
                        }
                        .foregroundColor(Theme.text)
                    }

                    field("AMOUNT") {
                        HStack {
                            TextField("0.00", text: Binding(get: { useMax ? "Max" : amount }, set: { amount = $0; useMax = false }))
                                .font(.mono(22, .medium))
                                .keyboardType(.decimalPad)
                                .disabled(useMax)
                            Text(asset.symbol).font(.system(size: 15, weight: .semibold)).foregroundColor(Theme.dim)
                            Button(useMax ? "Clear" : "Max") { useMax.toggle(); if !useMax { amount = "" } }
                                .font(.system(size: 13, weight: .bold)).foregroundColor(.black)
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .background(Capsule().fill(Color.white))
                        }
                    }
                    HStack {
                        Text("Available").foregroundColor(Theme.dim)
                        Spacer()
                        Text("\(Amount.format(app.balance(asset) ?? BigUInt(), decimals: asset.decimals)) \(asset.symbol)")
                            .font(.mono(13)).foregroundColor(Theme.text)
                    }
                    .font(.system(size: 13))

                    if let label = asset.chain.memoLabel {
                        field(label.uppercased()) {
                            TextField("Optional, required by some exchanges", text: $memo)
                                .font(.mono(15))
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .keyboardType(asset.chain == .xrp ? .numberPad : .default)
                        }
                    }

                    if let error {
                        Text(error).font(.system(size: 13)).foregroundColor(Theme.danger)
                    }

                    Button {
                        Task { await review() }
                    } label: {
                        if loading { ProgressView().tint(.black) } else { Text("Review") }
                    }
                    .buttonStyle(PrimaryButton(enabled: canReview))
                    .disabled(!canReview || loading)
                    .padding(.top, 6)
                }
                .padding(20)
            }
            .screen()
            .navigationTitle("Send \(asset.symbol)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { presentation.wrappedValue.dismiss() }.foregroundColor(Theme.dim)
                }
            }
        }
        .sheet(isPresented: $scanning) {
            QRScannerView { s in to = cleanAddress(s); scanning = false }
        }
        .fullScreenCover(item: $quote) { box in
            ReviewView(quote: box.q) { presentation.wrappedValue.dismiss() }.environmentObject(app)
        }
    }

    private var canReview: Bool {
        !to.trimmingCharacters(in: .whitespaces).isEmpty && (useMax || !amount.isEmpty)
    }

    private func field<C: View>(_ label: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.dim).tracking(1)
            content()
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 12).fill(Theme.surface))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.stroke))
        }
    }

    private func cleanAddress(_ s: String) -> String {
        var t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = t.range(of: ":"), !t.hasPrefix("0:"), !t.hasPrefix("-1:") { t = String(t[r.upperBound...]) }
        if let q = t.firstIndex(of: "?") { t = String(t[..<q]) }
        if let at = t.firstIndex(of: "@") { t = String(t[..<at]) }
        if let r = t.range(of: "transfer/") { t = String(t[r.upperBound...]) }
        return t.replacingOccurrences(of: "//", with: "")
    }

    private func review() async {
        error = nil
        let target = to.trimmingCharacters(in: .whitespacesAndNewlines)
        var value = BigUInt()
        if !useMax {
            guard let v = Amount.parse(amount, decimals: asset.decimals) else {
                error = "Invalid amount (max \(asset.decimals) decimals)."
                return
            }
            value = v
        }
        guard let from = app.addresses[asset.chain] else { return }
        loading = true
        defer { loading = false }
        do {
            let req = SendRequest(asset: asset, from: from, to: target, amount: value, useMax: useMax, memo: memo,
                                  nativeBalance: app.nativeBalance(asset.chain), assetBalance: app.balance(asset) ?? BigUInt())
            quote = QuoteBox(q: try await app.quote(req))
        } catch {
            self.error = error.localizedDescription
            Haptic.error()
        }
    }
}

struct QuoteBox: Identifiable {
    let id = UUID()
    let q: Quote
}

// MARK: - Review & sign (hardware-wallet style)

struct ReviewView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation
    let quote: Quote
    let onFinished: () -> Void

    @State private var pinAuth = false
    @State private var sending = false
    @State private var error: String?
    @State private var txid: String?

    var body: some View {
        VStack(spacing: 0) {
            FlowHeader(title: txid == nil ? "Review transaction" : "Sent") { presentation.wrappedValue.dismiss() }
            if let txid { success(txid) } else { review }
        }
        .screen()
        .sheet(isPresented: $pinAuth) {
            PinAuthSheet(title: "Approve transaction") { _ in sign() }
        }
    }

    private var review: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 14) {
                    VStack(spacing: 6) {
                        Text("SENDING").font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.dim).tracking(1)
                        Text(Amount.format(quote.amount, decimals: quote.asset.decimals))
                            .font(.mono(32, .semibold)).foregroundColor(Theme.text).lineLimit(1).minimumScaleFactor(0.4)
                        Text("\(quote.asset.symbol) · \(quote.asset.chain.name)").font(.system(size: 14)).foregroundColor(Theme.dim)
                    }
                    .frame(maxWidth: .infinity).card()

                    VStack(alignment: .leading, spacing: 10) {
                        Text("TO: VERIFY EVERY CHARACTER").font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.warn).tracking(1)
                        ChunkedAddress(address: quote.to, size: 16)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading).card()

                    VStack(spacing: 12) {
                        row("Network fee\(quote.feeIsMax ? " (max)" : "")",
                            "\(Amount.format(quote.fee, decimals: quote.asset.chain.decimals)) \(quote.asset.chain.symbol)")
                        if !quote.memo.isEmpty { row(quote.asset.chain.memoLabel ?? "Memo", quote.memo) }
                        row("From", shortAddress(quote.from))
                        if let std = quote.asset.standard, let c = quote.asset.contract { row(std, shortAddress(c)) }
                    }
                    .card()

                    ForEach(quote.notes, id: \.self) { n in
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "info.circle").foregroundColor(Theme.dim)
                            Text(n).font(.system(size: 13)).foregroundColor(Theme.dim)
                            Spacer(minLength: 0)
                        }
                    }
                    if let error {
                        Text(error).font(.system(size: 13)).foregroundColor(Theme.danger).multilineTextAlignment(.center)
                    }
                }
                .padding(20)
            }
            VStack(spacing: 10) {
                if sending {
                    ProgressView("Signing on device & broadcasting…").tint(.white).foregroundColor(Theme.dim).frame(height: 58)
                } else {
                    HoldToConfirm(title: "Hold to sign") { authorize() }
                }
                Button("Reject") { presentation.wrappedValue.dismiss() }
                    .font(.system(size: 15, weight: .semibold)).foregroundColor(Theme.danger).frame(height: 40)
            }
            .padding(.horizontal, 20).padding(.bottom, 12)
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(.system(size: 14)).foregroundColor(Theme.dim)
            Spacer()
            Text(v).font(.mono(14, .medium)).foregroundColor(Theme.text).multilineTextAlignment(.trailing)
        }
    }

    private func authorize() {
        error = nil
        if Prefs.biometrics {
            Task {
                if await Vault.authorize(reason: "Approve sending \(quote.asset.symbol)") { sign() } else { pinAuth = true }
            }
        } else {
            pinAuth = true
        }
    }

    private func sign() {
        sending = true
        Task {
            do {
                txid = try await app.send(quote)
                Haptic.success()
            } catch {
                self.error = error.localizedDescription
                Haptic.error()
            }
            sending = false
        }
    }

    private func success(_ id: String) -> some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "checkmark.circle").font(.system(size: 70, weight: .light)).foregroundColor(Theme.accent)
            Text("Transaction broadcast").font(.system(size: 22, weight: .semibold)).foregroundColor(Theme.text)
            Text("\(Amount.format(quote.amount, decimals: quote.asset.decimals)) \(quote.asset.symbol) to \(shortAddress(quote.to))")
                .font(.system(size: 15)).foregroundColor(Theme.dim)
            if !id.isEmpty {
                Text(id).font(.mono(12)).foregroundColor(Theme.dim).multilineTextAlignment(.center).padding(.horizontal, 30)
                    .textSelection(.enabled)
                HStack(spacing: 18) {
                    Button("Copy tx ID") { Clip.copy(id) }
                    if let url = quote.asset.chain.explorerURL(tx: id) {
                        Link("View in explorer", destination: url)
                    }
                }
                .font(.system(size: 14, weight: .semibold)).foregroundColor(Theme.accent)
            }
            Spacer()
            Button("Done") { presentation.wrappedValue.dismiss(); onFinished() }
                .buttonStyle(PrimaryButton()).padding(20)
        }
    }
}
