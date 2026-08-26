import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct ProviderQuotaModelCheck {
    static func main() throws {
        if CommandLine.arguments.contains("--usage-stdin") {
            let data = FileHandle.standardInput.readDataToEndOfFile()
            let usage = try JSONDecoder().decode(Usage.self, from: data)
            try expect(!usage.cursor.available, "disabled Cursor should decode as unavailable")
            try expect(!usage.zed.available, "disabled Zed should decode as unavailable")
            try expect(!usage.sub2api.available, "disabled Sub2API should decode as unavailable")
            try expect(!usage.zai.available, "disabled z.ai should decode as unavailable")
            print("provider quota usage decode passed")
            return
        }
        let data = Data("""
        {
          "available": true,
          "plan": "Pro",
          "account": "user@example.com",
          "windows": [
            {
              "id": "weekly",
              "title": "周额度",
              "used_pct": 35.5,
              "reset": 1788220800,
              "window_minutes": 10080,
              "detail": "35.5 / 100",
              "usage_known": true
            }
          ],
          "details": [
            {"label": "余额", "value": "$42.50", "secondary": "USD"}
          ],
          "source": "fixture",
          "updated": 1787702400,
          "stale": false
        }
        """.utf8)
        let quota = try JSONDecoder().decode(ProviderQuotaStat.self, from: data)
        try expect(quota.available, "available")
        try expect(quota.plan == "Pro", "plan")
        try expect(quota.windows.first?.used_pct == 35.5, "window percent")
        try expect(quota.windows.first?.window_minutes == 10080, "window minutes")
        try expect(quota.details.first?.secondary == "USD", "detail secondary")

        let empty = try JSONDecoder().decode(ProviderQuotaStat.self, from: Data("{}".utf8))
        try expect(!empty.available, "empty availability")
        try expect(empty.windows.isEmpty, "empty windows")
        try expect(empty.details.isEmpty, "empty details")
        print("provider quota model checks passed")
    }
}
