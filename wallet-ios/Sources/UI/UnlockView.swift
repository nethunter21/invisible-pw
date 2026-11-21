import SwiftUI

struct UnlockView: View {
    @EnvironmentObject private var app: AppState
    @State private var error: String?
    @State private var busy = false
    @State private var confirmReset = false
    @State private var restore = false
    @State private var triedBio = false

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                Logo(size: 44)
                Text("UNSEEN VAULT").font(.mono(13, .semibold)).tracking(3).foregroundColor(Theme.dim)
            }
            .padding(.top, 30)

            PinPad(title: "Enter PIN", error: error, busy: busy,
                   showBiometric: Prefs.biometrics, onBiometric: biometric) { pin in
                unlock(pin)
            }

            Button("Forgot PIN?") { confirmReset = true }
                .font(.system(size: 14)).foregroundColor(Theme.dim).padding(.bottom, 12)
        }
        .screen()
        .onAppear {
            if Prefs.biometrics && !triedBio { triedBio = true; biometric() }
            if let until = Vault.lockedUntil { error = VaultError.lockedOut(until: until).localizedDescription }
        }
        .alert("Reset with recovery phrase?", isPresented: $confirmReset) {
            Button("Erase & restore", role: .destructive) {
                Vault.wipe()
                restore = true
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This erases the vault on this phone. You'll need your recovery phrase to restore it. Without the phrase your funds are lost.")
        }
        .fullScreenCover(isPresented: $restore, onDismiss: {
            if !Vault.hasWallet { app.phase = .onboarding }
        }) {
            RestoreFlow().environmentObject(app)
        }
    }

    private func unlock(_ pin: String) {
        busy = true
        error = nil
        Task.detached(priority: .userInitiated) {
            let r = Result { try Vault.unlock(pin: pin) }
            await MainActor.run {
                busy = false
                switch r {
                case .success(let u): app.open(mnemonic: u.mnemonic)
                case .failure(let e):
                    error = e.localizedDescription
                    if !Vault.hasWallet { app.phase = .onboarding }
                }
            }
        }
    }

    private func biometric() {
        busy = true
        Task.detached(priority: .userInitiated) {
            let r = Result { try Vault.unlockWithBiometrics(reason: "Unlock Unseen Vault") }
            await MainActor.run {
                busy = false
                if case .success(let u) = r { app.open(mnemonic: u.mnemonic) }
            }
        }
    }
}
