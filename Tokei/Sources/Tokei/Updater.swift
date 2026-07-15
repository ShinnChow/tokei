import Foundation
import AppKit
import TokeiUpdateSecurity

final class Updater: NSObject, ObservableObject, URLSessionDownloadDelegate {
    enum State: Equatable {
        case idle, checking, upToDate, available(String, URL, String), downloading(Double), installing, failed(String)
        static func == (lhs: State, rhs: State) -> Bool {
            switch (lhs, rhs) {
            case (.idle, .idle), (.checking, .checking), (.upToDate, .upToDate), (.installing, .installing): return true
            case (.available(let a, _, _), .available(let b, _, _)): return a == b
            case (.downloading(let a), .downloading(let b)): return a == b
            case (.failed(let a), .failed(let b)): return a == b
            default: return false
            }
        }
    }

    static let releaseTag = "v1.0.14"
    @Published var state: State = .idle

    private let apiURLs = [
        URL(string: "https://dl.lanshuagent.com/tokei/latest.json")!,
        URL(string: "https://api.github.com/repos/cclank/tokei/releases/latest")!,
    ]
    private var downloadTask: URLSessionDownloadTask?
    private var expectedSHA256: String?
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForResource = 300
        return URLSession(configuration: config, delegate: self, delegateQueue: .main)
    }()

    static let shared = Updater()

    private static func isNewer(remote: String, local: String) -> Bool {
        let parse: (String) -> [Int] = { v in
            v.trimmingCharacters(in: CharacterSet(charactersIn: "v"))
                .split(separator: ".").compactMap { Int($0) }
        }
        let r = parse(remote), l = parse(local)
        for i in 0..<max(r.count, l.count) {
            let rv = i < r.count ? r[i] : 0
            let lv = i < l.count ? l[i] : 0
            if rv > lv { return true }
            if rv < lv { return false }
        }
        return false
    }

    func checkForUpdate() {
        guard state == .idle || state == .upToDate || {
            if case .failed = state { return true }; return false
        }() else { return }
        state = .checking
        tryCheck(index: 0)
    }

    private func tryCheck(index: Int) {
        guard index < apiURLs.count else {
            state = .failed("网络不可用")
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                if case .failed = self?.state { self?.state = .idle }
            }
            return
        }
        let apiURL = apiURLs[index]
        guard UpdateSecurity.isAllowedMetadataURL(apiURL) else {
            tryCheck(index: index + 1)
            return
        }
        var req = URLRequest(url: apiURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        session.dataTask(with: req) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                guard let http = response as? HTTPURLResponse,
                      (200..<300).contains(http.statusCode),
                      let responseURL = http.url,
                      UpdateSecurity.isAllowedMetadataURL(responseURL),
                      let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let tag = UpdateSecurity.releaseTag(from: json) else {
                    self.tryCheck(index: index + 1)
                    return
                }
                if Self.isNewer(remote: tag, local: Self.releaseTag) {
                    guard let release = UpdateSecurity.validatedRelease(from: json) else {
                        self.tryCheck(index: index + 1)
                        return
                    }
                    self.state = .available(release.tag, release.downloadURL, release.sha256)
                } else {
                    self.state = .upToDate
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                        if self?.state == .upToDate { self?.state = .idle }
                    }
                }
            }
        }.resume()
    }

    func performUpdate() {
        guard case .available(_, let url, let sha256) = state,
              UpdateSecurity.isAllowedDownloadSourceURL(url) else {
            state = .failed("更新地址不受信任")
            return
        }
        expectedSHA256 = sha256
        state = .downloading(0)
        downloadTask = session.downloadTask(with: url)
        downloadTask?.resume()
    }

    // MARK: - URLSessionDownloadDelegate

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        let progress = totalBytesExpectedToWrite > 0
            ? Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
            : 0
        state = .downloading(progress)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didFinishDownloadingTo location: URL) {
        guard let finalURL = downloadTask.response?.url,
              UpdateSecurity.isAllowedDownloadResponseURL(finalURL) else {
            failDownload("更新地址不受信任")
            return
        }
        guard let expectedSHA256 = expectedSHA256 else {
            failDownload("更新包缺少校验信息")
            return
        }
        let actualSHA256: String
        do {
            actualSHA256 = try UpdateSecurity.sha256(of: location)
        } catch {
            failDownload("更新包校验失败")
            return
        }
        guard actualSHA256 == expectedSHA256 else {
            failDownload("更新包校验失败")
            return
        }

        let workspace: UpdateWorkspace
        do {
            workspace = try UpdateInstaller.createWorkspace()
        } catch {
            failDownload("创建更新目录失败")
            return
        }
        do {
            try FileManager.default.moveItem(at: location, to: workspace.dmgURL)
        } catch {
            try? FileManager.default.removeItem(at: workspace.rootURL)
            failDownload("准备更新文件失败")
            return
        }
        self.expectedSHA256 = nil
        self.downloadTask = nil
        install(workspace: workspace)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        guard let redirectURL = request.url else {
            completionHandler(nil)
            return
        }
        let isDownload = task.taskIdentifier == downloadTask?.taskIdentifier
        let isAllowed = isDownload
            ? UpdateSecurity.isAllowedDownloadResponseURL(redirectURL)
            : UpdateSecurity.isAllowedMetadataURL(redirectURL)
        if !isAllowed, isDownload {
            failDownload("更新地址不受信任")
        }
        completionHandler(isAllowed ? request : nil)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard task.taskIdentifier == downloadTask?.taskIdentifier else { return }
        if let error = error {
            expectedSHA256 = nil
            downloadTask = nil
            if case .failed = state { return }
            state = .failed(error.localizedDescription)
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                if case .failed = self?.state { self?.state = .idle }
            }
        }
    }

    private func failDownload(_ message: String) {
        expectedSHA256 = nil
        downloadTask = nil
        state = .failed(message)
    }

    // MARK: - Install

    private func install(workspace: UpdateWorkspace) {
        state = .installing
        let appURL = Bundle.main.bundleURL
        let backupURL = workspace.backupURL(for: appURL)
        do {
            try UpdateInstaller.script.write(
                to: workspace.scriptURL,
                atomically: true,
                encoding: .utf8
            )
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: workspace.scriptURL.path
            )
        } catch {
            try? FileManager.default.removeItem(at: workspace.rootURL)
            state = .failed("准备安装脚本失败")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = [
            workspace.scriptURL.path,
            workspace.dmgURL.path,
            workspace.mountURL.path,
            appURL.path,
            workspace.rootURL.path,
            backupURL.path,
        ]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
        } catch {
            try? FileManager.default.removeItem(at: workspace.rootURL)
            state = .failed("启动安装程序失败")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            NSApp.terminate(nil)
        }
    }
}
