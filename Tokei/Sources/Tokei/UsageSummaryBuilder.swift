import Foundation

/// Which tool cards the user has enabled in settings (matches `@AppStorage("show…")` flags).
struct UsageToolVisibility: Equatable {
    var claude = true
    var codex = true
    var gemini = true
    var grok = true
    var qoder = true
    var qoderwork = true
    var qodercli = true
    var hermes = true
    var zcode = true
    var mimocode = true
    var openclaw = true
    var pi = true
    var workbuddy = true
    var opencode = true
    var qwencode = true

    static let allVisible = UsageToolVisibility()
}

/// Pure text builder for copying the current-period usage summary.
/// Keeps pasteboard/UI out of the unit under test.
enum UsageSummaryBuilder {
    struct Line: Equatable {
        var name: String
        var cost: Double?
        var tokens: Int?
        var sessions: Int?
        var calls: Int?
        var extra: String?

        var isEmpty: Bool {
            let tok = tokens ?? 0
            let ses = sessions ?? 0
            let cal = calls ?? 0
            let cst = cost ?? 0
            return tok <= 0 && ses <= 0 && cal <= 0 && cst <= 0 && (extra == nil || extra?.isEmpty == true)
        }
    }

    /// Human-readable plain-text summary for the selected range and visible tools.
    static func text(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> String {
        let lines = toolLines(usage: usage, range: range, visibility: visibility)
        var out: [String] = ["Tokei 用量 · \(range.label)"]
        if lines.isEmpty {
            out.append("（当前范围无可复制的用量）")
        } else {
            for line in lines {
                out.append(formatLine(line))
            }
            let totalCost = lines.compactMap(\.cost).reduce(0, +)
            let totalTokens = lines.compactMap(\.tokens).reduce(0, +)
            var totalParts: [String] = []
            if totalCost > 0 {
                totalParts.append(String(format: "$%.2f", totalCost))
            }
            if totalTokens > 0 {
                totalParts.append("\(Fmt.human(totalTokens)) tok")
            }
            if !totalParts.isEmpty {
                out.append("合计  " + totalParts.joined(separator: " · "))
            }
        }
        if let line = formatUpdatedLine(updated) {
            out.append(line)
        }
        return out.joined(separator: "\n")
    }

    /// Normalize store timestamps like `"更新 HH:mm:ss"` so we never emit `"更新于 更新 …"`.
    static func formatUpdatedLine(_ updated: String?) -> String? {
        guard let updated else { return nil }
        let trimmed = updated.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed == "加载中…" || trimmed.hasPrefix("加载中")
            || trimmed == "加载失败" || trimmed == "预览" {
            return nil
        }
        var body = trimmed
        if body.hasPrefix("更新于") {
            body = String(body.dropFirst(3)).trimmingCharacters(in: .whitespaces)
        } else if body.hasPrefix("更新") {
            body = String(body.dropFirst(2)).trimmingCharacters(in: .whitespaces)
        }
        guard !body.isEmpty else { return nil }
        return "更新于 \(body)"
    }

    static func toolLines(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility
    ) -> [Line] {
        var lines: [Line] = []

        if visibility.claude {
            let r = usage.claude.ranges.get(range)
            let tokens = r.in + r.out + r.cr + r.cw
            let line = Line(name: "Claude Code", cost: r.cost, tokens: tokens,
                            sessions: r.sessions, calls: nil, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.codex {
            let r = usage.codex.ranges.get(range)
            let tokens = r.in + r.cached + r.out
            let line = Line(name: "Codex", cost: r.cost, tokens: tokens,
                            sessions: r.sessions, calls: nil, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.gemini {
            let r = usage.gemini.ranges.get(range)
            let tokens = r.in + r.cached + r.out + r.thoughts
            let line = Line(name: "Gemini", cost: r.cost, tokens: tokens,
                            sessions: r.sessions, calls: nil, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.grok {
            let r = usage.grok.ranges.get(range)
            let tokens = r.usage_available
                ? (r.in + r.out + r.cr + r.reason)
                : r.tokens
            let sessions = max(r.sessions, r.usage_sessions)
            let line = Line(name: "Grok", cost: r.cost > 0 ? r.cost : nil, tokens: tokens,
                            sessions: sessions, calls: r.usage_calls > 0 ? r.usage_calls : nil,
                            extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qoder {
            let r = usage.qoder.ranges.get(range)
            let tokens = r.in + r.cached + r.out
            let line = Line(name: "Qoder Desktop", cost: nil, tokens: tokens,
                            sessions: r.sessions, calls: r.calls, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qoderwork {
            let r = usage.qoderwork.ranges.get(range)
            let line = Line(name: "QoderWork", cost: nil, tokens: r.in + r.out,
                            sessions: r.sessions, calls: r.calls, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qodercli {
            let r = usage.qodercli.ranges.get(range)
            let line = Line(name: "Qoder CLI", cost: nil, tokens: nil,
                            sessions: r.sessions, calls: r.calls, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.hermes {
            let r = usage.hermes.ranges.get(range)
            let tokens = r.in + r.out + r.cr + r.cw + r.reason
            let line = Line(name: "Hermes", cost: r.cost, tokens: tokens,
                            sessions: r.sessions, calls: nil, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.zcode {
            appendTokenTool(&lines, name: "ZCode", range: usage.zcode.ranges.get(range))
        }
        if visibility.mimocode {
            appendTokenTool(&lines, name: "MiMoCode", range: usage.mimocode.ranges.get(range))
        }
        if visibility.openclaw {
            let r = usage.openclaw.ranges.get(range)
            let tokens = r.in + r.out + r.cr + r.cw
            let line = Line(name: "OpenClaw", cost: r.cost, tokens: tokens,
                            sessions: r.sessions, calls: r.tasks > 0 ? r.tasks : nil, extra: nil)
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.pi {
            appendTokenTool(&lines, name: "Pi", range: usage.pi.ranges.get(range))
        }
        if visibility.workbuddy {
            appendTokenTool(&lines, name: "WorkBuddy", range: usage.workbuddy.ranges.get(range))
        }
        if visibility.opencode {
            appendTokenTool(&lines, name: "OpenCode", range: usage.opencode.ranges.get(range))
        }
        if visibility.qwencode {
            appendTokenTool(&lines, name: "Qwen Code", range: usage.qwencode.ranges.get(range))
        }
        return lines
    }

    private static func appendTokenTool(_ lines: inout [Line], name: String, range r: TokenUsageRange) {
        let tokens = r.in + r.out + r.cr + r.cw + r.reason
        let line = Line(name: name, cost: r.cost, tokens: tokens,
                        sessions: r.sessions, calls: nil, extra: nil)
        if !line.isEmpty { lines.append(line) }
    }

    private static func formatLine(_ line: Line) -> String {
        var parts: [String] = []
        if let cost = line.cost, cost > 0 {
            parts.append(String(format: "$%.2f", cost))
        }
        if let tokens = line.tokens, tokens > 0 {
            parts.append("\(Fmt.human(tokens)) tok")
        }
        if let sessions = line.sessions, sessions > 0 {
            parts.append("\(sessions) 会话")
        }
        if let calls = line.calls, calls > 0 {
            parts.append("\(calls) 次调用")
        }
        if let extra = line.extra, !extra.isEmpty {
            parts.append(extra)
        }
        if parts.isEmpty {
            return line.name
        }
        return "\(line.name)  " + parts.joined(separator: " · ")
    }
}
