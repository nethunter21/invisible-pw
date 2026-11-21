import SwiftUI

@main
struct UnseenVaultApp: App {
    @StateObject private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(app)
                .preferredColorScheme(.dark)
                .tint(.white)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            switch app.phase {
            case .onboarding: WelcomeView()
            case .locked: UnlockView()
            case .unlocked: HomeView()
            }
            // Hides balances & keys from the app switcher snapshot.
            if scenePhase != .active { PrivacyShield().transition(.opacity) }
        }
        .onChange(of: scenePhase) { app.scene($0) }
    }
}
