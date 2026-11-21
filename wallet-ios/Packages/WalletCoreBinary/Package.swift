// swift-tools-version:5.9
// Thin wrapper around Trust Wallet Core's official prebuilt xcframeworks (release 4.2.9).
// Upstream's manifest declares tools-version 5.3, which current Xcode rejects. Checksums pin the exact binaries.
import PackageDescription

let package = Package(
    name: "WalletCoreBinary",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "WalletCore", targets: ["WalletCore", "SwiftProtobuf"]),
    ],
    targets: [
        .binaryTarget(
            name: "WalletCore",
            url: "https://github.com/trustwallet/wallet-core/releases/download/4.2.9/WalletCore.xcframework.zip",
            checksum: "651894a9418fdd33ae5374367a6a64a57fa92b6e6ffb2d6723c319da97472cb4"
        ),
        .binaryTarget(
            name: "SwiftProtobuf",
            url: "https://github.com/trustwallet/wallet-core/releases/download/4.2.9/SwiftProtobuf.xcframework.zip",
            checksum: "946efd4b0132b92208335902e0b65e0aba2d11b9dd6f6d79cc8318e2530c9ae0"
        ),
    ]
)
