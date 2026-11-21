import SwiftUI
import AVFoundation

struct QRScannerView: View {
    let onScan: (String) -> Void
    @Environment(\.presentationMode) private var presentation
    @State private var denied = false

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            if denied {
                VStack(spacing: 12) {
                    Image(systemName: "camera").font(.system(size: 40)).foregroundColor(Theme.dim)
                    Text("Camera access is off").foregroundColor(Theme.text)
                    Text("Enable it in Settings → Unseen Vault → Camera, or paste the address instead.")
                        .font(.system(size: 13)).foregroundColor(Theme.dim).multilineTextAlignment(.center)
                }
                .padding(30)
            } else {
                ScannerRepresentable(onScan: onScan).ignoresSafeArea()
                RoundedRectangle(cornerRadius: 24).stroke(Color.white, lineWidth: 3).frame(width: 250, height: 250)
            }
            VStack {
                HStack {
                    Spacer()
                    Button { presentation.wrappedValue.dismiss() } label: {
                        Image(systemName: "xmark").font(.system(size: 18, weight: .semibold)).foregroundColor(.white)
                            .frame(width: 44, height: 44).background(Circle().fill(Color.black.opacity(0.6)))
                    }
                }
                Spacer()
                Text("Scan a recipient address").font(.system(size: 14)).foregroundColor(.white).padding(.bottom, 40)
            }
            .padding()
        }
        .onAppear {
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .denied, .restricted: denied = true
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { ok in DispatchQueue.main.async { denied = !ok } }
            default: break
            }
        }
    }
}

private struct ScannerRepresentable: UIViewControllerRepresentable {
    let onScan: (String) -> Void
    func makeUIViewController(context: Context) -> ScannerVC { let vc = ScannerVC(); vc.onScan = onScan; return vc }
    func updateUIViewController(_ vc: ScannerVC, context: Context) {}
}

final class ScannerVC: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onScan: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private var done = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else { return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let p = AVCaptureVideoPreviewLayer(session: session)
        p.videoGravity = .resizeAspectFill
        view.layer.addSublayer(p)
        preview = p
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        session.stopRunning()
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !done, let s = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
        done = true
        Haptic.success()
        onScan?(s)
    }
}
