import Charts
import SwiftUI

private enum QuotaHistoryTool: String, CaseIterable, Identifiable {
    case claude = "Claude"
    case codex = "Codex"

    var id: String { rawValue }
    var tint: Color { self == .claude ? Theme.claude : Theme.codex }
}

private enum QuotaHistorySpan: Int, CaseIterable, Identifiable {
    case hour = 1
    case sixHours = 6
    case day = 24

    var id: Int { rawValue }
    var label: String {
        switch self {
        case .hour: return "1h"
        case .sixHours: return "6h"
        case .day: return "24h"
        }
    }
    var axisStride: Int {
        switch self {
        case .hour: return 1
        case .sixHours: return 2
        case .day: return 6
        }
    }
}

private struct QuotaChartDatum: Identifiable {
    var timestamp: Date
    var remaining: Double
    var window: String
    var activity: [QuotaModelActivity]

    var id: String { "\(Int(timestamp.timeIntervalSince1970)):\(window)" }
}

private struct QuotaDropEvent: Identifiable {
    var timestamp: Date
    var durationMinutes: Int
    var window: String
    var drop: Double
    var activity: [QuotaModelActivity]

    var id: String { "\(Int(timestamp.timeIntervalSince1970)):\(window)" }
}

struct QuotaHistoryView: View {
    @ObservedObject var history: QuotaHistoryStore
    @State private var tool: QuotaHistoryTool = .claude
    @State private var span: QuotaHistorySpan = .day

    private var now: Date { Date() }
    private var start: Date { now.addingTimeInterval(TimeInterval(-span.rawValue * 60 * 60)) }
    private var recentPoints: [QuotaHistoryPoint] { history.points(since: start) }

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            controls
            Card(tint: tool.tint) {
                VStack(alignment: .leading, spacing: 12) {
                    summary
                    if chartData.isEmpty {
                        emptyState
                    } else {
                        quotaChart
                    }
                }
            }
            changesSection
            activitySection
            Text("额度曲线来自本机定时快照；模型标记来自同一分钟内本地会话 token 增量，仅表示相关活动，不等同于官方逐模型扣费归因。")
                .font(.system(size: 9.5))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var controls: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("额度轨迹")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Theme.tPrimary)
                Text("按分钟聚合 · 剩余额度")
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
            }
            Spacer()
            Picker("", selection: $tool) {
                ForEach(QuotaHistoryTool.allCases) { tool in
                    Text(tool.rawValue).tag(tool)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 145)
            .controlSize(.mini)
            Picker("", selection: $span) {
                ForEach(QuotaHistorySpan.allCases) { span in
                    Text(span.label).tag(span)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 138)
            .controlSize(.mini)
        }
    }

    private var summary: some View {
        HStack(spacing: 13) {
            ForEach(windowNames, id: \.self) { window in
                quotaSummary(
                    title: summaryTitle(for: window),
                    value: latestValue(window: window),
                    tint: seriesColor(for: window)
                )
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("采样点")
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
                Text("\(recentPoints.count)")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.tPrimary)
            }
            Spacer()
            if let largest = dropEvents.max(by: { $0.drop < $1.drop }) {
                VStack(alignment: .trailing, spacing: 3) {
                    Text("最大区间下降")
                        .font(.system(size: 9.5))
                        .foregroundStyle(Theme.tTertiary)
                    Text(String(format: "-%.1f%% / %dmin", largest.drop, largest.durationMinutes))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(seriesColor(for: largest.window))
                }
            }
        }
    }

    private func quotaSummary(title: String, value: Double?, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 9.5))
                .foregroundStyle(Theme.tTertiary)
            Text(value.map { String(format: "%.1f%%", $0) } ?? "—")
                .font(.system(size: 15, weight: .bold, design: .rounded))
                .foregroundStyle(value.map { $0 <= 15 ? Color.red : tint } ?? Theme.tTertiary)
        }
    }

    private var quotaChart: some View {
        Chart {
            ForEach(chartData) { item in
                LineMark(
                    x: .value("时间", item.timestamp),
                    y: .value("剩余额度", item.remaining),
                    series: .value("额度窗口", item.window)
                )
                .foregroundStyle(by: .value("额度窗口", item.window))
                .interpolationMethod(.stepEnd)
                .lineStyle(StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))

                let isLatest = item.id == latestDatumID(for: item.window)
                if !item.activity.isEmpty || isLatest {
                    PointMark(
                        x: .value("活动时间", item.timestamp),
                        y: .value("活动额度", item.remaining)
                    )
                    .foregroundStyle(by: .value("额度窗口", item.window))
                    .symbolSize(isLatest ? 16 : 8)
                    .opacity(isLatest ? 1 : 0.62)
                }
            }
        }
        .chartXScale(domain: start ... now)
        .chartYScale(domain: 0 ... 100)
        .chartForegroundStyleScale(
            domain: windowNames,
            range: windowColors
        )
        .chartLegend(position: .top, alignment: .trailing, spacing: 10)
        .chartXAxis {
            AxisMarks(values: .stride(by: .hour, count: span.axisStride)) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                AxisTick().foregroundStyle(Color.white.opacity(0.18))
                AxisValueLabel(format: .dateTime.hour().minute())
                    .font(.system(size: 8.5, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0, 25, 50, 75, 100]) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.08))
                AxisValueLabel {
                    if let number = value.as(Int.self) {
                        Text("\(number)%")
                    }
                }
                .font(.system(size: 8.5, design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            }
        }
        .frame(height: 235)
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 24))
                .foregroundStyle(tool.tint.opacity(0.8))
            Text("正在开始记录额度轨迹")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
            Text("Tokei 每 30 秒刷新，曲线按分钟聚合。保持应用运行后，这里会逐步出现数据。")
                .font(.system(size: 10))
                .foregroundStyle(Theme.tTertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 210)
    }

    private var changesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最近额度变化")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if dropEvents.isEmpty {
                Text("当前时间范围内还没有检测到额度下降")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(dropEvents.prefix(8))) { event in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(from: event.timestamp))
                            .font(.system(size: 9.5, design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        Text(event.window)
                            .font(.system(size: 9.5, weight: .semibold))
                            .foregroundStyle(tool.tint)
                            .frame(width: 42, alignment: .leading)
                        Text(String(format: "-%.1f%%", event.drop))
                            .font(.system(size: 10.5, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                            .frame(width: 54, alignment: .trailing)
                        Text("\(event.durationMinutes) 分钟")
                            .font(.system(size: 9.5))
                            .foregroundStyle(Theme.tTertiary)
                        activityText(event.activity)
                        Spacer()
                    }
                }
            }
        }
    }

    private var activitySection: some View {
        let events = activityEvents
        return VStack(alignment: .leading, spacing: 8) {
            Text("模型活动标记")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if events.isEmpty {
                Text("尚未检测到该工具的模型 token 增量")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(events.prefix(8)), id: \.timestamp) { point in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(from: Date(timeIntervalSince1970: TimeInterval(point.timestamp))))
                            .font(.system(size: 9.5, design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        activityText(activity(for: point))
                        Spacer()
                    }
                }
            }
        }
    }

    private func activityText(_ activity: [QuotaModelActivity]) -> some View {
        Text(activity.map { "\($0.model) +\(Fmt.human($0.tokenDelta))" }.joined(separator: " · "))
            .font(.system(size: 9.5, design: .monospaced))
            .foregroundStyle(Theme.tSecondary)
            .lineLimit(1)
    }

    private var chartData: [QuotaChartDatum] {
        recentPoints.flatMap { point -> [QuotaChartDatum] in
            let date = Date(timeIntervalSince1970: TimeInterval(point.timestamp))
            return windowNames.compactMap { window in
                value(for: window, point: point).map { remaining in
                    QuotaChartDatum(
                        timestamp: date,
                        remaining: remaining,
                        window: window,
                        activity: activity(for: point, window: window)
                    )
                }
            }
        }
    }

    private var dropEvents: [QuotaDropEvent] {
        var events: [QuotaDropEvent] = []
        for window in windowNames {
            let samples = recentPoints.compactMap { point -> (QuotaHistoryPoint, Double)? in
                value(for: window, point: point).map { (point, $0) }
            }
            for pair in zip(samples, samples.dropFirst()) {
                let previous = pair.0
                let current = pair.1
                let drop = previous.1 - current.1
                guard drop >= 0.05 else { continue }
                let minutes = max(1, (current.0.timestamp - previous.0.timestamp) / 60)
                events.append(.init(
                    timestamp: Date(timeIntervalSince1970: TimeInterval(current.0.timestamp)),
                    durationMinutes: minutes,
                    window: window,
                    drop: drop,
                    activity: activity(for: current.0, window: window)
                ))
            }
        }
        return events.sorted { $0.timestamp > $1.timestamp }
    }

    private var activityEvents: [QuotaHistoryPoint] {
        recentPoints.filter { !activity(for: $0).isEmpty }
            .sorted { $0.timestamp > $1.timestamp }
    }

    private func activity(for point: QuotaHistoryPoint) -> [QuotaModelActivity] {
        tool == .claude ? point.claudeActivity : point.codexActivity
    }

    private func activity(
        for point: QuotaHistoryPoint,
        window: String
    ) -> [QuotaModelActivity] {
        let all = activity(for: point)
        guard tool == .claude, window == "周 · Fable" else { return all }
        return all.filter { $0.model.localizedCaseInsensitiveContains("fable") }
    }

    private var windowNames: [String] {
        switch tool {
        case .claude:
            return ["5 小时", "周 · 全部", "周 · Fable"]
        case .codex:
            return ["周"]
        }
    }

    private var windowColors: [Color] {
        windowNames.map { seriesColor(for: $0) }
    }

    private func seriesColor(for window: String) -> Color {
        switch (tool, window) {
        case (.claude, "5 小时"):
            return Color(red: 1.00, green: 0.43, blue: 0.28)
        case (.claude, "周 · 全部"):
            return Color(red: 0.66, green: 0.55, blue: 1.00)
        case (.claude, "周 · Fable"):
            return Color(red: 1.00, green: 0.72, blue: 0.16)
        case (.codex, "周"):
            return Theme.codex
        default:
            return tool.tint
        }
    }

    private func value(for window: String, point: QuotaHistoryPoint) -> Double? {
        switch (tool, window) {
        case (.claude, "5 小时"):
            return point.claudeFiveHourRemaining
        case (.claude, "周 · 全部"):
            return point.claudeWeekRemaining
        case (.claude, "周 · Fable"):
            return point.claudeFableWeekRemaining
        case (.codex, "周"):
            return point.codexWeekRemaining
        default:
            return nil
        }
    }

    private func summaryTitle(for window: String) -> String {
        window == "5 小时" ? "5h 剩余" : "\(window)剩余"
    }

    private func latestValue(window: String) -> Double? {
        let values = chartData.filter { $0.window == window }
        return values.last?.remaining
    }

    private func latestDatumID(for window: String) -> String? {
        chartData.last(where: { $0.window == window })?.id
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}
