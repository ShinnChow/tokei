import Foundation

/// Default-on installation counts with an explicit opt-out. Kept separate from usage collection and device sync.
@MainActor
final class ActivityReporter: NSObject, URLSessionTaskDelegate {
    nonisolated static let enabledKey = "shareBasicActivity"
    static let shared = ActivityReporter()
    nonisolated static let endpoint = URL(string: "https://tokei-ops.lanshuagent.com/v1/heartbeat")!

    struct State: Codable {
        var installationID: UUID
        var lastSuccessfulDay: String?
        var lastAttemptAt: Date?
    }

    struct Payload: Codable {
        let installation_id: String
        let app_version: String
        let os_name: String
        let os_version: String
    }

    private let defaults: UserDefaults
    private let stateURL: URL
    private let configuration: URLSessionConfiguration
    private let endpoint: URL
    private let clock: () -> Date
    private var hasAttemptedReport = false
    private var activeTask: URLSessionDataTask?
    private var activeRequestID: UUID?
    private lazy var session = URLSession(configuration: configuration, delegate: self, delegateQueue: .main)

    init(defaults: UserDefaults = .standard, stateURL: URL? = nil,
         endpoint: URL = ActivityReporter.endpoint,
         configuration: URLSessionConfiguration = .ephemeral,
         clock: @escaping () -> Date = Date.init) {
        self.defaults = defaults
        // Registration supplies a default without overwriting a saved opt-out.
        defaults.register(defaults: [Self.enabledKey: true])
        self.stateURL = stateURL ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Tokei/Telemetry/state.json")
        self.endpoint = endpoint
        self.configuration = configuration
        self.clock = clock
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 15
        super.init()
    }

    static func utcDay(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    func preferencesChanged() {
        if !defaults.bool(forKey: Self.enabledKey) {
            activeRequestID = nil
            activeTask?.cancel()
            activeTask = nil
            return
        }
    }

    func reportLaunchIfNeeded(appVersion: String) {
        guard defaults.bool(forKey: Self.enabledKey), !hasAttemptedReport,
              endpoint.scheme == "https" else { return }
        hasAttemptedReport = true
        let now = clock()
        let day = Self.utcDay(now)
        do {
            var state: State
            if FileManager.default.fileExists(atPath: stateURL.path) {
                // A corrupt/unreadable file must not silently create another installation.
                state = try JSONDecoder().decode(State.self, from: Data(contentsOf: stateURL))
            } else {
                state = State(installationID: UUID())
            }
            let os = ProcessInfo.processInfo.operatingSystemVersion
            let version = appVersion.hasPrefix("v") ? String(appVersion.dropFirst()) : appVersion
            let payload = Payload(installation_id: state.installationID.uuidString.lowercased(),
                                  app_version: version, os_name: "macOS",
                                  os_version: "\(os.majorVersion).\(os.minorVersion)")
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("Tokei/\(version)", forHTTPHeaderField: "User-Agent")
            request.httpBody = try JSONEncoder().encode(payload)
            state.lastAttemptAt = now
            try save(state)
            let sentState = state
            let requestID = UUID()
            activeRequestID = requestID
            let task = session.dataTask(with: request) { [weak self] _, response, error in
                Task { @MainActor in
                    guard let self, self.activeRequestID == requestID else { return }
                    self.activeRequestID = nil
                    self.activeTask = nil
                    guard self.defaults.bool(forKey: Self.enabledKey), error == nil,
                          let response = response as? HTTPURLResponse,
                          response.statusCode == 204, response.url == self.endpoint else { return }
                    var updated = sentState
                    updated.lastSuccessfulDay = day
                    try? self.save(updated)
                }
            }
            activeTask = task
            task.resume()
        } catch {
            // Statistics must never interrupt the app or log installation identifiers.
        }
    }

    private func save(_ state: State) throws {
        var directory = stateURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        try JSONEncoder().encode(state).write(to: stateURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: stateURL.path)
    }

    // Never forward the installation ID to a redirect target.
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                willPerformHTTPRedirection response: HTTPURLResponse,
                                newRequest request: URLRequest,
                                completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
