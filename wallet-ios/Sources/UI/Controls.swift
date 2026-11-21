import SwiftUI

// MARK: - PIN pad (custom, never uses the system keyboard)

struct PinPad: View {
    let title: String
    var subtitle: String? = nil
    var error: String? = nil
    var busy = false
    var showBiometric = false
    var onBiometric: (() -> Void)? = nil
    let onComplete: (String) -> Void

    @State private var pin = ""
    @State private var shake = 0
    @AppStorage(Prefs.Key.shufflePad) private var shuffle = false
    @State private var digits: [Int] = Array(1...9) + [0]

    var body: some View {
        VStack(spacing: 0) {
            Spacer(minLength: 12)
            Text(title).font(.system(size: 22, weight: .semibold)).foregroundColor(Theme.text)
            if let subtitle {
                Text(subtitle).font(.system(size: 14)).foregroundColor(Theme.dim)
                    .multilineTextAlignment(.center).padding(.top, 6).padding(.horizontal, 32)
            }
            HStack(spacing: 18) {
                ForEach(0..<Vault.pinLength, id: \.self) { i in
                    Circle()
                        .fill(i < pin.count ? Color.white : Color.clear)
                        .overlay(Circle().stroke(i < pin.count ? Color.white : Theme.faint, lineWidth: 1.5))
                        .frame(width: 14, height: 14)
                }
            }
            .padding(.top, 28)
            .modifier(Shake(animatableData: CGFloat(shake)))

            ZStack {
                if busy { ProgressView().tint(.white) }
                else if let error { Text(error).font(.system(size: 13)).foregroundColor(Theme.danger).multilineTextAlignment(.center) }
            }
            .frame(height: 44).padding(.horizontal, 24)

            Spacer(minLength: 12)
            let grid = digits
            VStack(spacing: 14) {
                ForEach(0..<3) { r in
                    HStack(spacing: 22) {
                        ForEach(0..<3) { c in key(grid[r * 3 + c]) }
                    }
                }
                HStack(spacing: 22) {
                    if showBiometric, let onBiometric {
                        Button(action: onBiometric) {
                            Image(systemName: "faceid").font(.system(size: 26)).foregroundColor(Theme.text)
                                .frame(width: 78, height: 78)
                        }
                    } else { Color.clear.frame(width: 78, height: 78) }
                    key(grid[9])
                    Button {
                        if !pin.isEmpty { pin.removeLast(); Haptic.tap() }
                    } label: {
                        Image(systemName: "delete.left").font(.system(size: 22)).foregroundColor(Theme.text)
                            .frame(width: 78, height: 78)
                    }
                }
            }
            .padding(.bottom, 28)
        }
        .onAppear { if shuffle { digits.shuffle() } }
        .onChange(of: error) { e in if e != nil { pin = ""; withAnimation(.default) { shake += 1 }; Haptic.error() } }
    }

    private func key(_ d: Int) -> some View {
        Button {
            guard !busy, pin.count < Vault.pinLength else { return }
            Haptic.tap()
            pin.append(String(d))
            if pin.count == Vault.pinLength {
                let p = pin
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                    onComplete(p)
                    pin = ""
                    if shuffle { digits.shuffle() }
                }
            }
        } label: {
            Text("\(d)").font(.system(size: 30, weight: .regular, design: .rounded)).foregroundColor(Theme.text)
                .frame(width: 78, height: 78)
                .background(Circle().fill(Theme.surface2))
        }
        .buttonStyle(.plain)
    }
}

struct Shake: GeometryEffect {
    var animatableData: CGFloat
    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 10 * sin(animatableData * .pi * 4), y: 0))
    }
}

// MARK: - Hold-to-sign (physical-button feel of a hardware wallet)

struct HoldToConfirm: View {
    let title: String
    var duration: Double = 1.3
    var enabled = true
    let action: () -> Void

    @State private var progress: CGFloat = 0
    @State private var done = false

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 14).fill(Theme.surface2)
                RoundedRectangle(cornerRadius: 14).fill(Color.white)
                    .frame(width: geo.size.width * progress)
                HStack(spacing: 8) {
                    Image(systemName: done ? "checkmark" : "hand.tap")
                    Text(done ? "Signed" : title)
                }
                .font(.system(size: 17, weight: .semibold))
                .frame(maxWidth: .infinity)
                .foregroundColor(progress > 0.5 ? .black : .white)
            }
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.stroke))
            .opacity(enabled ? 1 : 0.4)
            .contentShape(Rectangle())
            .onLongPressGesture(minimumDuration: duration, maximumDistance: 40, pressing: { pressing in
                guard enabled, !done else { return }
                if pressing {
                    Haptic.tap()
                    withAnimation(.linear(duration: duration)) { progress = 1 }
                } else {
                    withAnimation(.easeOut(duration: 0.2)) { progress = 0 }
                }
            }, perform: {
                guard enabled, !done else { return }
                done = true
                progress = 1
                Haptic.success()
                action()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { done = false; progress = 0 }
            })
        }
        .frame(height: 58)
    }
}

// MARK: - PIN authorisation sheet

struct PinAuthSheet: View {
    let title: String
    let onSuccess: (Vault.Unlocked) -> Void
    @Environment(\.presentationMode) private var presentation
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        VStack {
            HStack {
                Spacer()
                Button("Cancel") { presentation.wrappedValue.dismiss() }.foregroundColor(Theme.dim).padding()
            }
            PinPad(title: title, subtitle: "Enter your 6-digit PIN", error: error, busy: busy) { pin in
                busy = true; error = nil
                Task.detached(priority: .userInitiated) {
                    let result = Result { try Vault.unlock(pin: pin) }
                    await MainActor.run {
                        busy = false
                        switch result {
                        case .success(let u):
                            presentation.wrappedValue.dismiss()
                            onSuccess(u)
                        case .failure(let e): error = e.localizedDescription
                        }
                    }
                }
            }
        }
        .screen()
    }
}
