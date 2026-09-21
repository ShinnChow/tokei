import Foundation

final class MockURLProtocol: URLProtocol {
    static var requests: [URLRequest] = []
    static var status = 204
    static var hold = false
    static var stopped = false
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requests.append(request)
        if Self.hold { return }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { Self.stopped = true }
}

@main struct ActivityReporterCheck {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let suite = "tokei.activity.test." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let stateURL = root.appendingPathComponent("Telemetry/state.json")
        var now = Date(timeIntervalSince1970: 1_789_862_400) // UTC midnight
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        defaults.set(false, forKey: ActivityReporter.enabledKey)
        let reporter = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        func settle() async { try? await Task.sleep(nanoseconds: 100_000_000) }
        func state() throws -> ActivityReporter.State { try JSONDecoder().decode(ActivityReporter.State.self, from: Data(contentsOf: stateURL)) }

        reporter.reportLaunchIfNeeded(appVersion: "v1.0.39")
        await settle()
        precondition(MockURLProtocol.requests.isEmpty && !FileManager.default.fileExists(atPath: stateURL.path), "a saved opt-out must survive initialization without creating an ID or sending")

        defaults.removeObject(forKey: ActivityReporter.enabledKey)
        precondition(defaults.bool(forKey: ActivityReporter.enabledKey), "unset preference must default to enabled")
        reporter.reportLaunchIfNeeded(appVersion: "v1.0.39")
        reporter.reportLaunchIfNeeded(appVersion: "v1.0.39")
        await settle()
        precondition(MockURLProtocol.requests.count == 1, "concurrent calls must not duplicate")
        let first = try state()
        precondition(first.lastSuccessfulDay == ActivityReporter.utcDay(now))
        let request = MockURLProtocol.requests[0]
        let body: Data
        if let data = request.httpBody { body = data }
        else {
            let stream = request.httpBodyStream!; stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 2048)
            let count = stream.read(&bytes, maxLength: bytes.count)
            body = Data(bytes.prefix(count))
        }
        let payload = try JSONSerialization.jsonObject(with: body) as! [String: String]
        precondition(Set(payload.keys) == Set(["installation_id", "app_version", "os_name", "os_version"]))
        precondition(payload["app_version"] == "1.0.39" && payload["os_name"] == "macOS")
        precondition(payload["os_version"]!.split(separator: ".").count == 2)
        precondition(request.value(forHTTPHeaderField: "Authorization") == nil && request.value(forHTTPHeaderField: "Cookie") == nil)
        let attributes = try FileManager.default.attributesOfItem(atPath: stateURL.path)
        precondition((attributes[.posixPermissions] as! NSNumber).intValue == 0o600)

        now = now.addingTimeInterval(86400)
        reporter.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 1, "same run must not report again even on another day")

        let restarted = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        restarted.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 2, "a new launch reports again")
        let restartedState = try state()
        precondition(restartedState.installationID == first.installationID, "stable ID across launches")

        MockURLProtocol.status = 503
        let failed = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        failed.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 3, "same-day launch must not be blocked by old daily state")
        now = now.addingTimeInterval(86400)
        failed.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 3, "failure is not retried in the same run")
        let failedState = try state()
        precondition(failedState.lastSuccessfulDay == restartedState.lastSuccessfulDay)

        MockURLProtocol.status = 204
        MockURLProtocol.hold = true
        let held = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        held.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 4)
        defaults.set(false, forKey: ActivityReporter.enabledKey)
        held.preferencesChanged()
        await settle()
        precondition(MockURLProtocol.stopped, "disable cancels in-flight request")
        let optedOut = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        optedOut.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 4, "saved opt-out survives another launch")
        defaults.set(true, forKey: ActivityReporter.enabledKey)
        held.preferencesChanged()
        held.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 4, "re-enabling cannot send a second report in this run")

        var redirectAllowed = true
        restarted.urlSession(URLSession.shared, task: URLSession.shared.dataTask(with: ActivityReporter.endpoint),
                             willPerformHTTPRedirection: HTTPURLResponse(url: ActivityReporter.endpoint, statusCode: 302, httpVersion: nil, headerFields: nil)!,
                             newRequest: URLRequest(url: URL(string: "https://other.example")!)) { request in redirectAllowed = request != nil }
        precondition(!redirectAllowed)
        defaults.set(true, forKey: ActivityReporter.enabledKey)
        try Data("corrupt".utf8).write(to: stateURL)
        let corrupt = ActivityReporter(defaults: defaults, stateURL: stateURL, configuration: config, clock: { now })
        corrupt.reportLaunchIfNeeded(appVersion: "v1.0.40")
        await settle()
        precondition(MockURLProtocol.requests.count == 4, "corrupt state must not create a fresh identity")
        print("Activity reporter checks passed")
    }
}
