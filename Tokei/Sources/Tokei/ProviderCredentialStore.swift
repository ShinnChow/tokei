import Foundation
import Darwin
import LocalAuthentication
import Security

enum ProviderSecret: String {
    case sub2api
    case zai
}

enum ProviderCredentialStore {
    private static let service = "com.cclank.tokei.provider-api-key"

    static func token(for provider: ProviderSecret) -> String? {
        var query = baseQuery(for: provider)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        applyNoUI(to: &query)
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        return value
    }

    @discardableResult
    static func setToken(_ token: String, for provider: ProviderSecret) -> Bool {
        let value = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let query = baseQuery(for: provider)
        if value.isEmpty {
            let status = SecItemDelete(query as CFDictionary)
            return status == errSecSuccess || status == errSecItemNotFound
        }
        let data = Data(value.utf8)
        let update = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }

    static func environmentOverrides() -> [String: String] {
        var result: [String: String] = [:]
        if let token = token(for: .sub2api) {
            result["SUB2API_API_KEY"] = token
        }
        if let token = token(for: .zai) {
            result["Z_AI_API_KEY"] = token
        }
        if let credentials = zedCredentials() {
            result["TOKEI_ZED_USER_ID"] = credentials.userID
            result["TOKEI_ZED_ACCESS_TOKEN"] = credentials.accessToken
        }
        return result
    }

    private static func baseQuery(for provider: ProviderSecret) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: provider.rawValue,
        ]
    }

    private struct ZedSettings: Decodable {
        var credentialsURL: String?
        var serverURL: String?

        enum CodingKeys: String, CodingKey {
            case credentialsURL = "credentials_url"
            case serverURL = "server_url"
        }
    }

    private static func zedCredentials() -> (userID: String, accessToken: String)? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/zed/settings.json")
        let settings = (try? Data(contentsOf: url))
            .flatMap { try? JSONDecoder().decode(ZedSettings.self, from: $0) }
        let credentialsURL = settings?.credentialsURL?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let serverURL = settings?.serverURL?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let serviceURL = [credentialsURL, serverURL, "https://zed.dev"]
            .compactMap { value -> String? in
                guard let value, !value.isEmpty else { return nil }
                return value
            }
            .first ?? "https://zed.dev"

        if let credentials = queryZedCredentials(
            itemClass: kSecClassInternetPassword, attribute: kSecAttrServer, value: serviceURL
        ) {
            return credentials
        }
        return queryZedCredentials(
            itemClass: kSecClassGenericPassword, attribute: kSecAttrService, value: serviceURL
        )
    }

    private static func queryZedCredentials(
        itemClass: CFTypeRef,
        attribute: CFString,
        value: String
    ) -> (userID: String, accessToken: String)? {
        var query: [String: Any] = [
            kSecClass as String: itemClass,
            attribute as String: value,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnAttributes as String: true,
            kSecReturnData as String: true,
        ]
        applyNoUI(to: &query)
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let item = result as? [String: Any],
              let userID = item[kSecAttrAccount as String] as? String,
              let data = item[kSecValueData as String] as? Data,
              let accessToken = String(data: data, encoding: .utf8),
              !userID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !accessToken.isEmpty else { return nil }
        return (userID, accessToken)
    }

    private static let uiFailPolicy: String = {
        let path = "/System/Library/Frameworks/Security.framework/Security"
        guard let handle = dlopen(path, RTLD_NOW) else { return "u_AuthUIF" }
        defer { dlclose(handle) }
        guard let symbol = dlsym(handle, "kSecUseAuthenticationUIFail") else {
            return "u_AuthUIF"
        }
        return symbol.assumingMemoryBound(to: CFString?.self).pointee as String? ?? "u_AuthUIF"
    }()

    private static func applyNoUI(to query: inout [String: Any]) {
        let context = LAContext()
        context.interactionNotAllowed = true
        query[kSecUseAuthenticationContext as String] = context
        query[kSecUseAuthenticationUI as String] = uiFailPolicy as CFString
    }
}
