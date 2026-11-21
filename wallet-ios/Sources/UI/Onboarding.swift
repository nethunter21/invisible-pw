import SwiftUI
import WalletCore

struct WelcomeView: View {
    @EnvironmentObject private var app: AppState
    @State private var route: Route?
    enum Route: Identifiable { case create, restore; var id: Int { hashValue } }

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            Logo(size: 84)
            Text("UNSEEN VAULT").font(.mono(22, .bold)).tracking(5).foregroundColor(Theme.text).padding(.top, 26)
            Text("Self-custody. Offline keys. No accounts.")
                .font(.system(size: 15)).foregroundColor(Theme.dim).padding(.top, 8)
            Spacer()
            VStack(alignment: .leading, spacing: 14) {
                feature("lock.shield", "Keys sealed by the Secure Enclave", "Your phrase is encrypted with your PIN and this device's hardware key.")
                feature("eye.slash", "No tracking, no sign-up", "No analytics, no cloud backup, no third-party SDKs.")
                feature("wifi.slash", "Offline mode", "Cut all network access with one switch.")
            }
            .padding(.horizontal, 28)
            Spacer()
            VStack(spacing: 12) {
                Button("Create new wallet") { route = .create }.buttonStyle(PrimaryButton())
                Button("Restore with recovery phrase") { route = .restore }.buttonStyle(SecondaryButton())
            }
            .padding(.horizontal, 20).padding(.bottom, 20)
        }
        .screen()
        .fullScreenCover(item: $route) { r in
            switch r {
            case .create: CreateFlow().environmentObject(app)
            case .restore: RestoreFlow().environmentObject(app)
            }
        }
    }

    private func feature(_ icon: String, _ title: String, _ sub: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon).font(.system(size: 18)).foregroundColor(Theme.accent).frame(width: 26)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 15, weight: .semibold)).foregroundColor(Theme.text)
                Text(sub).font(.system(size: 13)).foregroundColor(Theme.dim)
            }
        }
    }
}

// MARK: - Create

struct CreateFlow: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.presentationMode) private var presentation
    @StateObject private var capture = CaptureMonitor()

    enum Step { case warn, words, verify, pin }
    @State private var step: Step = .warn
    @State private var mnemonic = HDWallet(strength: 256, passphrase: "")?.mnemonic ?? ""
    @State private var revealed = false
    @State private var checks = [false, false, false]

    var words: [String] { mnemonic.split(separator: " ").map(String.init) }

    var body: some View {
        VStack(spacing: 0) {
            FlowHeader(title: header, onBack: back)
            switch step {
            case .warn: warn
            case .words: wordsView
            case .verify: VerifyWords(words: words) { step = .pin }
            case .pin:
                SetPinFlow { pin in
                    try Vault.create(mnemonic: mnemonic, pin: pin)
                    return mnemonic
                }
            }
        }
        .screen()
    }

    private var header: String {
        switch step {
        case .warn: return "Before you start"
        case .words: return "Recovery phrase"
        case .verify: return "Verify phrase"
        case .pin: return "Set PIN"
        }
    }

    private func back() {
        switch step {
        case .warn: presentation.wrappedValue.dismiss()
        case .words: step = .warn
        case .verify: step = .words
        case .pin: step = .verify
        }
    }

    private var warn: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("You'll get 24 words. They are the only backup of your funds.")
                .font(.system(size: 17, weight: .medium)).foregroundColor(Theme.text)
            checkRow(0, "I will write the words on paper, in order, and keep them offline.")
            checkRow(1, "Anyone who sees these words can take my funds.")
            checkRow(2, "If I lose them, nobody, including Unseen, can recover my wallet.")
            Spacer()
            Button("Show my recovery phrase") { step = .words }
                .buttonStyle(PrimaryButton(enabled: checks.allSatisfy { $0 }))
                .disabled(!checks.allSatisfy { $0 })
        }
        .padding(20)
    }

    private func checkRow(_ i: Int, _ text: String) -> some View {
        Button { checks[i].toggle(); Haptic.tap() } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: checks[i] ? "checkmark.square.fill" : "square")
                    .font(.system(size: 20)).foregroundColor(checks[i] ? Theme.accent : Theme.dim)
                Text(text).font(.system(size: 15)).foregroundColor(Theme.text).multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .card()
        }
        .buttonStyle(.plain)
    }

    private var wordsView: some View {
        VStack(spacing: 16) {
            ZStack {
                WordGrid(words: words)
                    .blur(radius: revealed && !capture.captured ? 0 : 14)
                if capture.captured {
                    Label("Screen recording detected", systemImage: "record.circle").foregroundColor(Theme.danger)
                } else if !revealed {
                    Button { revealed = true } label: {
                        Label("Tap to reveal", systemImage: "eye").font(.system(size: 16, weight: .semibold))
                            .padding(.horizontal, 18).padding(.vertical, 12)
                            .background(Capsule().fill(Theme.surface2))
                    }
                    .foregroundColor(.white)
                }
            }
            if capture.screenshotTaken {
                Text("A screenshot was taken. Screenshots sync to iCloud Photos. Delete it, or create a new wallet.")
                    .font(.system(size: 13)).foregroundColor(Theme.danger).multilineTextAlignment(.center)
            } else {
                Text("Write these down in order. Never photograph or type them anywhere.")
                    .font(.system(size: 13)).foregroundColor(Theme.dim).multilineTextAlignment(.center)
            }
            Spacer()
            Button("I've written them down") { step = .verify }
                .buttonStyle(PrimaryButton(enabled: revealed))
                .disabled(!revealed)
        }
        .padding(20)
    }
}

struct WordGrid: View {
    let words: [String]
    var body: some View {
        let cols = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
        LazyVGrid(columns: cols, spacing: 10) {
            ForEach(Array(words.enumerated()), id: \.offset) { i, w in
                HStack(spacing: 6) {
                    Text("\(i + 1)").font(.mono(11)).foregroundColor(Theme.faint).frame(width: 20, alignment: .trailing)
                    Text(w).font(.mono(14, .medium)).foregroundColor(Theme.text).lineLimit(1).minimumScaleFactor(0.7)
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 9).padding(.horizontal, 8)
                .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surface))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.stroke))
            }
        }
    }
}

struct VerifyWords: View {
    let words: [String]
    let onDone: () -> Void

    @State private var positions: [Int] = []
    @State private var current = 0
    @State private var options: [String] = []
    @State private var wrong: String?

    var body: some View {
        VStack(spacing: 22) {
            if current < positions.count {
                Text("Select word #\(positions[current] + 1)")
                    .font(.system(size: 22, weight: .semibold)).foregroundColor(Theme.text).padding(.top, 30)
                Text("Check \(current + 1) of \(positions.count)").font(.system(size: 14)).foregroundColor(Theme.dim)
                VStack(spacing: 10) {
                    ForEach(options, id: \.self) { o in
                        Button(o) { pick(o) }
                            .buttonStyle(SecondaryButton(tint: wrong == o ? Theme.danger : Theme.text))
                            .font(.mono(17))
                    }
                }
                .padding(.top, 10)
            }
            Spacer()
        }
        .padding(20)
        .onAppear(perform: setup)
    }

    private func setup() {
        positions = Array(Array(0..<words.count).shuffled().prefix(4)).sorted()
        current = 0
        makeOptions()
    }

    private func makeOptions() {
        guard current < positions.count else { return }
        let correct = words[positions[current]]
        var pool = Set(words.filter { $0 != correct }.shuffled().prefix(3))
        pool.insert(correct)
        options = Array(pool).shuffled()
        wrong = nil
    }

    private func pick(_ o: String) {
        if o == words[positions[current]] {
            Haptic.success()
            current += 1
            if current >= positions.count { onDone() } else { makeOptions() }
        } else {
            wrong = o
            Haptic.error()
        }
    }
}

// MARK: - Restore

struct RestoreFlow: View {
    @Environment(\.presentationMode) private var presentation
    @State private var count = 24
    @State private var words: [String] = []
    @State private var input = ""
    @State private var done = false
    @State private var error: String?
    @FocusState private var focused: Bool

    var suggestions: [String] {
        let p = input.lowercased().trimmingCharacters(in: .whitespaces)
        guard p.count >= 1 else { return [] }
        return Array(Mnemonic.suggest(prefix: p).split(separator: " ").map(String.init).prefix(6))
    }

    var phrase: String { words.joined(separator: " ") }

    var body: some View {
        VStack(spacing: 0) {
            FlowHeader(title: done ? "Set PIN" : "Restore wallet") {
                if done { done = false } else { presentation.wrappedValue.dismiss() }
            }
            if done {
                SetPinFlow { pin in
                    try Vault.create(mnemonic: phrase, pin: pin)
                    return phrase
                }
            } else {
                entry
            }
        }
        .screen()
    }

    private var entry: some View {
        VStack(spacing: 16) {
            Picker("Words", selection: $count) {
                Text("12 words").tag(12)
                Text("24 words").tag(24)
            }
            .pickerStyle(.segmented)
            .onChange(of: count) { _ in words = []; error = nil }

            if words.count < count {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Word \(words.count + 1) of \(count)").font(.system(size: 14)).foregroundColor(Theme.dim)
                    TextField("", text: $input)
                        .font(.mono(20, .medium))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.asciiCapable)
                        .textContentType(.oneTimeCode)
                        .focused($focused)
                        .padding(14)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Theme.surface))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.stroke))
                        .onSubmit { if suggestions.count == 1 { add(suggestions[0]) } else if Mnemonic.isValidWord(word: input.lowercased()) { add(input.lowercased()) } }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(suggestions, id: \.self) { s in
                                Button(s) { add(s) }
                                    .font(.mono(15, .medium)).foregroundColor(.black)
                                    .padding(.horizontal, 14).padding(.vertical, 9)
                                    .background(Capsule().fill(Color.white))
                            }
                        }
                    }
                    .frame(height: 40)
                }
            }

            if !words.isEmpty {
                ScrollView {
                    WordGrid(words: words)
                }
            }
            if let error { Text(error).font(.system(size: 13)).foregroundColor(Theme.danger) }
            Spacer(minLength: 0)
            HStack(spacing: 12) {
                Button("Undo") { if !words.isEmpty { words.removeLast(); error = nil } }
                    .buttonStyle(SecondaryButton()).disabled(words.isEmpty)
                Button("Continue") {
                    if Mnemonic.isValid(mnemonic: phrase) { done = true; focused = false }
                    else { error = "Checksum invalid: a word is wrong or out of order."; Haptic.error() }
                }
                .buttonStyle(PrimaryButton(enabled: words.count == count))
                .disabled(words.count != count)
            }
        }
        .padding(20)
        .onAppear { focused = true }
    }

    private func add(_ w: String) {
        guard words.count < count else { return }
        words.append(w)
        input = ""
        Haptic.tap()
        if words.count == count {
            focused = false
            if !Mnemonic.isValid(mnemonic: phrase) { error = "Checksum invalid: a word is wrong or out of order." }
        }
    }
}

// MARK: - Shared

struct FlowHeader: View {
    let title: String
    let onBack: () -> Void
    var body: some View {
        ZStack {
            Text(title).font(.system(size: 17, weight: .semibold)).foregroundColor(Theme.text)
            HStack {
                Button(action: onBack) {
                    Image(systemName: "chevron.left").font(.system(size: 18, weight: .semibold))
                        .foregroundColor(Theme.text).frame(width: 44, height: 44)
                }
                Spacer()
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 52)
    }
}

/// Enter + confirm PIN, then persist and open the wallet; offers biometrics afterwards.
struct SetPinFlow: View {
    @EnvironmentObject private var app: AppState
    let persist: (String) throws -> String

    @State private var first: String?
    @State private var error: String?
    @State private var busy = false
    @State private var unlocked: Vault.Unlocked?

    var body: some View {
        if let u = unlocked {
            BiometricOffer(unlocked: u) { app.open(mnemonic: u.mnemonic) }
        } else {
            PinPad(title: first == nil ? "Choose a PIN" : "Confirm PIN",
                   subtitle: first == nil ? "6 digits. Protects this device only; your phrase is the real backup." : nil,
                   error: error, busy: busy) { pin in
                error = nil
                if first == nil {
                    if Set(pin).count == 1 || "0123456789876543210".contains(pin) {
                        error = "Too easy to guess. Pick another PIN."
                        return
                    }
                    first = pin
                } else if pin != first {
                    first = nil
                    error = "PINs didn't match. Start again."
                } else {
                    busy = true
                    Task.detached(priority: .userInitiated) {
                        let r = Result { () throws -> Vault.Unlocked in
                            _ = try persist(pin)
                            return try Vault.unlock(pin: pin)
                        }
                        await MainActor.run {
                            busy = false
                            switch r {
                            case .success(let u): unlocked = u
                            case .failure(let e): error = e.localizedDescription; first = nil
                            }
                        }
                    }
                }
            }
        }
    }
}

struct BiometricOffer: View {
    let unlocked: Vault.Unlocked
    let finish: () -> Void
    @State private var error: String?

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "faceid").font(.system(size: 64, weight: .light)).foregroundColor(Theme.text)
            Text("Use \(Vault.biometryName)?").font(.system(size: 22, weight: .semibold)).foregroundColor(Theme.text)
            Text("Unlock and approve transactions faster. Your PIN always works as a fallback.")
                .font(.system(size: 15)).foregroundColor(Theme.dim).multilineTextAlignment(.center).padding(.horizontal, 30)
            if let error { Text(error).font(.system(size: 13)).foregroundColor(Theme.danger) }
            Spacer()
            VStack(spacing: 12) {
                if Vault.biometricsAvailable {
                    Button("Enable \(Vault.biometryName)") {
                        do { try Vault.enableBiometrics(unlocked); finish() } catch { self.error = error.localizedDescription }
                    }
                    .buttonStyle(PrimaryButton())
                }
                Button("Not now") { Vault.disableBiometrics(); finish() }.buttonStyle(SecondaryButton())
            }
            .padding(20)
        }
    }
}
