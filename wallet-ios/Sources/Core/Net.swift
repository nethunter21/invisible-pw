import Foundation

enum NetError: LocalizedError {
    case offline
    case badURL
    case http(Int, String)
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .offline: return "Offline mode is on. Turn it off in Settings to connect."
        case .badURL: return "Invalid endpoint URL."
        case .http(let c, let b): return "Network error \(c). \(b)"
        case .invalid(let m): return m
        }
    }
}

typealias JSON = [String: Any]

extension Dictionary where Key == String, Value == Any {
    func d(_ k: String) -> JSON? { self[k] as? JSON }
    func a(_ k: String) -> [Any]? { self[k] as? [Any] }
    func s(_ k: String) -> String? {
        if let v = self[k] as? String { return v }
        if let n = self[k] as? NSNumber { return n.stringValue }
        return nil
    }
    func i(_ k: String) -> Int64? {
        if let n = self[k] as? NSNumber { return n.int64Value }
        if let s = self[k] as? String { return Int64(s) }
        return nil
    }
}

/// Privacy-hardened HTTP client: ephemeral session, no cache, no cookies,
/// generic user agent, global kill switch (Offline mode).
final class Net {
    static let shared = Net()
    private let session: URLSession

    private init() {
        let c = URLSessionConfiguration.ephemeral
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.urlCache = nil
        c.httpCookieStorage = nil
        c.httpShouldSetCookies = false
        c.httpCookieAcceptPolicy = .never
        c.timeoutIntervalForRequest = 25
        c.waitsForConnectivity = false
        c.httpAdditionalHeaders = ["User-Agent": "Mozilla/5.0", "Accept": "application/json"]
        session = URLSession(configuration: c)
    }

    func request(_ url: URL, method: String = "GET", body: Data? = nil,
                 contentType: String = "application/json") async throws -> Data {
        if Prefs.offline { throw NetError.offline }
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.httpBody = body
        if body != nil { r.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        for attempt in 0..<3 {
            let (d, resp) = try await session.data(for: r)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if code == 429, attempt < 2 {
                try await Task.sleep(nanoseconds: UInt64(attempt + 1) * 1_300_000_000)
                continue
            }
            guard (200..<300).contains(code) else {
                throw NetError.http(code, String(decoding: d.prefix(300), as: UTF8.self))
            }
            return d
        }
        throw NetError.http(429, "Rate limited, try again shortly.")
    }

    func json(_ url: URL, method: String = "GET", body: Any? = nil) async throws -> Any {
        let data = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        let d = try await request(url, method: body == nil ? method : "POST", body: data)
        if d.isEmpty { return JSON() }
        return try JSONSerialization.jsonObject(with: d, options: [.fragmentsAllowed])
    }

    func object(_ url: URL, method: String = "GET", body: Any? = nil) async throws -> JSON {
        guard let o = try await json(url, method: method, body: body) as? JSON else {
            throw NetError.invalid("Unexpected response from \(url.host ?? "node").")
        }
        return o
    }

    /// JSON-RPC 2.0
    func rpc(_ url: URL, _ method: String, _ params: [Any]) async throws -> Any {
        let res = try await object(url, method: "POST",
                                   body: ["jsonrpc": "2.0", "id": 1, "method": method, "params": params])
        if let e = res.d("error") { throw NetError.invalid(e.s("message") ?? "RPC error") }
        guard let r = res["result"] else { throw NetError.invalid("Empty RPC response.") }
        return r
    }
}

func endpointURL(_ c: Chain, _ path: String) throws -> URL {
    guard let u = URL(string: Prefs.endpoint(c) + path) else { throw NetError.badURL }
    return u
}
