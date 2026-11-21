import SwiftUI
import UIKit
import UniformTypeIdentifiers
import CoreImage.CIFilterBuiltins

enum Theme {
    static let bg = Color.black
    static let surface = Color(white: 0.07)
    static let surface2 = Color(white: 0.12)
    static let stroke = Color.white.opacity(0.09)
    static let text = Color.white
    static let dim = Color(white: 0.56)
    static let faint = Color(white: 0.32)
    static let accent = Color(red: 0.0, green: 0.90, blue: 0.63)
    static let warn = Color(red: 1.0, green: 0.72, blue: 0.20)
    static let danger = Color(red: 1.0, green: 0.30, blue: 0.35)
}

extension Font {
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

enum Haptic {
    static func tap() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func error() { UINotificationFeedbackGenerator().notificationOccurred(.error) }
}

/// Clipboard that never syncs to other devices (no Universal Clipboard) and clears itself.
enum Clip {
    static func copy(_ s: String, seconds: TimeInterval = 60) {
        UIPasteboard.general.setItems([[UTType.plainText.identifier: s]],
                                      options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(seconds)])
        Haptic.success()
    }
}

// MARK: - Buttons

struct PrimaryButton: ButtonStyle {
    var enabled = true
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundColor(.black)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(RoundedRectangle(cornerRadius: 14).fill(enabled ? Color.white : Color(white: 0.35)))
            .opacity(configuration.isPressed ? 0.8 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
    }
}

struct SecondaryButton: ButtonStyle {
    var tint: Color = Theme.text
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundColor(tint)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(RoundedRectangle(cornerRadius: 14).fill(Theme.surface2))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.stroke))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 18).fill(Theme.surface))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Theme.stroke))
    }
}

extension View {
    func card() -> some View { modifier(CardModifier()) }

    func screen() -> some View {
        frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(Theme.bg.ignoresSafeArea())
    }
}

// MARK: - Brand

struct Logo: View {
    var size: CGFloat = 64
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.16)
                .stroke(Color.white, lineWidth: size * 0.07)
                .frame(width: size, height: size * 0.92)
            VStack(spacing: 0) {
                Circle().fill(Theme.accent).frame(width: size * 0.24, height: size * 0.24)
                Rectangle().fill(Theme.accent).frame(width: size * 0.1, height: size * 0.22)
            }
        }
    }
}

struct AssetIcon: View {
    let asset: Asset
    var size: CGFloat = 40
    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Circle()
                .fill(asset.isNative ? asset.chain.tint.opacity(0.18) : Theme.surface2)
                .overlay(Circle().stroke(asset.isNative ? asset.chain.tint.opacity(0.6) : Theme.stroke, lineWidth: 1))
                .overlay(
                    Text(String(asset.symbol.prefix(asset.symbol.count > 4 ? 3 : 4)))
                        .font(.system(size: size * (asset.symbol.count > 3 ? 0.24 : 0.3), weight: .bold, design: .rounded))
                        .foregroundColor(asset.isNative ? asset.chain.tint : .white)
                )
                .frame(width: size, height: size)
            if !asset.isNative {
                Circle().fill(asset.chain.tint)
                    .frame(width: size * 0.36, height: size * 0.36)
                    .overlay(Circle().stroke(Theme.bg, lineWidth: 2))
                    .offset(x: 2, y: 2)
            }
        }
    }
}

// MARK: - QR

struct QRCodeView: View {
    let text: String
    var body: some View {
        if let img = Self.make(text) {
            Image(uiImage: img).interpolation(.none).resizable().scaledToFit()
        } else {
            Color.white
        }
    }

    static func make(_ s: String) -> UIImage? {
        let f = CIFilter.qrCodeGenerator()
        f.message = Data(s.utf8)
        f.correctionLevel = "M"
        guard let out = f.outputImage?.transformed(by: CGAffineTransform(scaleX: 10, y: 10)),
              let cg = CIContext().createCGImage(out, from: out.extent) else { return nil }
        return UIImage(cgImage: cg)
    }
}

/// Address split in groups of 4 for easy visual verification (Ledger/Trezor style).
struct ChunkedAddress: View {
    let address: String
    var size: CGFloat = 15
    var body: some View {
        let chunks = stride(from: 0, to: address.count, by: 4).map { i -> String in
            let s = address.index(address.startIndex, offsetBy: i)
            let e = address.index(s, offsetBy: min(4, address.count - i))
            return String(address[s..<e])
        }
        let rows = stride(from: 0, to: chunks.count, by: 4).map { Array(chunks[$0..<min($0 + 4, chunks.count)]) }
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(spacing: 10) {
                    ForEach(Array(row.enumerated()), id: \.offset) { i, c in
                        Text(c).font(.mono(size, .medium))
                            .foregroundColor(i % 2 == 0 ? Theme.text : Theme.dim)
                    }
                }
            }
        }
    }
}

func shortAddress(_ a: String) -> String {
    guard a.count > 14 else { return a }
    return "\(a.prefix(6))…\(a.suffix(6))"
}

// MARK: - Screen capture shield

final class CaptureMonitor: ObservableObject {
    @Published var captured = UIScreen.main.isCaptured
    @Published var screenshotTaken = false
    private var tokens: [NSObjectProtocol] = []

    init() {
        let nc = NotificationCenter.default
        tokens.append(nc.addObserver(forName: UIScreen.capturedDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.captured = UIScreen.main.isCaptured
        })
        tokens.append(nc.addObserver(forName: UIApplication.userDidTakeScreenshotNotification, object: nil, queue: .main) { [weak self] _ in
            self?.screenshotTaken = true
        })
    }

    deinit { for t in tokens { NotificationCenter.default.removeObserver(t) } }
}

struct PrivacyShield: View {
    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(spacing: 14) {
                Logo(size: 56)
                Text("UNSEEN VAULT").font(.mono(13, .semibold)).foregroundColor(Theme.dim).tracking(3)
            }
        }
    }
}

struct Pill: View {
    let text: String
    var color: Color = Theme.dim
    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(color)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(Capsule().fill(color.opacity(0.14)))
    }
}

struct Toast: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 14, weight: .semibold))
            .foregroundColor(.black)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(Capsule().fill(Color.white))
            .shadow(radius: 10)
    }
}
