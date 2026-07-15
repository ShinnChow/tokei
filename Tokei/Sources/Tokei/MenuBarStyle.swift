import AppKit
import SwiftUI

enum MenuBarStyle: String, CaseIterable, Identifiable {
    case system
    case color
    case symbols
    case dots
    case compact
    case artistic
    case palm

    static let defaultsKey = "menuBarStyle"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "经典白"
        case .color: return "彩色"
        case .symbols: return "刻度"
        case .dots: return "圆点"
        case .compact: return "数字"
        case .artistic: return "星轨"
        case .palm: return "椰影"
        }
    }

    static var current: MenuBarStyle {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return .system }
        return MenuBarStyle(rawValue: raw) ?? .system
    }
}

enum MenuBarDensity: String, CaseIterable, Identifiable {
    case full
    case lowest
    case icon

    static let defaultsKey = "menuBarDensity"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .full: return "双额度"
        case .lowest: return "单额度"
        case .icon: return "仅图标"
        }
    }

    static var current: MenuBarDensity {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return .full }
        return MenuBarDensity(rawValue: raw) ?? .full
    }
}

enum MenuBarMetricKind {
    case claude
    case codex
    case total
}

struct MenuBarMetric {
    var kind: MenuBarMetricKind
    var value: String
    var remaining: Double? = nil
}

enum MenuBarArtwork {
    private static let signatureInk = NSColor(red: 0.15, green: 0.08, blue: 0.18, alpha: 1)
    private static let signatureRose = NSColor(red: 0.91, green: 0.29, blue: 0.43, alpha: 1)
    private static let signatureStem = NSColor(red: 0.96, green: 0.68, blue: 0.22, alpha: 1)
    private static let signatureJade = NSColor(red: 0.16, green: 0.72, blue: 0.58, alpha: 1)
    private static let signatureActive = NSColor(red: 0.98, green: 0.93, blue: 0.82, alpha: 1)
    private static let palmInk = NSColor(red: 0.03, green: 0.15, blue: 0.13, alpha: 1)
    private static let palmJade = NSColor(red: 0.39, green: 0.90, blue: 0.65, alpha: 1)
    private static let palmTeal = NSColor(red: 0.13, green: 0.72, blue: 0.59, alpha: 1)
    private static let palmGold = NSColor(red: 0.99, green: 0.72, blue: 0.27, alpha: 1)
    private static let palmCopper = NSColor(red: 0.95, green: 0.41, blue: 0.31, alpha: 1)

    static func brand(color: NSColor? = nil, active: Bool = false) -> NSImage {
        ribbonT(
            ink: color ?? .black,
            crossbarColors: [color ?? .black],
            stem: color ?? .black,
            activeColor: color ?? .black,
            active: active,
            layered: false,
            template: color == nil
        )
    }

    static func signature(active: Bool = false) -> NSImage {
        ribbonT(
            ink: signatureInk,
            crossbarColors: [signatureRose, signatureStem, signatureJade],
            stem: signatureStem,
            activeColor: signatureActive,
            active: active,
            layered: true,
            template: false
        )
    }

    private static func ribbonT(ink: NSColor, crossbarColors: [NSColor], stem: NSColor,
                                activeColor: NSColor,
                                active: Bool, layered: Bool, template: Bool) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)

            context.saveGState()
            context.translateBy(x: 9, y: 9)
            context.scaleBy(x: 1.18, y: 1.18)
            context.translateBy(x: -9, y: -9)

            func drawStroke(_ path: CGPath, color: NSColor) {
                if layered {
                    context.setStrokeColor(ink.cgColor)
                    context.setLineWidth(3.55)
                    context.addPath(path)
                    context.strokePath()
                }
                context.setStrokeColor(color.cgColor)
                context.setLineWidth(layered ? 2.0 : 2.2)
                context.addPath(path)
                context.strokePath()
            }

            let crossbarPath = CGMutablePath()
            crossbarPath.move(to: CGPoint(x: 3.85, y: 12.55))
            crossbarPath.addCurve(to: CGPoint(x: 14.15, y: 12.55),
                                  control1: CGPoint(x: 6.0, y: 15.15),
                                  control2: CGPoint(x: 12.0, y: 15.15))
            if layered {
                context.setStrokeColor(ink.cgColor)
                context.setLineWidth(3.55)
                context.addPath(crossbarPath)
                context.strokePath()

                context.saveGState()
                context.setLineWidth(2.0)
                context.addPath(crossbarPath)
                context.replacePathWithStrokedPath()
                context.clip()
                let gradient = CGGradient(
                    colorsSpace: CGColorSpaceCreateDeviceRGB(),
                    colors: crossbarColors.map(\.cgColor) as CFArray,
                    locations: [0, 0.5, 1]
                )
                if let gradient {
                    context.drawLinearGradient(
                        gradient,
                        start: CGPoint(x: 3.85, y: 12.55),
                        end: CGPoint(x: 14.15, y: 12.55),
                        options: []
                    )
                }
                context.restoreGState()
            } else if let crossbarColor = crossbarColors.first {
                drawStroke(crossbarPath, color: crossbarColor)
            }

            let stemPath = CGMutablePath()
            stemPath.move(to: CGPoint(x: 9.15, y: 13.65))
            stemPath.addCurve(to: CGPoint(x: 8.65, y: 5.3),
                              control1: CGPoint(x: 8.65, y: 10.8),
                              control2: CGPoint(x: 9.35, y: 7.35))
            drawStroke(stemPath, color: stem)
            context.restoreGState()

            if active {
                context.setFillColor(activeColor.cgColor)
                context.fillEllipse(in: CGRect(x: 14.0, y: 1.8, width: 2.2, height: 2.2))
            }
            return true
        }
        image.isTemplate = template
        return image
    }

    static func gauge(remaining: Double?, color: NSColor? = nil, active: Bool = false,
                      size: CGFloat = 11) -> NSImage {
        let drawColor = color ?? .black
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            let scale = size / 11
            context.setLineWidth(1.45 * scale)

            let center = CGPoint(x: size / 2, y: size / 2)
            let radius: CGFloat = 4.0 * scale
            context.setStrokeColor(drawColor.withAlphaComponent(0.22).cgColor)
            context.addEllipse(in: CGRect(x: center.x - radius, y: center.y - radius,
                                          width: radius * 2, height: radius * 2))
            context.strokePath()

            let progress = min(max((remaining ?? 100) / 100, 0.04), 1)
            context.setStrokeColor(drawColor.cgColor)
            context.addArc(center: center, radius: radius,
                           startAngle: .pi / 2,
                           endAngle: .pi / 2 - CGFloat(progress) * 2 * .pi,
                           clockwise: true)
            context.strokePath()

            if active {
                context.setFillColor(drawColor.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 0.8 * scale,
                                               y: center.y - 0.8 * scale,
                                               width: 1.6 * scale, height: 1.6 * scale))
            }
            return true
        }
        image.isTemplate = color == nil
        return image
    }

    static func starTrail(active: Bool = false) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)
            context.setStrokeColor(NSColor.black.cgColor)
            context.setFillColor(NSColor.black.cgColor)
            context.setLineWidth(1.35)

            context.move(to: CGPoint(x: 2.55, y: 10.65))
            context.addCurve(to: CGPoint(x: 14.75, y: 5.35),
                             control1: CGPoint(x: 3.35, y: 4.15),
                             control2: CGPoint(x: 10.85, y: 1.55))
            context.strokePath()

            context.move(to: CGPoint(x: 15.55, y: 7.25))
            context.addCurve(to: CGPoint(x: 2.85, y: 11.85),
                             control1: CGPoint(x: 15.35, y: 13.35),
                             control2: CGPoint(x: 7.75, y: 16.45))
            context.strokePath()

            let star = CGMutablePath()
            star.move(to: CGPoint(x: 9, y: 4.7))
            star.addCurve(to: CGPoint(x: 13.3, y: 9),
                          control1: CGPoint(x: 9.4, y: 7.35),
                          control2: CGPoint(x: 10.65, y: 8.6))
            star.addCurve(to: CGPoint(x: 9, y: 13.3),
                          control1: CGPoint(x: 10.65, y: 9.4),
                          control2: CGPoint(x: 9.4, y: 10.65))
            star.addCurve(to: CGPoint(x: 4.7, y: 9),
                          control1: CGPoint(x: 8.6, y: 10.65),
                          control2: CGPoint(x: 7.35, y: 9.4))
            star.addCurve(to: CGPoint(x: 9, y: 4.7),
                          control1: CGPoint(x: 7.35, y: 8.6),
                          control2: CGPoint(x: 8.6, y: 7.35))
            star.closeSubpath()
            context.addPath(star)
            context.fillPath()

            let satelliteSize: CGFloat = active ? 2.9 : 2.25
            context.fillEllipse(in: CGRect(x: 15.05 - satelliteSize / 2,
                                           y: 6.25 - satelliteSize / 2,
                                           width: satelliteSize, height: satelliteSize))
            if active {
                context.fillEllipse(in: CGRect(x: 1.65, y: 10.8, width: 2.2, height: 2.2))
            }
            return true
        }
        image.isTemplate = true
        return image
    }

    static func palm(active: Bool = false) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)

            func drawLeaf(_ path: CGPath, color: NSColor) {
                context.setFillColor(color.cgColor)
                context.addPath(path)
                context.fillPath()
                context.setStrokeColor(palmInk.cgColor)
                context.setLineWidth(0.6)
                context.addPath(path)
                context.strokePath()
            }

            let trunk = CGMutablePath()
            trunk.move(to: CGPoint(x: 5.9, y: 1.65))
            trunk.addCurve(to: CGPoint(x: 8.75, y: 10.45),
                           control1: CGPoint(x: 6.45, y: 4.5),
                           control2: CGPoint(x: 7.05, y: 8.05))
            trunk.addCurve(to: CGPoint(x: 10.0, y: 10.35),
                           control1: CGPoint(x: 9.2, y: 10.65),
                           control2: CGPoint(x: 9.65, y: 10.55))
            trunk.addCurve(to: CGPoint(x: 7.75, y: 1.55),
                           control1: CGPoint(x: 9.1, y: 7.65),
                           control2: CGPoint(x: 8.45, y: 4.0))
            trunk.closeSubpath()
            context.setFillColor(palmGold.cgColor)
            context.addPath(trunk)
            context.fillPath()
            context.setStrokeColor(palmInk.cgColor)
            context.setLineWidth(0.75)
            context.addPath(trunk)
            context.strokePath()

            let trunkHighlight = CGMutablePath()
            trunkHighlight.move(to: CGPoint(x: 7.1, y: 2.35))
            trunkHighlight.addCurve(to: CGPoint(x: 8.65, y: 8.75),
                                    control1: CGPoint(x: 7.35, y: 4.45),
                                    control2: CGPoint(x: 7.8, y: 7.0))
            context.setStrokeColor(signatureActive.withAlphaComponent(0.72).cgColor)
            context.setLineWidth(0.48)
            context.addPath(trunkHighlight)
            context.strokePath()

            let left = CGMutablePath()
            left.move(to: CGPoint(x: 9.25, y: 10.65))
            left.addCurve(to: CGPoint(x: 2.05, y: 10.95),
                          control1: CGPoint(x: 7.15, y: 12.9),
                          control2: CGPoint(x: 4.15, y: 13.0))
            left.addCurve(to: CGPoint(x: 9.25, y: 10.65),
                          control1: CGPoint(x: 4.25, y: 11.05),
                          control2: CGPoint(x: 7.15, y: 10.0))
            left.closeSubpath()
            drawLeaf(left, color: palmTeal)

            let upperLeft = CGMutablePath()
            upperLeft.move(to: CGPoint(x: 9.25, y: 10.65))
            upperLeft.addCurve(to: CGPoint(x: 5.15, y: 15.75),
                               control1: CGPoint(x: 7.95, y: 13.05),
                               control2: CGPoint(x: 6.0, y: 15.1))
            upperLeft.addCurve(to: CGPoint(x: 9.25, y: 10.65),
                               control1: CGPoint(x: 6.55, y: 14.1),
                               control2: CGPoint(x: 8.35, y: 11.6))
            upperLeft.closeSubpath()
            drawLeaf(upperLeft, color: palmJade)

            let upperRight = CGMutablePath()
            upperRight.move(to: CGPoint(x: 9.3, y: 10.7))
            upperRight.addCurve(to: CGPoint(x: 12.05, y: 15.7),
                                control1: CGPoint(x: 9.85, y: 13.0),
                                control2: CGPoint(x: 11.1, y: 15.25))
            upperRight.addCurve(to: CGPoint(x: 9.3, y: 10.7),
                                control1: CGPoint(x: 11.05, y: 14.0),
                                control2: CGPoint(x: 9.65, y: 11.75))
            upperRight.closeSubpath()
            drawLeaf(upperRight, color: palmTeal)

            let right = CGMutablePath()
            right.move(to: CGPoint(x: 9.35, y: 10.7))
            right.addCurve(to: CGPoint(x: 16.05, y: 11.75),
                           control1: CGPoint(x: 11.45, y: 13.15),
                           control2: CGPoint(x: 14.35, y: 13.45))
            right.addCurve(to: CGPoint(x: 9.35, y: 10.7),
                           control1: CGPoint(x: 14.15, y: 11.65),
                           control2: CGPoint(x: 11.5, y: 10.15))
            right.closeSubpath()
            drawLeaf(right, color: palmJade)

            let lowerRight = CGMutablePath()
            lowerRight.move(to: CGPoint(x: 9.4, y: 10.6))
            lowerRight.addCurve(to: CGPoint(x: 14.65, y: 8.25),
                                control1: CGPoint(x: 11.85, y: 11.0),
                                control2: CGPoint(x: 14.15, y: 9.65))
            lowerRight.addCurve(to: CGPoint(x: 9.4, y: 10.6),
                                control1: CGPoint(x: 13.35, y: 9.0),
                                control2: CGPoint(x: 11.35, y: 9.65))
            lowerRight.closeSubpath()
            drawLeaf(lowerRight, color: palmTeal)

            let coconuts = [CGPoint(x: 8.7, y: 10.25), CGPoint(x: 10.25, y: 10.05)]
            for center in coconuts {
                context.setFillColor(palmInk.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 1.13, y: center.y - 1.13,
                                               width: 2.26, height: 2.26))
                context.setFillColor(palmCopper.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 0.69, y: center.y - 0.69,
                                               width: 1.38, height: 1.38))
            }

            if active {
                context.setFillColor(signatureActive.cgColor)
                context.fillEllipse(in: CGRect(x: 14.45, y: 2.35, width: 2.15, height: 2.15))
            }
            return true
        }
        image.isTemplate = false
        return image
    }
}

struct MenuBarPresentation {
    var image: NSImage?
    var title: NSAttributedString
}

enum MenuBarTitleRenderer {
    private static let valueFont = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)

    static func render(style: MenuBarStyle, density: MenuBarDensity, keepAwake: Bool,
                       metrics: [MenuBarMetric], fallbackIcon: Bool = false) -> MenuBarPresentation {
        let title = NSMutableAttributedString()
        var leadingImage: NSImage?
        let focused = focusedMetric(in: metrics)
        let visibleMetrics = density == .lowest ? focused.map { [$0] } ?? Array(metrics.prefix(1)) : metrics

        if density == .icon {
            leadingImage = iconOnlyImage(style: style, metric: focused, active: keepAwake)
            if style == .dots && !keepAwake {
                appendIconOnlyDot(to: title, metric: focused)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .system || style == .color {
            leadingImage = style == .system
                ? MenuBarArtwork.brand(color: .white, active: keepAwake)
                : MenuBarArtwork.signature(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title,
                                    color: style == .system
                                        ? NSColor.white.withAlphaComponent(0.72)
                                        : .secondaryLabelColor)
                }
                appendValue(metric, color: style == .system ? .white : color(for: metric.kind),
                            to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .artistic {
            leadingImage = MenuBarArtwork.starTrail(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title)
                }
                appendValue(metric, color: .labelColor, to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .palm {
            leadingImage = MenuBarArtwork.palm(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title)
                }
                appendValue(metric, color: .labelColor, to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if keepAwake {
            leadingImage = MenuBarArtwork.signature(active: true)
        }

        for (index, metric) in visibleMetrics.enumerated() {
            if title.length > 0 {
                appendSeparator(style == .compact && index > 0 ? " · " : "  ", to: title)
            }
            appendDecorated(metric, to: title, style: style)
        }

        if fallbackIcon && visibleMetrics.isEmpty {
            leadingImage = MenuBarArtwork.brand(color: nil)
        }

        return MenuBarPresentation(image: leadingImage, title: title)
    }

    private static func appendDecorated(_ metric: MenuBarMetric, to title: NSMutableAttributedString,
                                        style: MenuBarStyle) {
        let familyColor = color(for: metric.kind)
        switch style {
        case .symbols:
            appendArtwork(MenuBarArtwork.gauge(remaining: metric.remaining, color: familyColor), to: title)
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .dots:
            title.append(NSAttributedString(string: "●", attributes: [
                .font: NSFont.systemFont(ofSize: 7, weight: .bold),
                .baselineOffset: 1,
                .foregroundColor: familyColor,
            ]))
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .compact:
            appendValue(metric, color: familyColor, to: title)
        case .system, .color, .artistic, .palm:
            appendValue(metric, color: familyColor, to: title)
        }
    }

    private static func appendValue(_ metric: MenuBarMetric, color: NSColor,
                                    to title: NSMutableAttributedString) {
        title.append(NSAttributedString(string: metric.value, attributes: [
            .font: valueFont,
            .baselineOffset: 1,
            .foregroundColor: color,
        ]))
    }

    private static func iconOnlyImage(style: MenuBarStyle, metric: MenuBarMetric?,
                                      active: Bool) -> NSImage? {
        let tint = color(for: metric?.kind ?? .total)
        if style == .artistic {
            return MenuBarArtwork.starTrail(active: active)
        }
        if style == .palm {
            return MenuBarArtwork.palm(active: active)
        }
        if active {
            if style == .color { return MenuBarArtwork.signature(active: true) }
            let color: NSColor? = style == .system ? .white : tint
            return MenuBarArtwork.brand(color: color, active: true)
        }
        switch style {
        case .system:
            return MenuBarArtwork.brand(color: .white)
        case .compact:
            return MenuBarArtwork.brand(color: nil)
        case .color:
            return MenuBarArtwork.signature()
        case .symbols:
            return MenuBarArtwork.gauge(remaining: metric?.remaining, size: 16)
        case .dots:
            return nil
        case .artistic:
            return MenuBarArtwork.starTrail()
        case .palm:
            return MenuBarArtwork.palm()
        }
    }

    private static func appendIconOnlyDot(to title: NSMutableAttributedString,
                                          metric: MenuBarMetric?) {
        title.append(NSAttributedString(string: "●", attributes: [
            .font: NSFont.systemFont(ofSize: 8, weight: .bold),
            .foregroundColor: color(for: metric?.kind ?? .total),
        ]))
    }

    private static func focusedMetric(in metrics: [MenuBarMetric]) -> MenuBarMetric? {
        let quotas = metrics.filter { $0.remaining != nil }
        if !quotas.isEmpty {
            return quotas.min { ($0.remaining ?? 0) < ($1.remaining ?? 0) }
        }
        return metrics.first
    }

    private static func appendSpace(to title: NSMutableAttributedString) {
        title.append(NSAttributedString(string: " ", attributes: [.font: valueFont]))
    }

    private static func appendSeparator(_ value: String, to title: NSMutableAttributedString,
                                        color: NSColor = .secondaryLabelColor) {
        title.append(NSAttributedString(string: value, attributes: [
            .font: valueFont,
            .foregroundColor: color,
        ]))
    }

    private static func appendArtwork(_ image: NSImage, to title: NSMutableAttributedString) {
        let attachment = NSTextAttachment()
        attachment.image = image
        title.append(NSAttributedString(attachment: attachment))
    }

    private static func color(for kind: MenuBarMetricKind) -> NSColor {
        switch kind {
        case .claude: return AppDelegate.claudeColor
        case .codex: return AppDelegate.codexColor
        case .total: return .secondaryLabelColor
        }
    }

}

struct MenuBarStylePreview: View {
    var style: MenuBarStyle
    var density: MenuBarDensity

    var body: some View {
        HStack(spacing: style == .compact ? 5 : 6) { previewContent }
        .font(.system(size: 10, weight: .semibold, design: .monospaced))
        .frame(height: 20)
        .accessibilityLabel("\(style.label)菜单栏预览")
    }

    @ViewBuilder
    private var previewContent: some View {
        switch style {
        case .system, .color:
            brandMark
            if density == .lowest {
                value(.codex, "85")
            } else if density == .full {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        case .symbols:
            if density == .icon || density == .lowest {
                gauge(.codex, "85", showValue: density != .icon)
            } else {
                gauge(.claude, "98", showValue: true)
                gauge(.codex, "85", showValue: true)
            }
        case .dots:
            if density == .icon {
                Circle().fill(Theme.codex).frame(width: 6, height: 6)
            } else if density == .lowest {
                dot(.codex, "85")
            } else {
                dot(.claude, "98")
                dot(.codex, "85")
            }
        case .compact:
            if density == .icon {
                templateImage(MenuBarArtwork.brand())
            } else if density == .lowest {
                value(.codex, "85")
            } else {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        case .artistic:
            templateImage(MenuBarArtwork.starTrail())
            if density == .lowest {
                value(.codex, "85")
            } else if density == .full {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        case .palm:
            Image(nsImage: MenuBarArtwork.palm())
            if density == .lowest {
                value(.codex, "85")
            } else if density == .full {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        }
    }

    @ViewBuilder
    private var brandMark: some View {
        if style == .system {
            Image(nsImage: MenuBarArtwork.brand(color: .white))
        } else {
            Image(nsImage: MenuBarArtwork.signature())
        }
    }

    private func templateImage(_ image: NSImage) -> some View {
        Image(nsImage: image)
            .renderingMode(.template)
            .foregroundStyle(Theme.tSecondary)
    }

    @ViewBuilder
    private func gauge(_ kind: MenuBarMetricKind, _ value: String, showValue: Bool) -> some View {
        let tint = nsColor(kind)
        let size: CGFloat = density == .icon ? 16 : 11
        Image(nsImage: MenuBarArtwork.gauge(remaining: Double(value), color: tint, size: size))
        if showValue {
            Text(value).foregroundStyle(Theme.tSecondary)
        }
    }

    private func dot(_ kind: MenuBarMetricKind, _ value: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(swiftColor(kind)).frame(width: 5, height: 5)
            Text(value).foregroundStyle(Theme.tSecondary)
        }
    }

    @ViewBuilder
    private func value(_ kind: MenuBarMetricKind, _ value: String) -> some View {
        if style == .system {
            Text(value).foregroundStyle(.white)
        } else if style == .artistic || style == .palm {
            Text(value).foregroundStyle(Theme.tSecondary)
        } else {
            Text(value).foregroundStyle(swiftColor(kind))
        }
    }

    private func nsColor(_ kind: MenuBarMetricKind) -> NSColor {
        switch kind {
        case .claude: return AppDelegate.claudeColor
        case .codex: return AppDelegate.codexColor
        case .total: return .secondaryLabelColor
        }
    }

    private func swiftColor(_ kind: MenuBarMetricKind) -> Color {
        switch kind {
        case .claude: return Theme.claude
        case .codex: return Theme.codex
        case .total: return Theme.tSecondary
        }
    }
}
