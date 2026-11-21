import Foundation

/// Minimal arbitrary-precision unsigned integer used for on-chain amounts
/// (ETH wei and ERC-20 balances overflow UInt64).
struct BigUInt: Comparable, Hashable, CustomStringConvertible {
    private(set) var limbs: [UInt32] = [] // little-endian, no trailing zero limbs

    init() {}

    init(_ v: UInt64) {
        limbs = [UInt32(truncatingIfNeeded: v), UInt32(truncatingIfNeeded: v >> 32)]
        normalize()
    }

    init<T: BinaryInteger>(_ v: T) { self.init(UInt64(clamping: v)) }

    init?(decimal s: String) {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return nil }
        for c in t.utf8 {
            guard c >= 48, c <= 57 else { return nil }
            mulAdd(10, UInt32(c - 48))
        }
    }

    init?(hex s: String) {
        var t = Substring(s.trimmingCharacters(in: .whitespaces))
        if t.hasPrefix("0x") || t.hasPrefix("0X") { t = t.dropFirst(2) }
        for c in t.utf8 {
            let v: UInt8
            switch c {
            case 48...57: v = c - 48
            case 97...102: v = c - 87
            case 65...70: v = c - 55
            default: return nil
            }
            mulAdd(16, UInt32(v))
        }
    }

    init(bigEndian data: Data) {
        for b in data { mulAdd(256, UInt32(b)) }
    }

    var isZero: Bool { limbs.isEmpty }

    var uint64: UInt64? {
        switch limbs.count {
        case 0: return 0
        case 1: return UInt64(limbs[0])
        case 2: return UInt64(limbs[0]) | (UInt64(limbs[1]) << 32)
        default: return nil
        }
    }

    var int64: Int64? {
        guard let u = uint64, u <= UInt64(Int64.max) else { return nil }
        return Int64(u)
    }

    private mutating func normalize() {
        while limbs.last == 0 { limbs.removeLast() }
    }

    private mutating func mulAdd(_ m: UInt32, _ a: UInt32) {
        var carry = UInt64(a)
        for i in limbs.indices {
            let p = UInt64(limbs[i]) * UInt64(m) + carry
            limbs[i] = UInt32(truncatingIfNeeded: p)
            carry = p >> 32
        }
        if carry > 0 { limbs.append(UInt32(carry)) }
        normalize()
    }

    func divMod(_ d: UInt32) -> (BigUInt, UInt32) {
        precondition(d != 0)
        var q = BigUInt()
        q.limbs = Array(repeating: 0, count: limbs.count)
        var rem: UInt64 = 0
        for i in stride(from: limbs.count - 1, through: 0, by: -1) {
            let cur = (rem << 32) | UInt64(limbs[i])
            q.limbs[i] = UInt32(cur / UInt64(d))
            rem = cur % UInt64(d)
        }
        q.normalize()
        return (q, UInt32(rem))
    }

    var description: String {
        if isZero { return "0" }
        var parts: [UInt32] = []
        var n = self
        while !n.isZero {
            let (q, r) = n.divMod(1_000_000_000)
            parts.append(r)
            n = q
        }
        var s = String(parts.last!)
        for p in parts.dropLast().reversed() {
            let x = String(p)
            s += String(repeating: "0", count: 9 - x.count) + x
        }
        return s
    }

    /// Minimal big-endian bytes (zero encodes as a single 0x00 byte).
    var bigEndianData: Data {
        if isZero { return Data([0]) }
        var out = [UInt8]()
        out.reserveCapacity(limbs.count * 4)
        for l in limbs.reversed() {
            out += [UInt8((l >> 24) & 0xff), UInt8((l >> 16) & 0xff), UInt8((l >> 8) & 0xff), UInt8(l & 0xff)]
        }
        while out.first == 0 { out.removeFirst() }
        return Data(out)
    }

    /// 32-byte left-padded hex word for ABI encoding.
    var abiWord: String {
        let h = bigEndianData.map { String(format: "%02x", $0) }.joined()
        return String(repeating: "0", count: max(0, 64 - h.count)) + h
    }

    static func < (a: BigUInt, b: BigUInt) -> Bool {
        if a.limbs.count != b.limbs.count { return a.limbs.count < b.limbs.count }
        for i in stride(from: a.limbs.count - 1, through: 0, by: -1) where a.limbs[i] != b.limbs[i] {
            return a.limbs[i] < b.limbs[i]
        }
        return false
    }

    static func + (a: BigUInt, b: BigUInt) -> BigUInt {
        var r = BigUInt()
        let n = max(a.limbs.count, b.limbs.count)
        r.limbs.reserveCapacity(n + 1)
        var carry: UInt64 = 0
        for i in 0..<n {
            let s = UInt64(i < a.limbs.count ? a.limbs[i] : 0) + UInt64(i < b.limbs.count ? b.limbs[i] : 0) + carry
            r.limbs.append(UInt32(truncatingIfNeeded: s))
            carry = s >> 32
        }
        if carry > 0 { r.limbs.append(UInt32(carry)) }
        r.normalize()
        return r
    }

    /// Saturating subtraction: returns 0 when b > a.
    static func - (a: BigUInt, b: BigUInt) -> BigUInt {
        if a <= b { return BigUInt() }
        var r = BigUInt()
        var borrow: Int64 = 0
        for i in 0..<a.limbs.count {
            var d = Int64(a.limbs[i]) - Int64(i < b.limbs.count ? b.limbs[i] : 0) - borrow
            if d < 0 { d += 1 << 32; borrow = 1 } else { borrow = 0 }
            r.limbs.append(UInt32(d))
        }
        r.normalize()
        return r
    }

    static func * (a: BigUInt, b: BigUInt) -> BigUInt {
        if a.isZero || b.isZero { return BigUInt() }
        var res = [UInt32](repeating: 0, count: a.limbs.count + b.limbs.count)
        for i in 0..<a.limbs.count {
            var carry: UInt64 = 0
            for j in 0..<b.limbs.count {
                let t = UInt64(a.limbs[i]) * UInt64(b.limbs[j]) + UInt64(res[i + j]) + carry
                res[i + j] = UInt32(truncatingIfNeeded: t)
                carry = t >> 32
            }
            res[i + b.limbs.count] = UInt32(carry)
        }
        var r = BigUInt()
        r.limbs = res
        r.normalize()
        return r
    }

    static func / (a: BigUInt, d: UInt32) -> BigUInt { a.divMod(d).0 }
}

enum Amount {
    /// Formats base units as a human decimal string (no grouping, '.' separator).
    static func format(_ v: BigUInt, decimals: Int, maxFraction: Int? = nil) -> String {
        var s = v.description
        guard decimals > 0 else { return s }
        if s.count <= decimals { s = String(repeating: "0", count: decimals - s.count + 1) + s }
        let intPart = String(s.prefix(s.count - decimals))
        var frac = String(s.suffix(decimals))
        if let m = maxFraction, frac.count > m { frac = String(frac.prefix(m)) }
        while frac.hasSuffix("0") { frac.removeLast() }
        return frac.isEmpty ? intPart : intPart + "." + frac
    }

    /// Parses a user-entered decimal string into base units. Rejects excess precision.
    static func parse(_ input: String, decimals: Int) -> BigUInt? {
        let t = input.replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: " ", with: "")
        guard !t.isEmpty, t != "." else { return nil }
        let parts = t.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count <= 2 else { return nil }
        let i = parts[0].isEmpty ? "0" : String(parts[0])
        var f = parts.count == 2 ? String(parts[1]) : ""
        guard f.count <= decimals else { return nil }
        f += String(repeating: "0", count: decimals - f.count)
        return BigUInt(decimal: i + f)
    }
}
