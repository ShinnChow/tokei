import SwiftUI
import AppKit

/// Renders a shareable usage card image (generated, not a live window screenshot).
enum UsageShareImage {
    static let cardWidth: CGFloat = 360
    static let renderScale: CGFloat = 2

    /// Build an NSImage for the current range / visibility.
    @MainActor
    static func render(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> NSImage? {
        let lines = UsageSummaryBuilder.toolLines(
            usage: usage, range: range, visibility: visibility
        )
        let content = UsageShareCardView(
            range: range,
            lines: lines,
            updatedLine: UsageSummaryBuilder.formatUpdatedLine(updated)
        )
        .environment(\.colorScheme, .dark)

        let renderer = ImageRenderer(content: content)
        renderer.scale = renderScale
        guard let cg = renderer.cgImage else { return nil }
        let size = NSSize(width: CGFloat(cg.width) / renderScale,
                          height: CGFloat(cg.height) / renderScale)
        let image = NSImage(cgImage: cg, size: size)
        return image
    }

    /// PNG bytes for tests / disk; uses the same render path as pasteboard.
    @MainActor
    static func pngData(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> Data? {
        guard let image = render(usage: usage, range: range, visibility: visibility, updated: updated),
              let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff) else { return nil }
        return rep.representation(using: .png, properties: [:])
    }

    /// Write generated image to the general pasteboard (and PNG for broader paste targets).
    @MainActor
    @discardableResult
    static func copyToPasteboard(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> Bool {
        guard let image = render(usage: usage, range: range, visibility: visibility, updated: updated) else {
            return false
        }
        let pb = NSPasteboard.general
        pb.clearContents()
        var ok = pb.writeObjects([image])
        if let tiff = image.tiffRepresentation,
           let rep = NSBitmapImageRep(data: tiff),
           let png = rep.representation(using: .png, properties: [:]) {
            ok = pb.setData(png, forType: .png) || ok
        }
        return ok
    }
}

// MARK: - Share card UI

struct UsageShareCardView: View {
    var range: RangeKey
    var lines: [UsageSummaryBuilder.Line]
    var updatedLine: String?

    private var totalCost: Double {
        lines.compactMap(\.cost).reduce(0, +)
    }

    private var totalTokens: Int {
        lines.compactMap(\.tokens).reduce(0, +)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if lines.isEmpty {
                Text("当前范围无可分享的用量")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.tTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 20)
            } else {
                VStack(spacing: 8) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        toolRow(line)
                    }
                }
                totals
            }
            if let updatedLine {
                Text(updatedLine)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
            Text("Tokei · 知度")
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Theme.tTertiary.opacity(0.85))
        }
        .padding(18)
        .frame(width: UsageShareImage.cardWidth, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(red: 0.14, green: 0.15, blue: 0.18))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "timer")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Theme.claude)
            VStack(alignment: .leading, spacing: 2) {
                Text("Tokei 用量")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.tPrimary)
                Text(range.label)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
            }
            Spacer(minLength: 0)
        }
    }

    private func toolRow(_ line: UsageSummaryBuilder.Line) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Circle()
                    .fill(tint(for: line.name))
                    .frame(width: 7, height: 7)
                Text(line.name)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.tPrimary)
                Spacer(minLength: 0)
                if let cost = line.cost, cost > 0 {
                    Text(String(format: "$%.2f", cost))
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.tPrimary)
                }
            }
            HStack(spacing: 10) {
                if let tokens = line.tokens, tokens > 0 {
                    meta("\(Fmt.human(tokens)) tok")
                }
                if let sessions = line.sessions, sessions > 0 {
                    meta("\(sessions) 会话")
                }
                if let calls = line.calls, calls > 0 {
                    meta("\(calls) 次调用")
                }
                Spacer(minLength: 0)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.black.opacity(0.28))
        )
    }

    private var totals: some View {
        HStack {
            Text("合计")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
            Spacer()
            HStack(spacing: 8) {
                if totalCost > 0 {
                    Text(String(format: "$%.2f", totalCost))
                        .font(.system(size: 14, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.tPrimary)
                }
                if totalTokens > 0 {
                    Text("\(Fmt.human(totalTokens)) tok")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Theme.tSecondary)
                }
            }
        }
        .padding(.top, 4)
    }

    private func meta(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, design: .monospaced))
            .foregroundStyle(Theme.tTertiary)
    }

    private func tint(for name: String) -> Color {
        switch name {
        case "Claude Code": return Theme.claude
        case "Codex": return Theme.codex
        case "Gemini": return Theme.gemini
        case "Grok": return Theme.grok
        case "Qoder Desktop": return Theme.qoder
        case "QoderWork": return Theme.qoderwork
        case "Qoder CLI": return Theme.qodercli
        case "Hermes": return Theme.hermes
        case "ZCode": return Theme.zcode
        case "MiMoCode": return Theme.mimocode
        case "OpenClaw": return Theme.openclaw
        case "Pi": return Theme.pi
        case "WorkBuddy": return Theme.workbuddy
        case "OpenCode": return Theme.opencode
        case "Qwen Code": return Theme.qwencode
        default: return Theme.tTertiary
        }
    }
}
