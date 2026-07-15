import CryptoKit
import Foundation

public struct UpdateRelease: Equatable, Sendable {
    public let tag: String
    public let downloadURL: URL
    public let sha256: String

    public init(tag: String, downloadURL: URL, sha256: String) {
        self.tag = tag
        self.downloadURL = downloadURL
        self.sha256 = sha256
    }
}

public struct UpdateWorkspace: Equatable, Sendable {
    public let identifier: String
    public let rootURL: URL
    public let dmgURL: URL
    public let mountURL: URL
    public let scriptURL: URL

    public func backupURL(for appURL: URL) -> URL {
        appURL.deletingLastPathComponent().appendingPathComponent(
            "\(appURL.lastPathComponent).tokei-backup-\(identifier)"
        )
    }
}

public enum UpdateInstaller {
    public static func createWorkspace(
        in baseDirectory: URL = FileManager.default.temporaryDirectory,
        fileManager: FileManager = .default
    ) throws -> UpdateWorkspace {
        let identifier = UUID().uuidString.lowercased()
        let rootURL = baseDirectory.appendingPathComponent(
            "tokei-update-\(identifier)", isDirectory: true
        )
        try fileManager.createDirectory(
            at: rootURL,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
        return UpdateWorkspace(
            identifier: identifier,
            rootURL: rootURL,
            dmgURL: rootURL.appendingPathComponent("Tokei.dmg"),
            mountURL: rootURL.appendingPathComponent("mount", isDirectory: true),
            scriptURL: rootURL.appendingPathComponent("install.sh")
        )
    }

    public static let script = """
    #!/bin/bash
    set -u

    if [ "$#" -ne 5 ]; then
        exit 2
    fi

    DMG_PATH="$1"
    MOUNT_DIR="$2"
    APP_PATH="$3"
    WORK_DIR="$4"
    BACKUP_PATH="$5"
    MOUNTED=0
    OLD_MOVED=0

    cleanup() {
        if [ "$MOUNTED" -eq 1 ]; then
            /usr/bin/hdiutil detach "$MOUNT_DIR" -quiet >/dev/null 2>&1 || true
            MOUNTED=0
        fi
        /bin/rm -rf "$WORK_DIR"
    }

    restore() {
        if [ "$OLD_MOVED" -eq 1 ]; then
            /bin/rm -rf "$APP_PATH"
            /bin/mv "$BACKUP_PATH" "$APP_PATH" >/dev/null 2>&1 || true
            OLD_MOVED=0
        fi
    }

    fail() {
        restore
        cleanup
        /usr/bin/open "$APP_PATH" >/dev/null 2>&1 || true
        exit 1
    }

    trap fail HUP INT TERM

    /bin/sleep 1
    [ -f "$DMG_PATH" ] || fail
    [ -d "$APP_PATH" ] || fail
    /bin/mkdir -p "$MOUNT_DIR" || fail
    /usr/bin/hdiutil attach "$DMG_PATH" -nobrowse -quiet -readonly -mountpoint "$MOUNT_DIR" || fail
    MOUNTED=1
    [ -d "$MOUNT_DIR/Tokei.app" ] || fail
    [ ! -e "$BACKUP_PATH" ] || /bin/rm -rf "$BACKUP_PATH" || fail
    /bin/mv "$APP_PATH" "$BACKUP_PATH" || fail
    OLD_MOVED=1
    /bin/cp -R "$MOUNT_DIR/Tokei.app" "$APP_PATH" || fail
    /usr/bin/xattr -cr "$APP_PATH" >/dev/null 2>&1 || true
    /bin/rm -rf "$BACKUP_PATH" || fail
    OLD_MOVED=0
    if /usr/bin/hdiutil detach "$MOUNT_DIR" -quiet >/dev/null 2>&1; then
        MOUNTED=0
    fi
    /usr/bin/open "$APP_PATH" >/dev/null 2>&1 || true
    cleanup
    exit 0
    """
}

public enum ShellEscaping {
    public static func singleQuoted(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

public enum UpdateSecurity {
    private static let metadataHosts: Set<String> = [
        "api.github.com",
        "dl.lanshuagent.com",
    ]
    private static let downloadSourceHosts: Set<String> = [
        "dl.lanshuagent.com",
        "github.com",
    ]
    private static let downloadRedirectHosts: Set<String> = [
        "release-assets.githubusercontent.com",
    ]

    public static func releaseTag(from json: [String: Any]) -> String? {
        guard let raw = (json["tag_name"] ?? json["version"]) as? String else { return nil }
        let tag = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return tag.isEmpty ? nil : tag
    }

    public static func validatedRelease(from json: [String: Any]) -> UpdateRelease? {
        guard let tag = releaseTag(from: json) else { return nil }

        let urlString: String?
        let digestString: String?
        if let assets = json["assets"] as? [[String: Any]],
           let asset = assets.first(where: isDMGAsset) {
            urlString = asset["browser_download_url"] as? String
            digestString = (asset["digest"] ?? asset["sha256"]) as? String
        } else {
            urlString = (json["download_url"] ?? json["url"]) as? String
            digestString = (json["sha256"] ?? json["digest"]) as? String
        }

        guard let rawURL = urlString,
              let url = URL(string: rawURL),
              isAllowedDownloadSourceURL(url),
              url.pathExtension.lowercased() == "dmg",
              let digest = normalizedSHA256(digestString) else {
            return nil
        }
        return UpdateRelease(tag: tag, downloadURL: url, sha256: digest)
    }

    public static func isAllowedMetadataURL(_ url: URL) -> Bool {
        isAllowedHTTPSURL(url, hosts: metadataHosts)
    }

    public static func isAllowedDownloadSourceURL(_ url: URL) -> Bool {
        isAllowedHTTPSURL(url, hosts: downloadSourceHosts)
    }

    public static func isAllowedDownloadResponseURL(_ url: URL) -> Bool {
        isAllowedHTTPSURL(url, hosts: downloadSourceHosts.union(downloadRedirectHosts))
    }

    public static func normalizedSHA256(_ raw: String?) -> String? {
        guard var digest = raw?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() else {
            return nil
        }
        if digest.hasPrefix("sha256:") {
            digest.removeFirst("sha256:".count)
        }
        guard digest.utf8.count == 64,
              digest.utf8.allSatisfy({ byte in
                  (48...57).contains(byte) || (97...102).contains(byte)
              }) else {
            return nil
        }
        return digest
    }

    public static func sha256(of fileURL: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }

        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func isDMGAsset(_ asset: [String: Any]) -> Bool {
        if let name = asset["name"] as? String, name.lowercased().hasSuffix(".dmg") {
            return true
        }
        guard let rawURL = asset["browser_download_url"] as? String,
              let url = URL(string: rawURL) else {
            return false
        }
        return url.pathExtension.lowercased() == "dmg"
    }

    private static func isAllowedHTTPSURL(_ url: URL, hosts: Set<String>) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme?.lowercased() == "https",
              let host = components.host?.lowercased(),
              hosts.contains(host),
              components.user == nil,
              components.password == nil,
              components.fragment == nil,
              components.port == nil || components.port == 443 else {
            return false
        }
        return true
    }
}
