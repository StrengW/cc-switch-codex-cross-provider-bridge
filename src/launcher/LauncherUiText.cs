using System;
using System.Globalization;

namespace CodexBridgeLauncherApp
{
    internal sealed class LauncherUiText
    {
        private readonly bool chinese;
        private readonly bool traditional;

        internal LauncherUiText()
        {
            string cultureName = "";
            try { cultureName = CultureInfo.CurrentUICulture.Name ?? ""; } catch { }
            if (String.IsNullOrEmpty(cultureName))
            {
                try { cultureName = CultureInfo.InstalledUICulture.Name ?? ""; } catch { }
            }
            chinese = cultureName.StartsWith("zh", StringComparison.OrdinalIgnoreCase);
            traditional = cultureName.Equals("zh-TW", StringComparison.OrdinalIgnoreCase) ||
                          cultureName.Equals("zh-HK", StringComparison.OrdinalIgnoreCase) ||
                          cultureName.Equals("zh-MO", StringComparison.OrdinalIgnoreCase) ||
                          cultureName.StartsWith("zh-Hant", StringComparison.OrdinalIgnoreCase);
        }

        internal string T(string english)
        {
            if (!chinese) return english;
            switch (english)
            {
                case "Codex Bridge Launcher": return Z("CodexBridge 启动器", "CodexBridge 啟動器");
                case "Status: starting...": return Z("状态：正在启动...", "狀態：正在啟動...");
                case "Restart Codex": return Z("重启 Codex", "重新啟動 Codex");
                case "Ensure Bridge Running": return Z("确保 Bridge 运行", "確保 Bridge 執行");
                case "Pause automatic restarts": return Z("暂停自动重启", "暫停自動重新啟動");
                case "Open Installed App Folder": return Z("打开已安装程序目录", "開啟已安裝程式目錄");
                case "Open Bridge Runtime Log": return Z("打开 Bridge 运行日志", "開啟 Bridge 執行記錄");
                case "Open Bridge Startup Log": return Z("打开 Bridge 启动日志", "開啟 Bridge 啟動記錄");
                case "Open Launcher Log": return Z("打开 Launcher 日志", "開啟 Launcher 記錄");
                case "Open Log Folder": return Z("打开日志目录", "開啟記錄目錄");
                case "Check for Updates...": return Z("检查更新...", "檢查更新...");
                case "Exit CodexBridge...": return Z("退出 CodexBridge...", "退出 CodexBridge...");
                case "Uninstall CodexBridge...": return Z("卸载 CodexBridge...", "解除安裝 CodexBridge...");
                case "Starting / waiting for route...": return Z("正在启动/等待路由...", "正在啟動/等待路由...");
                case "Paused": return Z("已暂停", "已暫停");
                case "Watching provider switches": return Z("正在监视 Provider 切换", "正在監視 Provider 切換");
                case "Official": return Z("官方", "官方");
                case "Third-party": return Z("第三方", "第三方");
                case "unknown": return Z("未知", "未知");
                case "Provider switch complete": return Z("Provider 切换完成", "Provider 切換完成");
                case "Provider switch failed": return Z("Provider 切换失败", "Provider 切換失敗");
                case "CC Switch proxy restored": return Z("CC Switch 代理已恢复", "CC Switch 代理已恢復");
                case "CC Switch proxy unavailable": return Z("CC Switch 代理不可用", "CC Switch 代理無法使用");
                case "CodexBridge update available": return Z("CodexBridge 有可用更新", "CodexBridge 有可用更新");
                case "CodexBridge is up to date": return Z("CodexBridge 已是最新版本", "CodexBridge 已是最新版本");
                case "Could not check for updates": return Z("无法检查更新", "無法檢查更新");
                case "Open Latest Release": return Z("打开最新版本页面", "開啟最新版本頁面");
                case "Later": return Z("稍后", "稍後");
                case "Manual Codex restart": return Z("手动重启 Codex", "手動重新啟動 Codex");
                case "Ensure Bridge": return Z("确保 Bridge", "確保 Bridge");
                case "Bridge startup failed. Launcher is still running; open Launcher Log for details.": return Z("Bridge 启动失败。Launcher 仍在运行，请打开 Launcher 日志查看详情。", "Bridge 啟動失敗。Launcher 仍在執行，請開啟 Launcher 記錄查看詳情。");
                case "Ready. The CC Switch watcher starts with Windows and launches CodexBridge when CC Switch opens.": return Z("已就绪。CC Switch watcher 会随 Windows 启动，并在 CC Switch 打开时启动 CodexBridge。", "已就緒。CC Switch watcher 會隨 Windows 啟動，並在 CC Switch 開啟時啟動 CodexBridge。");
                case "codex_bridge_manager.ps1 not found next to the launcher.": return Z("启动器旁边找不到 codex_bridge_manager.ps1。", "啟動器旁邊找不到 codex_bridge_manager.ps1。");
                case "Third-party route unavailable: please open CC Switch.": return Z("第三方路由暂不可用：请打开 CC Switch。", "第三方路由暫時無法使用：請開啟 CC Switch。");
                case "Third-party route unavailable: {0}": return Z("第三方路由不可用：{0}", "第三方路由無法使用：{0}");
                case "Route: {0}": return Z("路由：{0}", "路由：{0}");
                case "Switching: {0}": return Z("正在切换：{0}", "正在切換：{0}");
                case "{0} is ready. Bridge remained resident.": return Z("{0} 已就绪。Bridge 继续常驻。", "{0} 已就緒。Bridge 繼續常駐。");
                case "Third-party route {0} is available again.": return Z("第三方路由 {0} 已恢复可用。", "第三方路由 {0} 已恢復可用。");
                case "Exit CodexBridge cancelled": return Z("已取消退出 CodexBridge", "已取消退出 CodexBridge");
                case "Official handoff failed. Bridge remains running; no components were stopped.": return Z("Official 直连切换失败。Bridge 仍在运行，未停止任何组件。", "Official 直連切換失敗。Bridge 仍在執行，未停止任何元件。");
                case "{0} failed: {1}": return Z("{0} 失败：{1}", "{0} 失敗：{1}");
                case "Current version: {0}.": return Z("当前版本：{0}。", "目前版本：{0}。");
                case "The latest release could not be checked. {0}": return Z("无法获取最新 Release。{0}", "無法取得最新 Release。{0}");
                case "If this keeps failing, a proxy or firewall is usually blocking api.github.com.": return Z("如果反复失败，通常是代理或防火墙拦截了 api.github.com。", "如果反覆失敗，通常是代理或防火牆攔截了 api.github.com。");
                case "Version {0} is available (current {1}). Open the GitHub Release page now?": return Z("发现新版本 {0}（当前为 {1}）。现在打开 GitHub Release 页面吗？", "發現新版本 {0}（目前為 {1}）。現在開啟 GitHub Release 頁面嗎？");
                case "Uninstaller not found:\r\n{0}": return Z("找不到卸载程序：\r\n{0}", "找不到解除安裝程式：\r\n{0}");
                case "Could not start the CodexBridge uninstaller.\r\n\r\n{0}": return Z("无法启动 CodexBridge 卸载程序。\r\n\r\n{0}", "無法啟動 CodexBridge 解除安裝程式。\r\n\r\n{0}");
                case "Could not install Codex Bridge into %LOCALAPPDATA%\\CodexProviderBridge\\app.\r\n\r\n{0}": return Z("无法将 CodexBridge 安装到 %LOCALAPPDATA%\\CodexProviderBridge\\app。\r\n\r\n{0}", "無法將 CodexBridge 安裝到 %LOCALAPPDATA%\\CodexProviderBridge\\app。\r\n\r\n{0}");
                case "Codex Bridge Launcher is already running in the system tray.": return Z("CodexBridge 启动器已在系统托盘中运行。", "CodexBridge 啟動器已在系統匣中執行。");
                case "Codex Bridge Launcher crashed. See %LOCALAPPDATA%\\CodexProviderBridge\\launcher-crash.log": return Z("CodexBridge 启动器崩溃，请查看 %LOCALAPPDATA%\\CodexProviderBridge\\launcher-crash.log", "CodexBridge 啟動器當機，請查看 %LOCALAPPDATA%\\CodexProviderBridge\\launcher-crash.log");
                case "Repairing provider switch (restarting CC Switch once)...": return Z("正在修复 Provider 切换（重启 CC Switch 一次）...", "正在修復 Provider 切換（重新啟動 CC Switch 一次）...");
                case "Provider switch repair": return Z("Provider 切换修复", "Provider 切換修復");
                case "Repair failed: please reopen CC Switch, then switch the provider again.": return Z("修复失败：请重新打开 CC Switch，然后再次切换 Provider。", "修復失敗：請重新開啟 CC Switch，然後再次切換 Provider。");
                case "Route flapping detected": return Z("检测到路由抖动", "偵測到路由抖動");
                case "The provider route kept flipping, so CodexBridge paused automatic Codex restarts to avoid a restart loop. Reopen CC Switch, then switch the provider once more; CodexBridge resumes automatically.": return Z("Provider 路由反复抖动，CodexBridge 已暂停自动重启 Codex 以避免重启循环。请重新打开 CC Switch，然后再切换一次 Provider；CodexBridge 会自动恢复。", "Provider 路由反覆抖動，CodexBridge 已暫停自動重新啟動 Codex 以避免重新啟動循環。請重新開啟 CC Switch，然後再切換一次 Provider；CodexBridge 會自動恢復。");
                case "Restart Codex to apply": return Z("请重启 Codex 以生效", "請重新啟動 Codex 以生效");
                case "Provider switched. Please restart Codex in your editor (VS Code/Cursor) to apply the new route.": return Z("Provider 已切换。请在你的编辑器（VS Code/Cursor）中重启 Codex 以应用新路由。", "Provider 已切換。請在你的編輯器（VS Code/Cursor）中重新啟動 Codex 以套用新路由。");
                default: return english;
            }
        }

        internal string F(string template, params object[] args)
        {
            return String.Format(T(template), args);
        }

        internal string Status(string value)
        {
            return chinese ? (traditional ? "狀態：" : "状态：") + value : "Status: " + value;
        }

        internal string Route(string kind, string model)
        {
            string prefix = kind == "official" ? T("Official") : kind == "third-party" ? T("Third-party") : T("unknown");
            return String.IsNullOrEmpty(model) ? prefix : prefix + " / " + model;
        }

        internal string FallbackRoute(string model)
        {
            return Route("third-party", model);
        }

        private string Z(string simplified, string traditional)
        {
            return this.traditional ? traditional : simplified;
        }
    }
}
