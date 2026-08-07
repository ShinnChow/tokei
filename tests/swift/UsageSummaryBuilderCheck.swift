import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct UsageSummaryBuilderCheck {
    static func main() throws {
        let usage = try decodeFixture(Self.fixtureJSON)
        let allVisible = UsageToolVisibility.allVisible

        let todayText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: allVisible, updated: "12:34"
        )
        try expect(todayText.contains("Tokei 用量 · 今日"), "period label missing: \(todayText)")
        try expect(todayText.contains("Claude Code"), "claude line missing: \(todayText)")
        try expect(todayText.contains("$1.25"), "claude cost missing: \(todayText)")
        try expect(todayText.contains("Codex"), "codex line missing: \(todayText)")
        try expect(todayText.contains("$0.50"), "codex cost missing: \(todayText)")
        try expect(todayText.contains("合计"), "total line missing: \(todayText)")
        // Claude 1.25 + Codex 0.50 + Gemini 0.10
        try expect(todayText.contains("$1.85"), "total cost wrong: \(todayText)")
        try expect(todayText.contains("更新于 12:34"), "updated missing: \(todayText)")
        try expect(!todayText.contains("更新于 更新"), "must not double-prefix bare time: \(todayText)")
        try expect(todayText.contains("Gemini"), "gemini should appear when visible: \(todayText)")
        try expect(todayText.contains("$0.10") || todayText.contains("$0.1"),
                   "gemini cost missing: \(todayText)")

        // Store path uses lastUpdated = "更新 HH:mm:ss" (main.swift); strip, don't nest.
        let storeStampText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: allVisible, updated: "更新 21:51:18"
        )
        try expect(storeStampText.contains("更新于 21:51:18"),
                   "store stamp should normalize: \(storeStampText)")
        try expect(!storeStampText.contains("更新于 更新"),
                   "must not double-prefix store lastUpdated: \(storeStampText)")
        try expect(UsageSummaryBuilder.formatUpdatedLine("更新 21:51:18") == "更新于 21:51:18",
                   "formatUpdatedLine store stamp")
        try expect(UsageSummaryBuilder.formatUpdatedLine("更新于 09:00") == "更新于 09:00",
                   "formatUpdatedLine already-prefixed")
        try expect(UsageSummaryBuilder.formatUpdatedLine("加载中…") == nil,
                   "loading stamp omitted")

        var hideGemini = allVisible
        hideGemini.gemini = false
        let hiddenText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: hideGemini, updated: nil
        )
        try expect(!hiddenText.contains("Gemini"),
                   "hidden gemini must be omitted: \(hiddenText)")
        try expect(hiddenText.contains("Claude Code"), "claude still required: \(hiddenText)")
        try expect(hiddenText.contains("Codex"), "codex still required: \(hiddenText)")
        try expect(hiddenText.contains("$1.75"),
                   "total without gemini should be $1.75: \(hiddenText)")

        // Empty tools (OpenCode with zeros) must not dump noise.
        try expect(!todayText.contains("OpenCode"),
                   "zero-usage tools should be omitted: \(todayText)")

        // Week range uses week numbers from fixture.
        let weekText = UsageSummaryBuilder.text(
            usage: usage, range: .week, visibility: allVisible, updated: nil
        )
        try expect(weekText.contains("Tokei 用量 · 本周"), "week label: \(weekText)")
        try expect(weekText.contains("$3.00"), "week claude cost: \(weekText)")

        let lines = UsageSummaryBuilder.toolLines(
            usage: usage, range: .today, visibility: hideGemini
        )
        try expect(lines.map(\.name) == ["Claude Code", "Codex"],
                   "tool order/names: \(lines.map(\.name))")
        try expect(lines[0].cost == 1.25, "claude cost value")
        try expect(lines[0].tokens == 1350, "claude tokens 1000+200+100+50")
        try expect(lines[1].cost == 0.50, "codex cost value")
        try expect(lines[1].tokens == 350, "codex tokens 100+50+200")

        print("usage summary builder checks passed")
    }

    private static func decodeFixture(_ json: String) throws -> Usage {
        let data = Data(json.utf8)
        do {
            return try JSONDecoder().decode(Usage.self, from: data)
        } catch {
            throw TestFailure.assertion("fixture decode failed: \(error)")
        }
    }

    /// Minimal Usage JSON: today has Claude+Codex+Gemini; week has Claude only; rest empty.
    private static let fixtureJSON = """
    {
      "claude": {
        "ranges": {
          "today": {"hit": 40, "in": 1000, "out": 200, "cr": 100, "cw": 50, "cost": 1.25, "sessions": 2, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 40, "in": 3000, "out": 600, "cr": 300, "cw": 100, "cost": 3.0, "sessions": 5, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []}
        },
        "session_name": "demo",
        "session_total": 2
      },
      "codex": {
        "ranges": {
          "today": {"hit": 20, "in": 100, "cached": 50, "out": 200, "reason": 10, "cost": 0.5, "sessions": 1, "models": []},
          "yesterday": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "gemini": {
        "ranges": {
          "today": {"hit": 10, "in": 80, "out": 20, "cached": 10, "thoughts": 5, "cost": 0.1, "sessions": 1, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "grok": {
        "ranges": {
          "today": {"tokens": 0, "sessions": 0},
          "yesterday": {"tokens": 0},
          "week": {"tokens": 0},
          "last_week": {"tokens": 0},
          "month": {"tokens": 0},
          "year": {"tokens": 0}
        }
      },
      "hermes": {
        "ranges": {
          "today": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "openclaw": {
        "ranges": {
          "today": {"tasks": 0, "completed": 0, "failed": 0, "hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "week": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "last_week": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "month": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "year": {"tasks": 0, "completed": 0, "failed": 0, "models": []}
        }
      },
      "opencode": {
        "ranges": {
          "today": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
      }
    }
    """
}
