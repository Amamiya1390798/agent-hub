// 画 Hub 图标（深色圆角方块 + 四个 agent 色点），输出 1024 PNG。
import Cocoa
let S: CGFloat = 1024
let img = NSImage(size: NSSize(width: S, height: S))
img.lockFocus()
let inset: CGFloat = 100
let rect = NSRect(x: inset, y: inset, width: S - inset * 2, height: S - inset * 2)
let bg = NSBezierPath(roundedRect: rect, xRadius: 185, yRadius: 185)
NSGradient(colors: [NSColor(red: 0.16, green: 0.155, blue: 0.14, alpha: 1), NSColor(red: 0.09, green: 0.088, blue: 0.08, alpha: 1)])!.draw(in: bg, angle: -90)
let cols = [NSColor(red: 0.23, green: 0.49, blue: 0.94, alpha: 1), NSColor(red: 0.82, green: 0.44, blue: 0.31, alpha: 1),
            NSColor(red: 0.07, green: 0.64, blue: 0.50, alpha: 1), NSColor(red: 0.48, green: 0.36, blue: 0.96, alpha: 1)]
let d: CGFloat = 190, gap: CGFloat = 120
let x0 = S / 2 - gap / 2 - d, x1 = S / 2 + gap / 2, y0 = S / 2 - gap / 2 - d, y1 = S / 2 + gap / 2
for (i, p) in [(x0, y1), (x1, y1), (x0, y0), (x1, y0)].enumerated() {
    cols[i].setFill()
    NSBezierPath(ovalIn: NSRect(x: p.0, y: p.1, width: d, height: d)).fill()
}
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
