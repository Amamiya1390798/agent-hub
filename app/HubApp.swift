// Hub 面板的原生窗口：有自己的程序坞图标，内嵌显示本机面板页面。
import Cocoa
import WebKit

let panelURL = URL(string: "http://127.0.0.1:8765/")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var tries = 0

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.navigationDelegate = self
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1380, height: 880),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Hub"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 520, height: 480)
        window.center()
        window.setFrameAutosaveName("HubMainWindow")
        window.contentView = web
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.global().async {
            self.ensureServer()
            DispatchQueue.main.async { self.load() }
        }
    }

    // 确保后台的面板服务在运行（已经在跑就什么都不做）
    func ensureServer() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: NSHomeDirectory() + "/.local/bin/hub")
        p.arguments = ["ui", "--no-window"]
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = NSHomeDirectory() + "/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        p.environment = env
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run(); p.waitUntilExit() } catch {}
    }

    func load() { web.load(URLRequest(url: panelURL, cachePolicy: .reloadIgnoringLocalCacheData)) }

    func retryOrFail(_ error: Error) {
        tries += 1
        if tries <= 20 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.load() }
        } else {
            let html = "<body style='font:15px -apple-system;padding:40px;color:#555'><h3>面板服务没能启动</h3><p>在终端运行 <code>hub ui</code> 看看报了什么错，然后按 ⌘R 重试。</p></body>"
            web.loadHTMLString(html, baseURL: nil)
        }
    }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { retryOrFail(e) }
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) { tries = 0 }

    // 外部链接交给默认浏览器
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, let host = u.host, host != "127.0.0.1", host != "localhost", a.navigationType == .linkActivated {
            NSWorkspace.shared.open(u)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { NSWorkspace.shared.open(u) }
        return nil
    }

    // 网页里的 alert / confirm / prompt：WKWebView 默认不显示，必须自己弹系统对话框，
    // 否则 confirm() 会直接当作「取消」，按钮看起来就是点了没反应。
    func panel(_ text: String, buttons: [String], input: String? = nil) -> (Bool, String?) {
        let a = NSAlert()
        a.messageText = text
        buttons.forEach { a.addButton(withTitle: $0) }
        var field: NSTextField?
        if let v = input {
            let f = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
            f.stringValue = v; a.accessoryView = f; field = f
        }
        let ok = a.runModal() == .alertFirstButtonReturn
        return (ok, field?.stringValue)
    }
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping () -> Void) {
        _ = panel(m, buttons: ["好"]); completionHandler()
    }
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        completionHandler(panel(m, buttons: ["确定", "取消"]).0)
    }
    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt p: String, defaultText d: String?, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let r = panel(p, buttons: ["确定", "取消"], input: d ?? "")
        completionHandler(r.0 ? r.1 : nil)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    @objc func reload(_ s: Any?) { tries = 0; DispatchQueue.global().async { self.ensureServer(); DispatchQueue.main.async { self.load() } } }
    @objc func showWindow(_ s: Any?) { window.makeKeyAndOrderFront(nil) }

    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) {
            let mi = NSMenuItem(); let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            mi.submenu = m; main.addItem(mi)
        }
        func item(_ t: String, _ sel: Selector?, _ key: String, target: AnyObject? = nil) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: sel, keyEquivalent: key); i.target = target; return i
        }
        add("Hub", [item("隐藏 Hub", #selector(NSApplication.hide(_:)), "h"), .separator(),
                    item("退出 Hub", #selector(NSApplication.terminate(_:)), "q")])
        add("编辑", [item("撤销", Selector(("undo:")), "z"), item("重做", Selector(("redo:")), "Z"), .separator(),
                    item("剪切", #selector(NSText.cut(_:)), "x"), item("拷贝", #selector(NSText.copy(_:)), "c"),
                    item("粘贴", #selector(NSText.paste(_:)), "v"), item("全选", #selector(NSText.selectAll(_:)), "a")])
        add("显示", [item("重新载入", #selector(reload(_:)), "r", target: self)])
        add("窗口", [item("最小化", #selector(NSWindow.performMiniaturize(_:)), "m"),
                    item("关闭窗口", #selector(NSWindow.performClose(_:)), "w"),
                    item("显示 Hub 窗口", #selector(showWindow(_:)), "0", target: self)])
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
