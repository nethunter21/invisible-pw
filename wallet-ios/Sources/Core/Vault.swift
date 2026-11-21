import Foundation
import Security
import CryptoKit
import CommonCrypto
import LocalAuthentication

// MARK: - Errors

enum VaultError: LocalizedError {
    case keychain(OSStatus)
    case wrongPin(remaining: Int?)
    case lockedOut(until: Date)
    case corrupted
    case biometricsUnavailable
    case cancelled

    var errorDescription: String? {
        switch self {
        case .keychain(let s): return "Secure storage error (\(s))."
        case .wrongPin(let r):
            if let r { return "Wrong PIN. \(r) attempt\(r == 1 ? "" : "s") before the vault is erased." }
            return "Wrong PIN."
        case .lockedOut(let until):
            let s = max(1, Int(until.timeIntervalSinceNow.rounded(.up)))
            return "Too many attempts. Try again in \(s)s."
        case .corrupted: return "Vault data is unreadable."
        case .biometricsUnavailable: return "Face ID / Touch ID is not available."
        case .cancelled: return "Cancelled."
        }
    }
}

// MARK: - Keychain (device-only, never synced to iCloud)

enum Keychain {
    static let service = "com.unseen.vault"

    static func set(_ data: Data, for key: String, access: SecAccessControl? = nil) throws {
        delete(key)
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any,
        ]
        if let access {
            q[kSecAttrAccessControl as String] = access
        } else {
            q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        }
        let st = SecItemAdd(q as CFDictionary, nil)
        guard st == errSecSuccess else { throw VaultError.keychain(st) }
    }

    static func get(_ key: String, context: LAContext? = nil) throws -> Data? {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        if let context { q[kSecUseAuthenticationContext as String] = context }
        var out: CFTypeRef?
        let st = SecItemCopyMatching(q as CFDictionary, &out)
        if st == errSecItemNotFound { return nil }
        if st == errSecUserCanceled || st == errSecAuthFailed { throw VaultError.cancelled }
        guard st == errSecSuccess else { throw VaultError.keychain(st) }
        return out as? Data
    }

    @discardableResult
    static func delete(_ key: String) -> Bool {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        return SecItemDelete(q as CFDictionary) == errSecSuccess
    }

    static func deleteAll() {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        SecItemDelete(q as CFDictionary)
    }
}

// MARK: - Vault

/// Encrypted seed storage.
///
/// key = HKDF-SHA256( PBKDF2-SHA256(PIN, salt, 310k) || SE-secret )
///   SE-secret = ECDH between a Secure Enclave P-256 key (non-exportable) and a stored public key,
///   so the encrypted seed cannot be brute-forced off-device even if the keychain is extracted.
/// The recovery phrase is sealed with AES-256-GCM; a wrong PIN fails authentication.
enum Vault {
    private static let kSeed = "seed.v1"
    private static let kSE = "se.key"
    private static let kPeer = "se.peer"
    private static let kDevice = "device.secret"
    private static let kBio = "bio.key"
    private static let kFails = "pin.fails"
    private static let kLockUntil = "pin.lockUntil"

    static let pinLength = 6
    static let maxFailsBeforeWipe = 10
    private static let iterations = 310_000

    struct SealedSeed: Codable {
        var v: Int
        var salt: Data
        var iterations: Int
        var box: Data
    }

    struct Unlocked {
        let mnemonic: String
        let key: SymmetricKey
    }

    static var hasWallet: Bool { ((try? Keychain.get(kSeed)) ?? nil) != nil }

    // MARK: Create / unlock

    static func create(mnemonic: String, pin: String) throws {
        // Fresh hardware binding for every new vault.
        Keychain.delete(kSE); Keychain.delete(kPeer); Keychain.delete(kDevice); Keychain.delete(kBio)
        let salt = randomBytes(32)
        let key = try deriveKey(pin: pin, salt: salt, iterations: iterations)
        let sealed = try AES.GCM.seal(Data(mnemonic.utf8), using: key)
        guard let combined = sealed.combined else { throw VaultError.corrupted }
        let blob = SealedSeed(v: 1, salt: salt, iterations: iterations, box: combined)
        try Keychain.set(try JSONEncoder().encode(blob), for: kSeed)
        resetFails()
    }

    static func unlock(pin: String) throws -> Unlocked {
        try checkLockout()
        let blob = try loadBlob()
        let key = try deriveKey(pin: pin, salt: blob.salt, iterations: blob.iterations)
        do {
            let m = try open(blob, key: key)
            resetFails()
            return Unlocked(mnemonic: m, key: key)
        } catch {
            throw registerFail()
        }
    }

    static func changePin(old: String, new: String) throws {
        let u = try unlock(pin: old)
        let hadBio = Prefs.biometrics
        try create(mnemonic: u.mnemonic, pin: new)
        if hadBio {
            let fresh = try unlock(pin: new)
            try? enableBiometrics(fresh)
        }
    }

    // MARK: Biometrics

    static var biometryName: String {
        let c = LAContext()
        _ = c.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        switch c.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        default: return "Biometrics"
        }
    }

    static var biometricsAvailable: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
    }

    static func enableBiometrics(_ u: Unlocked) throws {
        guard biometricsAvailable,
              let ac = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, .biometryCurrentSet, nil)
        else { throw VaultError.biometricsUnavailable }
        let raw = u.key.withUnsafeBytes { Data($0) }
        try Keychain.set(raw, for: kBio, access: ac)
        Prefs.biometrics = true
    }

    static func disableBiometrics() {
        Keychain.delete(kBio)
        Prefs.biometrics = false
    }

    /// Prompts Face ID / Touch ID and decrypts the seed. Blocking: call off the main thread.
    static func unlockWithBiometrics(reason: String) throws -> Unlocked {
        try checkLockout()
        let ctx = LAContext()
        ctx.localizedReason = reason
        ctx.localizedFallbackTitle = ""
        guard let raw = try Keychain.get(kBio, context: ctx) else {
            Prefs.biometrics = false
            throw VaultError.biometricsUnavailable
        }
        let key = SymmetricKey(data: raw)
        let m = try open(try loadBlob(), key: key)
        return Unlocked(mnemonic: m, key: key)
    }

    /// Biometric re-authorisation for signing (no secret material involved).
    static func authorize(reason: String) async -> Bool {
        let ctx = LAContext()
        ctx.localizedFallbackTitle = ""
        return (try? await ctx.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason)) ?? false
    }

    // MARK: Erase

    static func wipe() {
        Keychain.deleteAll()
        Prefs.resetAll()
    }

    // MARK: Attempts / lockout

    static var failedAttempts: Int {
        guard let d = (try? Keychain.get(kFails)) ?? nil, let s = String(data: d, encoding: .utf8) else { return 0 }
        return Int(s) ?? 0
    }

    static var lockedUntil: Date? {
        guard let d = (try? Keychain.get(kLockUntil)) ?? nil, let s = String(data: d, encoding: .utf8),
              let t = TimeInterval(s) else { return nil }
        let date = Date(timeIntervalSince1970: t)
        return date > Date() ? date : nil
    }

    private static func checkLockout() throws {
        if let until = lockedUntil { throw VaultError.lockedOut(until: until) }
    }

    private static func resetFails() {
        Keychain.delete(kFails)
        Keychain.delete(kLockUntil)
    }

    private static func registerFail() -> VaultError {
        let n = failedAttempts + 1
        try? Keychain.set(Data(String(n).utf8), for: kFails)
        if Prefs.wipeAfterFails && n >= maxFailsBeforeWipe {
            wipe()
            return .corrupted
        }
        if n >= 5 {
            let delay = min(3600.0, 30.0 * pow(2.0, Double(n - 5)))
            let until = Date().addingTimeInterval(delay)
            try? Keychain.set(Data(String(until.timeIntervalSince1970).utf8), for: kLockUntil)
            return .lockedOut(until: until)
        }
        return .wrongPin(remaining: Prefs.wipeAfterFails ? maxFailsBeforeWipe - n : nil)
    }

    // MARK: Crypto internals

    private static func loadBlob() throws -> SealedSeed {
        guard let raw = try Keychain.get(kSeed),
              let blob = try? JSONDecoder().decode(SealedSeed.self, from: raw) else { throw VaultError.corrupted }
        return blob
    }

    private static func open(_ blob: SealedSeed, key: SymmetricKey) throws -> String {
        let box = try AES.GCM.SealedBox(combined: blob.box)
        let d = try AES.GCM.open(box, using: key)
        guard let s = String(data: d, encoding: .utf8) else { throw VaultError.corrupted }
        return s
    }

    private static func deriveKey(pin: String, salt: Data, iterations: Int) throws -> SymmetricKey {
        let stretched = try pbkdf2(pin: pin, salt: salt, rounds: iterations)
        let ikm = stretched + (try hardwareSecret())
        return HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: ikm), salt: salt,
                                      info: Data("unseen.vault.v1".utf8), outputByteCount: 32)
    }

    private static func hardwareSecret() throws -> Data {
        if SecureEnclave.isAvailable {
            let se: SecureEnclave.P256.KeyAgreement.PrivateKey
            if let d = try Keychain.get(kSE) {
                se = try SecureEnclave.P256.KeyAgreement.PrivateKey(dataRepresentation: d)
            } else {
                guard let ac = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .privateKeyUsage, nil)
                else { throw VaultError.corrupted }
                se = try SecureEnclave.P256.KeyAgreement.PrivateKey(accessControl: ac)
                try Keychain.set(se.dataRepresentation, for: kSE)
            }
            let peer: P256.KeyAgreement.PublicKey
            if let p = try Keychain.get(kPeer) {
                peer = try P256.KeyAgreement.PublicKey(rawRepresentation: p)
            } else {
                peer = P256.KeyAgreement.PrivateKey().publicKey
                try Keychain.set(peer.rawRepresentation, for: kPeer)
            }
            let shared = try se.sharedSecretFromKeyAgreement(with: peer)
            return shared.withUnsafeBytes { Data($0) }
        }
        if let d = try Keychain.get(kDevice) { return d }
        let d = randomBytes(32)
        try Keychain.set(d, for: kDevice)
        return d
    }

    private static func pbkdf2(pin: String, salt: Data, rounds: Int) throws -> Data {
        var out = Data(count: 32)
        let pw = Array(pin.utf8)
        let status = out.withUnsafeMutableBytes { outPtr in
            salt.withUnsafeBytes { saltPtr in
                CCKeyDerivationPBKDF(
                    CCPBKDFAlgorithm(kCCPBKDF2),
                    pw.map { Int8(bitPattern: $0) }, pw.count,
                    saltPtr.bindMemory(to: UInt8.self).baseAddress, salt.count,
                    CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), UInt32(rounds),
                    outPtr.bindMemory(to: UInt8.self).baseAddress, 32)
            }
        }
        guard status == kCCSuccess else { throw VaultError.corrupted }
        return out
    }

    static func randomBytes(_ n: Int) -> Data {
        var d = Data(count: n)
        let st = d.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, n, $0.baseAddress!) }
        precondition(st == errSecSuccess, "SecRandom failed")
        return d
    }
}

// MARK: - Preferences (non-secret)

enum Prefs {
    static let d = UserDefaults.standard

    enum Key {
        static let offline = "pref.offline"
        static let biometrics = "pref.biometrics"
        static let shufflePad = "pref.shufflePad"
        static let autoLock = "pref.autoLock"
        static let wipeAfterFails = "pref.wipeAfterFails"
        static let hideBalances = "pref.hideBalances"
        static let loadImages = "pref.loadImages"
        static let showUnverified = "pref.showUnverified"
        static func endpoint(_ c: Chain) -> String { "pref.endpoint.\(c.rawValue)" }
    }

    static var offline: Bool { get { d.bool(forKey: Key.offline) } set { d.set(newValue, forKey: Key.offline) } }
    static var biometrics: Bool { get { d.bool(forKey: Key.biometrics) } set { d.set(newValue, forKey: Key.biometrics) } }
    static var wipeAfterFails: Bool { get { d.bool(forKey: Key.wipeAfterFails) } set { d.set(newValue, forKey: Key.wipeAfterFails) } }
    static var autoLock: Int { d.object(forKey: Key.autoLock) as? Int ?? 60 }

    static func endpoint(_ c: Chain) -> String {
        let v = (d.string(forKey: Key.endpoint(c)) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let base = v.isEmpty ? c.defaultEndpoint : v
        return base.hasSuffix("/") ? String(base.dropLast()) : base
    }

    static func resetAll() {
        if let id = Bundle.main.bundleIdentifier { d.removePersistentDomain(forName: id) }
    }
}
