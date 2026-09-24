import AppKit
import Darwin
import Foundation

struct CommandResult {
    let status: Int32
    let output: String
}

final class CommandRunner {
    func run(_ executable: String, _ arguments: [String], timeout: TimeInterval = 20) -> CommandResult {
        let process = Process()
        let outputPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = outputPipe
        process.standardError = outputPipe
        do {
            try process.run()
            let deadline = Date().addingTimeInterval(timeout)
            while process.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
            if process.isRunning {
                process.terminate()
                process.waitUntilExit()
                let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
                return CommandResult(status: -2,
                                      output: "Command timed out after \(Int(timeout)) seconds.\n" + (String(data: data, encoding: .utf8) ?? ""))
            }
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
    let watcherPlist: String
    let launcherLog: String
    let watcherLog: String
    let bridgeLog: String
    let routeState: String
    let directOfficialLatch: String

    init() {
        home = FileManager.default.homeDirectoryForCurrentUser.path
        stateRoot = "\(home)/Library/Application Support/CodexProviderBridge"
        appRoot = "\(stateRoot)/app"
        launcherApp = "\(appRoot)/CodexBridge.app"
        manager = "\(appRoot)/codex_bridge_manager.sh"
        uninstall = "\(appRoot)/codex_bridge_uninstall.sh"
        launcherPlist = "\(home)/Library/LaunchAgents/com.strengw.codexbridge.launcher.plist"
        watcherPlist = "\(home)/Library/LaunchAgents/com.strengw.codexbridge.watcher.plist"
        launcherLog = "\(stateRoot)/launcher.log"
        watcherLog = "\(stateRoot)/macos-watcher.log"
        bridgeLog = "\(stateRoot)/bridge-stdout.log"
        routeState = "\(home)/.codex/cpb-active-model-catalog.json.source.json"
        directOfficialLatch = "\(home)/.codex/cpb-native-detach.flag"
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
    // Third-party route is active but the CC Switch local proxy (:15721) is
    // unreachable, so third-party requests cannot be delivered yet.
    var thirdPartyBlocked: Bool = false
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
        if result.route == "Third-party" && !bridgePortOpen(15721) {
            result.thirdPartyBlocked = true
        }
        return result
    }

    // Returns the full manager result, not just the exit code: the failure
    // dialog needs the manager's reason ("Error: ..." on stderr) to be
    // actionable instead of a dead end.
    @discardableResult
    func ensureBridge() -> CommandResult {
        runner.run("/bin/bash", [paths.manager, "start", "--background"])
    }

    @discardableResult
    func restartBridge() -> CommandResult {
        runner.run("/bin/bash", [paths.manager, "restart", "--background"])
    }

    @discardableResult
    func restartCodex() -> Bool {
        runner.run("/bin/bash", [paths.manager, "restart-codex"]).status == 0
    }

    func open(_ path: String) -> Bool {
        runner.run("/usr/bin/open", [path]).status == 0
    }

    @discardableResult
    func stopAll() -> Bool {
        let route = status().route
        if route == "Official" {
            let handoff = runner.run("/bin/bash", [paths.manager, "prepare-direct-official"], timeout: 12)
            guard handoff.status == 0 else {
                clearDirectOfficialLatch()
                return false
            }
            let restarted = runner.run("/bin/bash", [paths.manager, "restart-codex"], timeout: 12)
            guard restarted.status == 0 else {
                clearDirectOfficialLatch()
                return false
            }
        }

        let bridgeStop = runner.run("/bin/bash", [paths.manager, "stop"], timeout: 12)
        _ = runner.run("/bin/launchctl", ["bootout", "gui/\(getuid())", paths.launcherPlist], timeout: 5)
        let ccSwitchStopped = stopCcSwitch()
        // The watcher LaunchAgent is intentionally left loaded. It is the only
        // login resident and will launch the full app on the next CC Switch
        // false -> true edge.
        return bridgeStop.status == 0 && ccSwitchStopped
    }

    private func clearDirectOfficialLatch() {
        try? FileManager.default.removeItem(atPath: paths.directOfficialLatch)
    }

    private let ccSwitchProcessPattern = "(^|/|[[:space:]])CC[ _-]*Switch([[:space:]]|$)|(^|/|[[:space:]])CCSwitch([[:space:]]|$)"

    private func ccSwitchRunning() -> Bool {
        runner.run("/usr/bin/pgrep", ["-if", ccSwitchProcessPattern], timeout: 2).status == 0
    }

    private func bridgePortOpen(_ port: Int) -> Bool {
        runner.run("/usr/bin/nc", ["-z", "127.0.0.1", String(port)], timeout: 2).status == 0
    }

    private func waitForPortClosed(_ port: Int, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline && bridgePortOpen(port) {
            Thread.sleep(forTimeInterval: 0.2)
        }
        return !bridgePortOpen(port)
    }

    private func waitForCcSwitchStopped(timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline && ccSwitchRunning() {
            Thread.sleep(forTimeInterval: 0.2)
        }
        return !ccSwitchRunning()
    }

    private func stopCcSwitch() -> Bool {
        _ = runner.run("/usr/bin/osascript", ["-e", "tell application \"CC Switch\" to quit"], timeout: 8)
        if waitForCcSwitchStopped(timeout: 3) && waitForPortClosed(15721, timeout: 3) {
            return true
        }

        _ = runner.run("/usr/bin/pkill", ["-TERM", "-if", ccSwitchProcessPattern], timeout: 3)
        if !waitForCcSwitchStopped(timeout: 3) {
            _ = runner.run("/usr/bin/pkill", ["-KILL", "-if", ccSwitchProcessPattern], timeout: 3)
        }
        let stopped = waitForCcSwitchStopped(timeout: 3)
        let portClosed = waitForPortClosed(15721, timeout: 3)
        return stopped && portClosed
    }

    // MARK: Provider/auth switch repair (read-only detection + bounded bound restart)

    // Process identity of the editor-hosted Codex backend(s): PID plus start time, so a
    // reload (a fresh identity) can be told apart from the still-running old backend.
    // Read-only; used only to withdraw the restart reminder.
    func codexProcessSignature() -> String {
        let result = runner.run("/bin/ps", ["-ax", "-o", "pid=,lstart=,comm="], timeout: 3)
        guard result.status == 0 else { return "" }
        var entries: [String] = []
        for line in result.output.split(separator: "\n") {
            let fields = line.split(separator: " ", omittingEmptySubsequences: true)
            guard fields.count >= 7 else { continue }
            let pid = String(fields[0])
            let started = fields[1...5].map(String.init).joined(separator: " ")
            let command = fields[6...].map(String.init).joined(separator: " ")
            if (command as NSString).lastPathComponent == "codex" {
                entries.append(pid + "@" + started)
            }
        }
        return entries.sorted().joined(separator: ",")
    }

    // Read-only: the repair is provably needed when the pinned custom provider
    // requires OpenAI auth but ~/.codex/auth.json has no live ChatGPT credential.
    // Never writes auth.json and never logs token values.
    func isThirdPartyAuthRepairNeeded() -> Bool {
        let configPath = "\(paths.home)/.codex/config.toml"
        guard let config = try? String(contentsOfFile: configPath, encoding: .utf8) else { return false }
        guard config.range(of: "(?m)^\\s*model_provider\\s*=\\s*[\"']custom[\"']", options: .regularExpression) != nil else { return false }
        guard config.range(of: "(?m)^\\s*requires_openai_auth\\s*=\\s*true", options: .regularExpression) != nil else { return false }
        return !hasLiveChatGptCredential()
    }

    private func hasLiveChatGptCredential() -> Bool {
        let authPath = "\(paths.home)/.codex/auth.json"
        guard let data = FileManager.default.contents(atPath: authPath),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        if let access = json["access_token"] as? String, !access.isEmpty { return true }
        if let refresh = json["refresh_token"] as? String, !refresh.isEmpty { return true }
        if let tokens = json["tokens"] as? [String: Any] {
            if let access = tokens["access_token"] as? String, !access.isEmpty { return true }
            if let refresh = tokens["refresh_token"] as? String, !refresh.isEmpty { return true }
        }
        return false
    }

    // Bind ONLY the currently-running CC Switch app instance. The path comes from
    // the live NSRunningApplication (never system discovery, never a remembered or
    // default install path, never persisted). Returns nil when CC Switch is not
    // running, in which case the repair must abort.
    func boundCcSwitchAppPath() -> String? {
        let pattern = "CC[ _-]*Switch|CCSwitch"
        let options: String.CompareOptions = [.regularExpression, .caseInsensitive]
        for app in NSWorkspace.shared.runningApplications {
            let name = app.localizedName ?? ""
            let bundleName = app.bundleURL?.lastPathComponent ?? ""
            let base = bundleName.hasSuffix(".app") ? String(bundleName.dropLast(4)) : bundleName
            if name.range(of: pattern, options: options) != nil || base.range(of: pattern, options: options) != nil {
                if let path = app.bundleURL?.path, FileManager.default.fileExists(atPath: path) {
                    return path
                }
            }
        }
        return nil
    }

    // The ONLY new CC Switch stop+start path on macOS. Restarts the already-bound
    // live instance once, bounded and loop-free: graceful quit then bounded force,
    // wait :15721 closed, relaunch the SAME bound path by explicit location (never
    // by name discovery), wait :15721 up, short settle for auth.json. Any failure
    // or timeout returns false (no retry).
    func restartBoundCcSwitchInstanceOnce(_ boundPath: String) -> Bool {
        guard FileManager.default.fileExists(atPath: boundPath) else { return false }
        _ = stopCcSwitch()
        guard waitForCcSwitchStopped(timeout: 6) else { return false }
        guard runner.run("/usr/bin/open", [boundPath], timeout: 10).status == 0 else { return false }
        let deadline = Date().addingTimeInterval(20)
        while Date() < deadline && !bridgePortOpen(15721) { Thread.sleep(forTimeInterval: 0.25) }
        guard bridgePortOpen(15721) else { return false }
        Thread.sleep(forTimeInterval: 1.5)
        return true
    }

    func uninstall() -> Bool {
        runner.run("/bin/bash", [paths.uninstall, "--confirmed"]).status == 0
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
    private var timer: Timer?
    private var thirdPartyBlockedNotified = false
    // Provider/auth switch repair state (macOS parity with the Windows launcher):
    // lastRouteKey gates the repair to a real switch edge, repairDoneKey is the
    // one-shot latch per route key, repairInProgress mutes the proxy-down alert
    // during the expected :15721 drop.
    private var lastRouteKey: String?
    private var repairInProgress = false
    private var repairDoneKey: String?
    // Deferred reconciliation (parity with Windows): when a third-party switch's
    // repair is suppressed by the cooldown or an open circuit, remember its key and
    // re-attempt once the route settles and the guard clears, so a rate-limited
    // switch is never silently dropped (which would leave CC Switch unrepaired).
    private var pendingRepairReconcileKey: String?
    // Flap circuit breaker (parity with the Windows launcher): a route that keeps
    // flipping (official<->third-party) must not repeatedly trigger the disruptive
    // repair restart, so repairs are rate limited and paused once flapping is seen.
    private var observedRouteKey: String?
    private var routeStableSince: Date?
    private var lastRepairRestartAt: Date?
    private var suppressedRepairCount = 0
    private var repairCircuitOpen = false
    private let repairCooldownSeconds: TimeInterval = 8
    private let repairFlapThreshold = 3
    private let repairFlapSettleSeconds: TimeInterval = 15

    // Durable "restart Codex" reminder (Windows parity). An editor-hosted Codex backend
    // is never terminated, so a switch only takes effect after the user reloads Codex.
    // The menu bar icon, its tooltip and a bold menu line keep the reminder visible
    // until the Codex process identity actually changes; a modal alert interrupts once
    // per switch edge on top of that.
    private var pendingCodexRestartReason = ""
    private var pendingCodexProcessSignature = ""
    private var lastPendingRestartCheckAt = Date.distantPast
    private var restartDialogOpen = false
    private var pendingRestartMenuItem: NSMenuItem?
    private var observedRouteForReminder = "none"
    private var reminderBaselineDone = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "link", accessibilityDescription: "CodexBridge")
        statusItem.button?.image?.isTemplate = true
        buildMenu()
        refreshStatus()
        ensureBridgeOnLaunch()
        // Added to the modal-panel run loop mode as well, so the poll keeps running while
        // the restart dialog is up (Windows parity: its WinForms timer keeps ticking
        // inside the modal message loop). Without this, a Codex reload during the dialog
        // would not withdraw the reminder until the dialog is dismissed.
        let statusTimer = Timer(timeInterval: 5, repeats: true) { [weak self] _ in self?.refreshStatus() }
        RunLoop.main.add(statusTimer, forMode: .common)
        RunLoop.main.add(statusTimer, forMode: .modalPanel)
        timer = statusTimer
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
        // Bold reminder line, hidden until a switch needs a Codex reload. Mirror of the
        // Windows launcher's persistent menu line.
        let reminder = NSMenuItem(title: controller.copy.text("Restart Codex to apply", "请重启 Codex 以生效"), action: nil, keyEquivalent: "")
        reminder.isHidden = true
        reminder.attributedTitle = NSAttributedString(string: reminder.title, attributes: [.font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)])
        pendingRestartMenuItem = reminder
        menu.addItem(reminder)
        menu.addItem(.separator())
        add(menu, "Ensure Bridge Running", #selector(ensureBridge))
        add(menu, "Restart Bridge", #selector(restartBridge))
        add(menu, "Restart Codex", #selector(restartCodex))
        menu.addItem(.separator())
        add(menu, "Open Bridge Log", #selector(openBridgeLog))
        add(menu, "Open Watcher Log", #selector(openWatcherLog))
        add(menu, "Open Launcher Log", #selector(openLauncherLog))
        add(menu, "Open Log Folder", #selector(openLogFolder))
        add(menu, "Check for Updates...", #selector(manualCheckForUpdates))
        menu.addItem(.separator())
        add(menu, "Exit CodexBridge...", #selector(exitCodexBridge))
        add(menu, "Uninstall CodexBridge...", #selector(uninstall))
        statusItem.menu = menu
    }

    private func add(_ menu: NSMenu, _ english: String, _ selector: Selector) {
        let chinese: [String: String] = ["Ensure Bridge Running": "确保 Bridge 运行", "Restart Bridge": "重启 Bridge", "Restart Codex": "重启 Codex", "Open Bridge Log": "打开 Bridge 日志", "Open Watcher Log": "打开 Watcher 日志", "Open Launcher Log": "打开 Launcher 日志", "Open Log Folder": "打开日志目录", "Check for Updates...": "检查更新...", "Exit CodexBridge...": "退出 CodexBridge...", "Uninstall CodexBridge...": "卸载 CodexBridge..."]
        menu.addItem(NSMenuItem(title: controller.copy.text(english, chinese[english] ?? english), action: selector, keyEquivalent: ""))
    }

    private func ensureBridgeOnLaunch() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            let result = self.controller.ensureBridge()
            DispatchQueue.main.async {
                if result.status != 0 {
                    self.notifyBridgeStartFailure(result.output)
                }
                self.refreshStatus()
            }
        }
    }

    private func refreshStatus() {
        let value = controller.status()
        statusLabel.title = controller.copy.text("Status: \(value.state.rawValue)", "状态：\(value.state == .running ? "运行中" : value.state == .stopped ? "已停止" : "未知")")
        if value.thirdPartyBlocked {
            routeLabel.title = controller.copy.text("Route: Third-party unavailable (open CC Switch)", "路由：第三方不可用（请打开 CC Switch）")
            if !thirdPartyBlockedNotified && !repairInProgress {
                thirdPartyBlockedNotified = true
                notify(controller.copy.text("Third-party route is active but the CC Switch local proxy (127.0.0.1:15721) is unreachable. Please open CC Switch; CodexBridge will not revive it on a proxy drop or after you close it.", "当前为第三方路由，但连不上 CC Switch 本地代理（127.0.0.1:15721）。请打开 CC Switch；CodexBridge 不会因掉线或你关闭而后台复活它。"))
            }
        } else {
            thirdPartyBlockedNotified = false
            routeLabel.title = controller.copy.text("Route: \(value.route)", "路由：\(value.route == "Official" ? "官方" : value.route == "Third-party" ? "第三方" : "未知")")
        }
        if let model = value.model, !model.isEmpty {
            if modelLabel == nil { modelLabel = NSMenuItem(title: "", action: nil, keyEquivalent: ""); statusItem.menu?.insertItem(modelLabel!, at: 3) }
            modelLabel?.title = controller.copy.text("Model: \(model)", "模型：\(model)")
        } else if let item = modelLabel, let index = statusItem.menu?.index(of: item), index >= 0 {
            statusItem.menu?.removeItem(at: index); modelLabel = nil
        }
        checkRouteEdgeReminder(value)
        checkProviderSwitchRepair(value)
        checkPendingRestartApplied()
    }

    // Provider/auth switch repair (macOS parity with the Windows launcher).
    // Edge-triggered: every real third-party switch edge restarts the already
    // bound live CC Switch instance once (bounded, loop-free, at most once per
    // route key), then asks the user to reload Codex. It never terminates an
    // editor-hosted Codex backend, never revives CC Switch on a proxy drop or
    // after the user closes it, and never discovers or launches it from a
    // remembered or default path.
    private func checkProviderSwitchRepair(_ value: BridgeStatus) {
        // Key the switch edge on the route MODEL -- the provider identity that actually
        // changes. Runtime evidence on Windows proved the sidecar's source_path is
        // CONSTANT across providers (CC Switch writes them all into one catalog file), so
        // route_model is the correct discriminator for Official -> third-party and
        // third-party -> third-party. Mirrors the Windows launcher.
        let providerId = value.model ?? ""
        // Flap circuit breaker: measure route stability by the observed key, and
        // re-arm the circuit only after the route has stayed stable long enough.
        let currentKey = value.route == "Third-party" ? ("third-party|" + providerId) : (value.route == "Official" ? "official" : "unknown")
        if currentKey != observedRouteKey { observedRouteKey = currentKey; routeStableSince = Date() }
        if repairCircuitOpen, let since = routeStableSince, Date().timeIntervalSince(since) >= repairFlapSettleSeconds {
            repairCircuitOpen = false; suppressedRepairCount = 0
        }

        // Leaving a third-party route re-arms the one-shot latch, and so does every
        // genuine third-party switch edge below, so returning to the SAME provider
        // (DeepSeek -> Official -> DeepSeek) is repaired again instead of being
        // blocked by a stale latch.
        guard value.route == "Third-party" else { lastRouteKey = nil; repairDoneKey = nil; pendingRepairReconcileKey = nil; return }
        let key = "third-party|" + providerId
        defer { lastRouteKey = key }
        // A genuine new edge, or a deferred reconciliation of a switch whose repair was
        // suppressed earlier. Reconciliation bypasses the same-key guard so a
        // rate-limited switch is eventually applied instead of silently dropped.
        let isReconcile = (pendingRepairReconcileKey == key)
        if key == lastRouteKey && !isReconcile { return }
        // New third-party switch edge: re-arm the one-shot latch for this switch.
        repairDoneKey = nil
        if repairInProgress { return }
        if repairCircuitOpen {
            // Defer to reconciliation once the circuit re-arms.
            pendingRepairReconcileKey = key
            return
        }
        // Edge-triggered repair: EVERY genuine third-party switch edge restarts the
        // bound CC Switch once. Gating on a point-in-time credential read raced with
        // CC Switch's own auth.json write and silently skipped the repair on a repeat
        // switch to the SAME provider, so the credential check is no longer the
        // trigger; it is still used below to decide whether reloading Codex is safe
        // when CC Switch cannot be repaired.
        // Rate limit the disruptive repair: a flapping route re-arrives inside the
        // cooldown, so it is suppressed; after repeated flaps the circuit opens.
        if let last = lastRepairRestartAt, Date().timeIntervalSince(last) < repairCooldownSeconds {
            // Only genuine switch edges count toward the flap threshold; a deferred
            // reconcile retry simply waits out the cooldown instead of tripping it.
            if !isReconcile {
                suppressedRepairCount += 1
                if suppressedRepairCount >= repairFlapThreshold {
                    repairCircuitOpen = true
                    notify(controller.copy.text("Route flapping detected: CodexBridge paused automatic repair restarts to avoid a loop. Reopen CC Switch, then switch the provider once more.", "检测到路由抖动：CodexBridge 已暂停自动修复重启以避免循环。请重新打开 CC Switch，然后再切换一次 Provider。"))
                }
            }
            pendingRepairReconcileKey = key
            return
        }
        guard let boundPath = controller.boundCcSwitchAppPath() else {
            // No live CC Switch to repair. When the credential is genuinely absent the
            // user must reopen CC Switch, so defer the edge for reconciliation;
            // otherwise there is nothing to repair and the route can stand.
            if controller.isThirdPartyAuthRepairNeeded() { pendingRepairReconcileKey = key }
            else { pendingRepairReconcileKey = nil }
            return
        }
        pendingRepairReconcileKey = nil
        repairInProgress = true
        suppressedRepairCount = 0
        lastRepairRestartAt = Date()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            let ok = self.controller.restartBoundCcSwitchInstanceOnce(boundPath)
            // CC Switch was repaired. Codex must reload to pick up the restored
            // credential, but on macOS Codex runs as an editor-hosted (VS Code/Cursor)
            // or CLI backend: terminating it leaves the editor on a "click to restart"
            // page and, because route switches repeat, CodexBridge would keep killing
            // the respawning backend and make that page flicker. Never terminate it
            // here; ask the user to restart Codex so the editor owns its own lifecycle.
            DispatchQueue.main.async {
                self.repairInProgress = false
                self.repairDoneKey = key
                if ok {
                    self.raiseRestartCodexReminder(self.controller.copy.text("Provider switch repaired: CC Switch was restarted once", "已修复 Provider 切换：CC Switch 已重启一次"))
                } else {
                    self.notify(self.controller.copy.text("Provider switch repair failed: please reopen CC Switch, then switch the provider again.", "Provider 切换修复失败：请重新打开 CC Switch，然后再次切换 Provider。"))
                }
                self.refreshStatus()
            }
        }
    }

    // Windows parity: EVERY genuine switch edge asks the user to reload Codex. The
    // third-party path below runs the repair and raises the reminder itself; this covers
    // the official edge, where nothing else would tell the user that the config changed.
    private func checkRouteEdgeReminder(_ value: BridgeStatus) {
        let kind = value.route == "Official" ? "official" : (value.route == "Third-party" ? "third-party" : "none")
        let previous = observedRouteForReminder
        observedRouteForReminder = kind
        // The first observation after launch only sets the baseline (no edge yet).
        if !reminderBaselineDone { reminderBaselineDone = true; return }
        if kind == "official" && previous != "official" {
            raiseRestartCodexReminder(controller.copy.text("Official route / ChatGPT account reload", "官方路由 / ChatGPT 账号重新加载"))
        }
    }

    // Windows parity: the reminder is withdrawn only when the Codex process identity
    // really changed (the user reloaded it), never merely because the route changed.
    private func checkPendingRestartApplied() {
        guard !pendingCodexRestartReason.isEmpty else { return }
        // Throttled: refreshStatus runs on a 5 s timer and enumerating processes is not free.
        if Date().timeIntervalSince(lastPendingRestartCheckAt) < 2 { return }
        lastPendingRestartCheckAt = Date()
        let current = controller.codexProcessSignature()
        if current.isEmpty { return }                          // Codex is not up yet; keep waiting.
        if current == pendingCodexProcessSignature { return }  // Unchanged; the reminder still applies.
        logLauncher("Codex was reloaded by the user; clearing the persistent restart reminder (was: \(pendingCodexRestartReason)).")
        clearRestartCodexReminder()
    }

    private func raiseRestartCodexReminder(_ reason: String) {
        pendingCodexRestartReason = reason
        pendingCodexProcessSignature = controller.codexProcessSignature()
        statusItem.button?.image = NSImage(systemSymbolName: "exclamationmark.circle.fill", accessibilityDescription: "CodexBridge")
        statusItem.button?.image?.isTemplate = true
        statusItem.button?.toolTip = controller.copy.text("CodexBridge: restart Codex to apply the new provider", "CodexBridge：请重启 Codex 以应用新 Provider")
        pendingRestartMenuItem?.isHidden = false
        logLauncher("Persistent Codex-restart reminder raised; it stays in the menu bar until Codex is reloaded: \(reason)")
        // One alert at a time: later switches refresh the menu bar reminder behind it
        // instead of stacking dialogs. The modal run loop keeps running (modalPanel mode),
        // so the badge and the withdrawal check stay live while the alert blocks.
        if restartDialogOpen { return }
        restartDialogOpen = true
        defer { restartDialogOpen = false }
        showRestartCodexDialog()
    }

    private func clearRestartCodexReminder() {
        pendingCodexRestartReason = ""
        pendingCodexProcessSignature = ""
        statusItem.button?.image = NSImage(systemSymbolName: "link", accessibilityDescription: "CodexBridge")
        statusItem.button?.image?.isTemplate = true
        statusItem.button?.toolTip = nil
        pendingRestartMenuItem?.isHidden = true
    }

    private func showRestartCodexDialog() {
        let alert = NSAlert()
        alert.messageText = controller.copy.text("Restart Codex to apply", "请重启 Codex 以生效")
        alert.informativeText = controller.copy.text("Provider switched. Please restart Codex in your editor (VS Code/Cursor) to apply the new route.", "Provider 已切换。请在你的编辑器（VS Code/Cursor）中重启 Codex 以应用新路由。")
            + "\n\n"
            + controller.copy.text("Codex keeps the previous provider until it is reloaded. The menu bar warning stays until then, and this reminder returns on the next switch.", "重启前 Codex 仍使用旧 Provider。菜单栏警告会一直保留，下次切换 Provider 时也会再次提醒。")
        alert.alertStyle = .warning
        // Windows parity: the reminder must land on top of whatever the user is working
        // in, so the app is activated and the alert is pinned above normal windows.
        NSApplication.shared.activate(ignoringOtherApps: true)
        alert.window.level = .floating
        alert.runModal()
    }

    private func logLauncher(_ message: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        guard let data = "\(stamp) \(message)\n".data(using: .utf8) else { return }
        let path = controller.paths.launcherLog
        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            handle.closeFile()
        } else {
            try? data.write(to: URL(fileURLWithPath: path))
        }
    }

    private func notify(_ message: String) {
        let alert = NSAlert(); alert.messageText = "CodexBridge"; alert.informativeText = message; alert.alertStyle = .warning; alert.runModal()
    }

    // The manager reports why a start or restart failed on stderr ("Error: ..."),
    // and the runner merges stderr into the output. Show that reason instead of a
    // dead-end dialog, and record it in launcher.log for later diagnosis.
    private func bridgeStartFailureDetail(_ output: String) -> String {
        for line in output.split(separator: "\n") {
            if line.hasPrefix("Error: ") {
                return String(line.dropFirst("Error: ".count))
            }
        }
        return ""
    }

    private func notifyBridgeStartFailure(_ output: String) {
        notifyBridgeFailure(controller.copy.text("Could not start the Bridge.", "无法启动 Bridge。"), output: output)
    }

    private func notifyBridgeFailure(_ message: String, output: String) {
        let detail = bridgeStartFailureDetail(output)
        logLauncher("Bridge start/restart failed: \(detail.isEmpty ? output : detail)")
        let alert = NSAlert()
        alert.messageText = message
        var body = detail
        if !body.isEmpty { body += "\n\n" }
        body += controller.copy.text("Retry tries again; Open Bridge Log shows the recorded details.", "可以点“重试”再试一次；“打开 Bridge 日志”查看记录的详细原因。")
        alert.informativeText = body
        alert.alertStyle = .warning
        alert.addButton(withTitle: controller.copy.text("Retry", "重试"))
        alert.addButton(withTitle: controller.copy.text("Open Bridge Log", "打开 Bridge 日志"))
        alert.addButton(withTitle: controller.copy.text("Close", "关闭"))
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            let retry = controller.ensureBridge()
            if retry.status != 0 {
                notifyBridgeFailure(message, output: retry.output)
            } else {
                refreshStatus()
            }
        } else if response == .alertSecondButtonReturn {
            _ = controller.open(controller.paths.bridgeLog)
        }
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

    @objc private func ensureBridge() {
        let result = controller.ensureBridge()
        if result.status != 0 { notifyBridgeStartFailure(result.output) }
        refreshStatus()
    }

    @objc private func restartBridge() {
        let result = controller.restartBridge()
        if result.status != 0 { notifyBridgeFailure(controller.copy.text("Could not restart the Bridge.", "无法重启 Bridge。"), output: result.output) }
        refreshStatus()
    }
    @objc private func restartCodex() { if !controller.restartCodex() { notify(controller.copy.text("Codex was not running or could not be restarted.", "Codex 未运行或无法重启。")) } }
    @objc private func openBridgeLog() { _ = controller.open(controller.paths.bridgeLog) }
    @objc private func openWatcherLog() { _ = controller.open(controller.paths.watcherLog) }
    @objc private func openLauncherLog() { _ = controller.open(controller.paths.launcherLog) }
    @objc private func openLogFolder() { _ = controller.open(controller.paths.stateRoot) }
    @objc private func exitCodexBridge() {
        let alert = NSAlert(); alert.messageText = controller.copy.text("Exit CodexBridge?", "退出 CodexBridge？"); alert.informativeText = controller.copy.text("This will stop CodexBridge, the Bridge, and CC Switch. The watcher stays available and will start CodexBridge when you open CC Switch again.", "这将关闭 CodexBridge、Bridge 和 CC Switch。watcher 会继续运行，下次打开 CC Switch 时自动启动 CodexBridge。"); alert.alertStyle = .warning; alert.addButton(withTitle: controller.copy.text("Exit CodexBridge", "退出 CodexBridge")); alert.addButton(withTitle: controller.copy.text("Cancel", "取消")); configureNoAsDefaultButton(alert); if alert.runModal() == .alertFirstButtonReturn {
            let official = controller.status().route == "Official"
            if !controller.stopAll() {
                let message = official
                    ? controller.copy.text("Official handoff failed. Bridge remains running; no components were stopped.", "官方交接失败。Bridge 仍在运行，未停止任何组件。")
                    : controller.copy.text("Could not complete Exit CodexBridge. See the launcher log.", "无法完成退出 CodexBridge，请查看 Launcher 日志。")
                notify(message)
                return
            }
            NSApp.terminate(nil)
        }
    }

    @objc private func uninstall() {
        let alert = NSAlert(); alert.messageText = controller.copy.text("Uninstall CodexBridge?", "卸载 CodexBridge？"); alert.informativeText = controller.copy.text("This removes the Bridge app, runtime, logs, and launch agents. If Codex pointed at the local Bridge, its config is restored to the pre-install state or switched back to the direct Official route. Chat history is not removed.", "这会删除 Bridge 应用、运行时、日志和启动项。若 Codex 正指向本地 Bridge，其配置会恢复到安装前状态，或切回 Official 直连。聊天记录不会删除。"); alert.alertStyle = .warning; alert.addButton(withTitle: controller.copy.text("Uninstall", "卸载")); alert.addButton(withTitle: controller.copy.text("Cancel", "取消")); configureNoAsDefaultButton(alert); if alert.runModal() == .alertFirstButtonReturn { if !controller.uninstall() { notify(controller.copy.text("Uninstall failed. See the launcher log.", "卸载失败，请查看 Launcher 日志。")) } else { NSApp.terminate(nil) } }
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
