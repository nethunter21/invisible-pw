import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation

    @AppStorage(Prefs.Key.offline) private var offline = false
    @AppStorage(Prefs.Key.biometrics) private var biometrics = false
    @AppStorage(Prefs.Key.shufflePad) private var shuffle = false
    @AppStorage(Prefs.Key.autoLock) private var autoLock = 60
    @AppStorage(Prefs.Key.wipeAfterFails) private var wipeAfterFails = false
    @AppStorage(Prefs.Key.hideBalances) private var hideBalances = false
    @AppStorage(Prefs.Key.loadImages) private var loadImages = true
    @AppStorage(Prefs.Key.showUnverified) private var showUnverified = false

    @State private var auth: AuthPurpose?
    @State private var phrase: String?
    @State private var confirmErase = false
    @State private var changePin = false
    @State private var message: String?

    enum AuthPurpose: Identifiable { case reveal, enableBio, erase; var id: Int { hashValue } }

    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Security")) {
                    if Vault.biometricsAvailable {
                        Toggle("Unlock with \(Vault.biometryName)", isOn: Binding(get: { biometrics }, set: { on in
                            if on { auth = .enableBio } else { Vault.disableBiometrics(); biometrics = false }
                        }))
                    }
                    Button("Change PIN") { changePin = true }
                    Toggle("Shuffle PIN pad", isOn: $shuffle)
                    Picker("Auto-lock", selection: $autoLock) {
                        Text("Immediately").tag(0)
                        Text("30 seconds").tag(30)
                        Text("1 minute").tag(60)
                        Text("5 minutes").tag(300)
                    }
                    Toggle("Erase after 10 wrong PINs", isOn: $wipeAfterFails)
                }

                Section(header: Text("Privacy"), footer: Text("Offline mode blocks every network request. Balances and sending are paused until you turn it off.")) {
                    Toggle("Offline mode", isOn: $offline)
                    Toggle("Hide balances", isOn: $hideBalances)
                    Toggle("Load collectible images", isOn: $loadImages)
                    Toggle("Show unverified tokens", isOn: $showUnverified)
                    NavigationLink("Endpoints (use your own node)", destination: EndpointsView())
                }

                Section(header: Text("Backup"), footer: Text("Your recovery phrase is the only way to restore funds if this phone is lost, reset or the app is deleted.")) {
                    Button("Show recovery phrase") { auth = .reveal }
                }

                Section(header: Text("Addresses")) {
                    ForEach(Chain.allCases) { c in
                        if let a = app.addresses[c] {
                            Button { Clip.copy(a); message = "\(c.symbol) address copied" } label: {
                                HStack {
                                    Text(c.name).foregroundColor(Theme.text)
                                    Spacer()
                                    Text(shortAddress(a)).font(.mono(13)).foregroundColor(Theme.dim)
                                }
                            }
                        }
                    }
                }

                Section {
                    Button("Erase wallet from this iPhone", role: .destructive) { confirmErase = true }
                }

                Section(footer: VStack(alignment: .leading, spacing: 4) {
                    Text("Unseen Vault \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")")
                    Text("Keys are generated and used only on this device. Signing by Trust Wallet Core (open source).")
                }) { EmptyView() }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { presentation.wrappedValue.dismiss() } }
            }
        }
        .navigationViewStyle(.stack)
        .sheet(item: $auth) { purpose in
            PinAuthSheet(title: purpose == .reveal ? "Show phrase" : purpose == .erase ? "Confirm erase" : "Enable \(Vault.biometryName)") { u in
                switch purpose {
                case .reveal: phrase = u.mnemonic
                case .enableBio:
                    do { try Vault.enableBiometrics(u); biometrics = true } catch { message = error.localizedDescription }
                case .erase:
                    presentation.wrappedValue.dismiss()
                    app.erase()
                }
            }
        }
        .fullScreenCover(item: Binding(get: { phrase.map(PhraseBox.init) }, set: { phrase = $0?.text })) { box in
            PhraseRevealView(phrase: box.text) { phrase = nil }
        }
        .sheet(isPresented: $changePin) { ChangePinView() }
        .alert("Erase this wallet?", isPresented: $confirmErase) {
            Button("Erase", role: .destructive) { auth = .erase }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Make sure your recovery phrase is written down. Without it, funds on this wallet are lost forever.")
        }
        .overlay(alignment: .bottom) {
            if let m = message {
                Toast(text: m).padding(.bottom, 30)
                    .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { message = nil } }
            }
        }
        .preferredColorScheme(.dark)
    }
}

struct PhraseBox: Identifiable {
    let text: String
    var id: String { "phrase" }
}

struct PhraseRevealView: View {
    let phrase: String
    let close: () -> Void
    @StateObject private var capture = CaptureMonitor()

    var body: some View {
        VStack(spacing: 18) {
            FlowHeader(title: "Recovery phrase", onBack: close)
            if capture.captured {
                Spacer()
                Label("Hidden while the screen is being recorded", systemImage: "record.circle").foregroundColor(Theme.danger)
                Spacer()
            } else {
                WordGrid(words: phrase.split(separator: " ").map(String.init)).padding(.horizontal, 20)
                Text("Never share these words. Unseen will never ask for them.")
                    .font(.system(size: 13)).foregroundColor(Theme.warn).multilineTextAlignment(.center).padding(.horizontal, 30)
                Spacer()
            }
            Button("Close", action: close).buttonStyle(PrimaryButton()).padding(20)
        }
        .screen()
    }
}

struct ChangePinView: View {
    @Environment(\.presentationMode) private var presentation
    @State private var old: String?
    @State private var new: String?
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        VStack {
            HStack { Spacer(); Button("Cancel") { presentation.wrappedValue.dismiss() }.foregroundColor(Theme.dim).padding() }
            PinPad(title: old == nil ? "Current PIN" : (new == nil ? "New PIN" : "Confirm new PIN"),
                   error: error, busy: busy) { pin in
                error = nil
                if old == nil { old = pin }
                else if new == nil { new = pin }
                else if pin != new { new = nil; error = "PINs didn't match." }
                else {
                    busy = true
                    let o = old!, n = pin
                    Task.detached(priority: .userInitiated) {
                        let r = Result { try Vault.changePin(old: o, new: n) }
                        await MainActor.run {
                            busy = false
                            switch r {
                            case .success: Haptic.success(); presentation.wrappedValue.dismiss()
                            case .failure(let e): error = e.localizedDescription; old = nil; new = nil
                            }
                        }
                    }
                }
            }
        }
        .screen()
    }
}

struct EndpointsView: View {
    var body: some View {
        List {
            Section(footer: Text("Point each network at your own node or a provider you trust. Leave empty for the default. Requests carry no identifiers, but providers can see your IP; use a VPN or Tor (e.g. Orbot) to hide it.")) {
                ForEach(Chain.allCases) { c in EndpointRow(chain: c) }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Endpoints")
    }
}

private struct EndpointRow: View {
    let chain: Chain
    @AppStorage private var value: String
    init(chain: Chain) {
        self.chain = chain
        _value = AppStorage(wrappedValue: "", Prefs.Key.endpoint(chain))
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(chain.name).font(.system(size: 13, weight: .semibold))
            TextField(chain.defaultEndpoint, text: $value)
                .font(.mono(13))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
        }
    }
}
