import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct QuotaHistoryStoreCheck {
    static func main() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-quota-history-\(UUID().uuidString)")
        let fileURL = directory.appendingPathComponent("quota_history.json")
        defer { try? FileManager.default.removeItem(at: directory) }

        let base = Date(timeIntervalSince1970: 1_800_000_000)
        let store = QuotaHistoryStore(fileURL: fileURL)
        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 82,
                claudeWeekRemaining: 61,
                claudeFableWeekRemaining: 17,
                codexWeekRemaining: 49,
                claudeModelTotals: ["claude-opus": 100],
                codexModelTotals: ["gpt-5": 200]
            ),
            at: base
        )
        try expect(store.points.count == 1, "first capture should create one point")
        try expect(store.points[0].claudeActivity.isEmpty, "first capture should establish a baseline")

        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 80.5,
                claudeWeekRemaining: 60.5,
                claudeFableWeekRemaining: 16.5,
                codexWeekRemaining: 48.5,
                claudeModelTotals: ["claude-opus": 130],
                codexModelTotals: ["gpt-5": 225]
            ),
            at: base.addingTimeInterval(30)
        )
        try expect(store.points.count == 1, "captures in one minute should merge")
        try expect(store.points[0].claudeFiveHourRemaining == 80.5, "same-minute quota should use latest value")
        try expect(store.points[0].claudeFableWeekRemaining == 16.5, "Fable quota should use latest value")
        try expect(store.points[0].claudeActivity == [
            QuotaModelActivity(model: "claude-opus", tokenDelta: 30),
        ], "same-minute model delta should be recorded")

        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 79,
                claudeWeekRemaining: 60,
                claudeFableWeekRemaining: 16,
                codexWeekRemaining: 48,
                claudeModelTotals: ["claude-opus": 150, "claude-sonnet": 10],
                codexModelTotals: ["gpt-5": 240]
            ),
            at: base.addingTimeInterval(65)
        )
        try expect(store.points.count == 2, "next minute should append a point")
        try expect(store.points[1].claudeActivity.map(\.model) == [
            "claude-opus", "claude-sonnet",
        ], "new and growing models should both be attributed")

        let reloaded = QuotaHistoryStore(fileURL: fileURL)
        try expect(reloaded.points == store.points, "history should survive a reload")

        reloaded.record(
            QuotaCapture(
                claudeFiveHourRemaining: 100,
                claudeWeekRemaining: 100,
                claudeFableWeekRemaining: 100,
                codexWeekRemaining: 100
            ),
            at: base.addingTimeInterval(8 * 24 * 60 * 60)
        )
        try expect(reloaded.points.count == 1, "points outside retention should be pruned")

        print("quota history store checks passed")
    }

    private static func expect(
        _ condition: @autoclosure () -> Bool,
        _ message: String
    ) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
