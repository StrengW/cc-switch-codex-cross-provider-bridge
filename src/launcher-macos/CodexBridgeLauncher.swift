import AppKit
import Darwin
import Foundation

struct CommandResult {
    let status: Int32
    let output: String
}

final class CommandRunner {
    func run(_ executable: String, _ arguments: [String]) -> CommandResult {
        let process = Process()
        let outputPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = outputPipe
        process.standardError = outputPipe
        do {
            try process.run()
            process.waitUntilExit()
            let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
            return CommandResult(status: process.terminationStatus,
                                  output: String(data: data, encoding: .utf8) ?? "")
        } catch {
            return CommandResult(status: -1, output: error.localizedDescription)
        }
    }
}

struct LauncherPaths {
    let home: String
    let stateRoot: String
    let appRoot: String
    let launcherApp: String
    let manager: String
    let uninstall: String
    let launcherPlist: String
    let launcherDisabled: String
    let watcherPlist: String
    let launcherLog: String
    let watcherLog: String
    let bridgeLog: String
    let routeState: String

    init() {
        home = FileManager.default.homeDirectoryForCurrentUser.path
        stateRoot = "\(home)/Library/Application Support/CodexProviderBridge"
        appRoot = "\(stateRoot)/app"
        launcherApp = "\(appRoot)/CodexBridge.app"
        manager = "\(appRoot)/codex_bridge_manager.sh"
        uninstall = "\(appRoot)/codex_bridge_uninstall.sh"
        launcherPlist = "\(home)/Library/LaunchAgents/com.strengw.codexbridge.launcher.plist"
        launcherDisabled = "\(stateRoot)/launcher-disabled"
        watcherPlist = "\(home)/Library/LaunchAgents/com.strengw.codexbridge.watcher.plist"
        launcherLog = "\(stateRoot)/launcher.log"
        watcherLog = "\(stateRoot)/macos-watcher.log"
        bridgeLog = "\(stateRoot)/bridge-stdout.log"
        routeState = "\(home)/.codex/cpb-active-model-catalog.json.source.json"
    }
}

struct LocalizedCopy {
    let chinese: Bool

    init() {
        let preferred = Locale.preferredLanguages.compactMap { Locale(identifier: $0).languageCode }
        let systemLanguage = Locale.current.languageCode
        chinese = systemLanguage?.hasPrefix("zh") == true || preferred.contains { $0.hasPrefix("zh") }
    }

    func text(_ english: String, _ simplifiedChinese: String) -> String {
        chinese ? simplifiedChinese : english
    }
}

enum ReleaseUpdateResult {
    case failed(String)
    case upToDate
    case available(version: String, url: URL)
}

final class ReleaseUpdateChecker {
    static let apiURL = URL(string: "https://api.github.com/repos/StrengW/cc-switch-codex-cross-provider-bridge/releases/latest")!
    static let releaseURL = URL(string: "https://github.com/StrengW/cc-switch-codex-cross-provider-bridge/releases")!

    static func check(currentVersion: String, completion: @escaping (ReleaseUpdateResult) -> Void) {
        var request = URLRequest(url: apiURL)
        request.httpMethod = "GET"
        request.timeoutInterval = 5
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("CodexBridge-Launcher/\(currentVersion)", forHTTPHeaderField: "User-Agent")
        URLSession.shared.dataTask(with: request) { data, _, error in
            guard let data, error == nil else {
                DispatchQueue.main.async { completion(.failed(error?.localizedDescription ?? "Network request failed.")) }
                return
            }
            guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tag = object["tag_name"] as? String,
                  let latest = normalizedVersion(tag) else {
                DispatchQueue.main.async { completion(.failed("GitHub latest release metadata was invalid.")) }
                return
            }
            let url = URL(string: (object["html_url"] as? String) ?? "") ?? releaseURL
            let result: ReleaseUpdateResult = isNewer(latest, than: currentVersion)
                ? .available(version: latest, url: url)
                : .upToDate
            DispatchQueue.main.async { completion(result) }
        }.resume()
    }

    private static func normalizedVersion(_ value: String) -> String? {
        let candidate = value.hasPrefix("v") ? String(value.dropFirst()) : value
        let parts = candidate.split(separator: ".", maxSplits: 2).map(String.init)
        guard parts.count == 3, Int(parts[0]) != nil, Int(parts[1]) != nil else { return nil }
        let patch = parts[2].split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init) ?? ""
        guard Int(patch) != nil else { return nil }
        return candidate
    }

    private static func isNewer(_ left: String, than right: String) -> Bool {
        func parts(_ value: String) -> [Int] {
            let raw = value.hasPrefix("v") ? String(value.dropFirst()) : value
            return raw.split(separator: ".", maxSplits: 2).map {
                let numeric = $0.split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init) ?? "0"
                return Int(numeric) ?? 0
            }
        }
        let a = parts(left) + [0, 0, 0]
        let b = parts(right) + [0, 0, 0]
        for index in 0..<3 where a[index] != b[index] { return a[index] > b[index] }
        return false
    }
}

struct BridgeStatus {
    enum State: String { case running = "Running", stopped = "Stopped", unknown = "Unknown" }
    var state: State = .unknown
    var route: String = "Unknown"
    var model: String?
}

final class LauncherController {
    let paths = LauncherPaths()
    let copy = LocalizedCopy()
    private let runner = CommandRunner()

    func status() -> BridgeStatus {
        var result = BridgeStatus()
        let managerResult = runner.run("/bin/bash", [paths.manager, "status"])
        if managerResult.status == 0 {
            let lines = managerResult.output.split(separator: "\n")
            let managed = lines.first { $0.hasPrefix("ManagedProcess:") }?.contains("true") == true
            let listening = lines.first { $0.hasPrefix("BridgeListening:") }?.contains("true") == true
            result.state = managed && listening ? .running : .stopped
            if let override = lines.first(where: { $0.hasPrefix("ModelOverride:") }) {
                let value = override.split(separator: ":", maxSplits: 1).last.map(String.init)?.trimmingCharacters(in: .whitespaces)
                result.model = value?.isEmpty == false ? value : nil
            }
        }
        if let data = FileManager.default.contents(atPath: paths.routeState),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let kind = json["route_kind"] as? String {
                result.route = kind == "official" ? "Official" : kind == "third-party" ? "Third-party" : "Unknown"
            }
            if result.model == nil, let model = json["route_model"] as? String, !model.isEmpty {
                result.model = model
            }
        }
        return result
    }

    @discardableResult
    func ensureBridge() -> Bool {
        runner.run("/bin/bash", [paths.manager, "start", "--background"]).status == 0
    }

    @discardableResult
    func restartBridge() -> Bool {
        runner.run("/bin/bash", [paths.manager, "restart", "--background"]).status == 0
    }

    @discardableResult
    func restartCodex() -> Bool {
        runner.run("/bin/bash", [paths.manager, "restart-codex"]).status == 0
    }

    @discardableResult
    func restartCCSwitch() -> Bool {
        runner.run("/bin/bash", [paths.manager, "restart-cc-switch"]).status == 0
    }

    func open(_ path: String) -> Bool {
        runner.run("/usr/bin/open", [path]).status == 0
    }

    func stopAll() {
        _ = runner.run("/bin/bash", [paths.manager, "stop"])
        _ = runner.run("/bin/launchctl", ["bootout", "gui/\(getuid())", paths.launcherPlist])
        _ = runner.run("/bin/launchctl", ["bootout", "gui/\(getuid())", paths.watcherPlist])
        _ = runner.run("/usr/bin/osascript", ["-e", "tell application \"CC Switch\" to quit"])
    }

    func uninstall() -> Bool {
        runner.run("/bin/bash", [paths.uninstall, "--confirmed"]).status == 0
    }

    func launcherAtLogin() -> Bool {
        guard let dictionary = NSDictionary(contentsOfFile: paths.launcherPlist) as? [String: Any] else { return true }
        return dictionary["RunAtLoad"] as? Bool ?? true
    }

    @discardableResult
    func setLauncherAtLogin(_ enabled: Bool) -> Bool {
        let directory = (paths.launcherPlist as NSString).deletingLastPathComponent
        try? FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "Label": "com.strengw.codexbridge.launcher",
            "ProgramArguments": ["/usr/bin/open", paths.launcherApp],
            "RunAtLoad": enabled,
            "ProcessType": "Interactive",
            "StandardOutPath": paths.launcherLog,
            "StandardErrorPath": paths.launcherLog
        ]
        guard (payload as NSDictionary).write(toFile: paths.launcherPlist, atomically: true) else { return false }
        if enabled {
            try? FileManager.default.removeItem(atPath: paths.launcherDisabled)
        } else {
            FileManager.default.createFile(atPath: paths.launcherDisabled, contents: Data(), attributes: nil)
        }
        _ = runner.run("/bin/launchctl", ["bootout", "gui/\(getuid())", paths.launcherPlist])
        let result = runner.run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", paths.launcherPlist])
        return result.status == 0 || !enabled
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let controller = LauncherController()
    private let currentVersion = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.0.0"
    private let updateCheckKey = "CodexBridge.lastUpdateCheck"
    private var statusItem: NSStatusItem!
    private var statusLabel: NSMenuItem!
    private var routeLabel: NSMenuItem!
    private var modelLabel: NSMenuItem?
    private var loginItem: NSMenuItem!
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "link", accessibilityDescription: "CodexBridge")
        statusItem.button?.image?.isTemplate = true
        buildMenu()
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshStatus() }
        checkForUpdates(manual: false)
    }

    private func buildMenu() {
        let menu = NSMenu()
        let title = NSMenuItem(title: "CodexBridge", action: nil, keyEquivalent: "")
        title.isEnabled = false
        menu.addItem(title)
        statusLabel = NSMenuItem(title: "Status: Unknown", action: nil, keyEquivalent: "")
        routeLabel = NSMenuItem(title: "Route: Unknown", action: nil, keyEquivalent: "")
        menu.addItem(statusLabel); menu.addItem(routeLabel)
        menu.addItem(.separator())
        add(menu, "Ensure Bridge Running", #selector(ensureBridge))
        add(menu, "Restart Bridge", #selector(restartBridge))
        add(menu, "Restart Codex", #selector(restartCodex))
        add(menu, "Restart CC Switch", #selector(restartCCSwitch))
        menu.addItem(.separator())
        add(menu, "Open Bridge Log", #selector(openBridgeLog))
        add(menu, "Open Watcher Log", #selector(openWatcherLog))
        add(menu, "Open Launcher Log", #selector(openLauncherLog))
        add(menu, "Open Log Folder", #selector(openLogFolder))
        add(menu, "Check for Updates...", #selector(manualCheckForUpdates))
        loginItem = NSMenuItem(title: "Launch at Login", action: #selector(toggleLogin), keyEquivalent: "")
        menu.addItem(loginItem)
        menu.addItem(.separator())
        add(menu, "Exit Everything...", #selector(exitEverything))
        add(menu, "Uninstall CodexBridge...", #selector(uninstall))
        statusItem.menu = menu
        updateLoginTitle()
    }

    private func add(_ menu: NSMenu, _ english: String, _ selector: Selector) {
        let chinese: [String: String] = ["Ensure Bridge Running": "确保 Bridge 运行", "Restart Bridge": "重启 Bridge", "Restart Codex": "重启 Codex", "Restart CC Switch": "重启 CC Switch", "Open Bridge Log": "打开 Bridge 日志", "Open Watcher Log": "打开 Watcher 日志", "Open Launcher Log": "打开 Launcher 日志", "Open Log Folder": "打开日志目录", "Check for Updates...": "检查更新...", "Exit Everything...": "退出全部组件...", "Uninstall CodexBridge...": "卸载 CodexBridge..."]
        menu.addItem(NSMenuItem(title: controller.copy.text(english, chinese[english] ?? english), action: selector, keyEquivalent: ""))
    }

    private func refreshStatus() {
        let value = controller.status()
        statusLabel.title = controller.copy.text("Status: \(value.state.rawValue)", "状态：\(value.state == .running ? "运行中" : value.state == .stopped ? "已停止" : "未知")")
        routeLabel.title = controller.copy.text("Route: \(value.route)", "路由：\(value.route == "Official" ? "官方" : value.route == "Third-party" ? "第三方" : "未知")")
        if let model = value.model, !model.isEmpty {
            if modelLabel == nil { modelLabel = NSMenuItem(title: "", action: nil, keyEquivalent: ""); statusItem.menu?.insertItem(modelLabel!, at: 3) }
            modelLabel?.title = controller.copy.text("Model: \(model)", "模型：\(model)")
        } else if let item = modelLabel, let index = statusItem.menu?.index(of: item), index >= 0 {
            statusItem.menu?.removeItem(at: index); modelLabel = nil
        }
    }

    private func updateLoginTitle() {
        let suffix = controller.launcherAtLogin() ? " ✓" : ""
        loginItem.title = controller.copy.text("Launch at Login\(suffix)", "登录时启动\(suffix)")
    }

    private func notify(_ message: String) {
        let alert = NSAlert(); alert.messageText = "CodexBridge"; alert.informativeText = message; alert.alertStyle = .warning; alert.runModal()
    }

    private func configureNoAsDefaultButton(_ alert: NSAlert) {
        alert.buttons.last?.keyEquivalent = "\r"
    }

    @objc private func manualCheckForUpdates() { checkForUpdates(manual: true) }
    private func checkForUpdates(manual: Bool) {
        if !manual && !shouldCheckForUpdates() { return }
        ReleaseUpdateChecker.check(currentVersion: currentVersion) { [weak self] result in
            guard let self else { return }
            switch result {
            case .available(let version, let url): self.showUpdatePrompt(version: version, url: url)
            case .upToDate where manual: self.notify(self.controller.copy.text("CodexBridge is up to date.", "CodexBridge 已是最新版本。"))
            case .failed(let message) where manual: self.notify(self.controller.copy.text("Could not check for updates: ", "无法检查更新：") + message)
            default: break
            }
        }
    }

    private func shouldCheckForUpdates() -> Bool {
        let defaults = UserDefaults.standard
        let previous = defaults.object(forKey: updateCheckKey) as? Date
        if let previous, Date().timeIntervalSince(previous) < 24 * 60 * 60 { return false }
        defaults.set(Date(), forKey: updateCheckKey)
        return true
    }

    private func showUpdatePrompt(version: String, url: URL) {
        let alert = NSAlert()
        alert.messageText = controller.copy.text("CodexBridge update available", "CodexBridge 有可用更新")
        alert.informativeText = controller.copy.text("Version \(version) is available (current \(currentVersion)).", "发现新版本 \(version)（当前为 \(currentVersion)）。")
        alert.alertStyle = .informational
        alert.addButton(withTitle: controller.copy.text("Open Latest Release", "打开最新版本页面"))
        alert.addButton(withTitle: controller.copy.text("Later", "稍后"))
        configureNoAsDefaultButton(alert)
        if alert.runModal() == .alertFirstButtonReturn { _ = controller.open(url.path.isEmpty ? ReleaseUpdateChecker.releaseURL.absoluteString : url.absoluteString) }
    }

    @objc private func ensureBridge() { if !controller.ensureBridge() { notify(controller.copy.text("Could not start the Bridge.", "无法启动 Bridge。")) }; refreshStatus() }
    @objc private func restartBridge() { if !controller.restartBridge() { notify(controller.copy.text("Could not restart the Bridge.", "无法重启 Bridge。")) }; refreshStatus() }
    @objc private func restartCodex() { if !controller.restartCodex() { notify(controller.copy.text("Codex was not running or could not be restarted.", "Codex 未运行或无法重启。")) } }
    @objc private func restartCCSwitch() { if !controller.restartCCSwitch() { notify(controller.copy.text("CC Switch could not be restarted.", "无法重启 CC Switch。")) } }
    @objc private func openBridgeLog() { _ = controller.open(controller.paths.bridgeLog) }
    @objc private func openWatcherLog() { _ = controller.open(controller.paths.watcherLog) }
    @objc private func openLauncherLog() { _ = controller.open(controller.paths.launcherLog) }
    @objc private func openLogFolder() { _ = controller.open(controller.paths.stateRoot) }
    @objc private func toggleLogin() { _ = controller.setLauncherAtLogin(!controller.launcherAtLogin()); updateLoginTitle() }

    @objc private func exitEverything() {
        let alert = NSAlert(); alert.messageText = controller.copy.text("Exit CodexBridge?", "退出 CodexBridge？"); alert.informativeText = controller.copy.text("This will stop CodexBridge background services. You may need to restart Codex before using Bridge again.", "这会停止 CodexBridge 后台服务，并可能需要重新启动 Codex 才能继续通过 Bridge 工作。"); alert.alertStyle = .warning; alert.addButton(withTitle: controller.copy.text("Exit Everything", "退出全部组件")); alert.addButton(withTitle: controller.copy.text("Cancel", "取消")); configureNoAsDefaultButton(alert); if alert.runModal() == .alertFirstButtonReturn { controller.stopAll(); NSApp.terminate(nil) }
    }

    @objc private func uninstall() {
        let alert = NSAlert(); alert.messageText = controller.copy.text("Uninstall CodexBridge?", "卸载 CodexBridge？"); alert.informativeText = controller.copy.text("This removes the Bridge app, runtime, logs, and launch agents. Codex chat history is not removed.", "这会删除 Bridge 应用、运行时、日志和启动项，不会删除 Codex 聊天记录。"); alert.alertStyle = .warning; alert.addButton(withTitle: controller.copy.text("Uninstall", "卸载")); alert.addButton(withTitle: controller.copy.text("Cancel", "取消")); configureNoAsDefaultButton(alert); if alert.runModal() == .alertFirstButtonReturn { if !controller.uninstall() { notify(controller.copy.text("Uninstall failed. See the launcher log.", "卸载失败，请查看 Launcher 日志。")) } else { NSApp.terminate(nil) } }
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
