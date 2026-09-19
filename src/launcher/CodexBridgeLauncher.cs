using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace CodexBridgeLauncherApp
{
    internal sealed class RouteSnapshot
    {
        public string Kind = "";
        public string Model = "";
        public string Source = "";
        public string Key = "";
    }

    internal sealed class LauncherContext : ApplicationContext
    {
        private const string LauncherVersion = "1.7.9-standard-uninstall";
        private readonly object sync = new object();
        private readonly object bridgeLifecycleSync = new object();
        private readonly object bridgeEnsureProcessSync = new object();
        private Process bridgeEnsureProcess;
        private readonly NotifyIcon tray;
        private readonly Icon launcherIcon;
        private readonly System.Windows.Forms.Timer pollTimer;
        private readonly Mutex mutex;
        private readonly string baseDir;
        private readonly string userProfile;
        private readonly string codexHome;
        private readonly string routeStatePath;
        private readonly string statePath;
        private readonly string logDir;
        private readonly string launcherRuntimeDir;
        private readonly string launcherLog;
        private readonly string bridgeStdoutLog;
        private readonly string bridgeStderrLog;
        private readonly string managerScript;
        private readonly Dictionary<string, string> state = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private string lastHandledKey = "";
        private string pendingKey = "";
        private DateTime pendingSinceUtc = DateTime.MinValue;
        private bool baselineInitialized;
        private bool handling;
        private bool thirdPartyProxyRecoveryQueued;
        private DateTime nextThirdPartyProxyHealthUtc = DateTime.MinValue;
        private volatile bool exiting;
        private ToolStripMenuItem statusItem;
        private ToolStripMenuItem pauseItem;
        private ToolStripMenuItem startupItem;
        private bool paused;
        private readonly string installDir;
        private const string StartupRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValueName = "CodexBridgeLauncher";
        public LauncherContext(Mutex singleInstanceMutex)
        {
            mutex = singleInstanceMutex;
            baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            codexHome = Path.Combine(userProfile, ".codex");
            routeStatePath = Path.Combine(codexHome, "cpb-active-model-catalog.json.source.json");
            statePath = Path.Combine(codexHome, "cpb-launcher-state.json");
            logDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge");
            installDir = Path.Combine(logDir, "app");
            launcherRuntimeDir = Path.Combine(logDir, "launcher-runtime");
            launcherLog = Path.Combine(logDir, "launcher.log");
            bridgeStdoutLog = Path.Combine(logDir, "bridge-stdout.log");
            bridgeStderrLog = Path.Combine(logDir, "bridge-stderr.log");
            managerScript = Path.Combine(baseDir, "codex_bridge_manager.ps1");

            Directory.CreateDirectory(codexHome);
            Directory.CreateDirectory(logDir);
            Directory.CreateDirectory(launcherRuntimeDir);
            // Never keep the package/update directory as this process current directory.
            // Child processes (especially CC Switch) can inherit cwd and then hold a
            // directory handle that prevents the user from replacing/deleting the package.
            try { Directory.SetCurrentDirectory(launcherRuntimeDir); } catch { }
            LoadState();

            launcherIcon = LoadLauncherIcon();
            tray = new NotifyIcon();
            tray.Icon = launcherIcon;
            tray.Text = "Codex Bridge Launcher";
            tray.Visible = true;
            tray.ContextMenuStrip = BuildMenu();
            tray.DoubleClick += delegate { OpenLogFolder(); };

            Log("Launcher " + LauncherVersion + " started. base=" + baseDir + "; cwd=" + Environment.CurrentDirectory);
            Log("Policy: Bridge remains the compatibility layer while CodexBridge is running. Third-party => keep CC Switch proxy :15721 supervised and restart Codex only on actual route changes; Official => CC Switch may stay closed. Exit Everything performs an explicit full shutdown after confirmation, without rewriting config.toml or restarting Codex.");
            Log("Tray initialized; startup background failures are isolated from the UI process.");
            bool residentAutoStartEnabled = IsStartupRegistered();
            Log("Resident CodexBridge auto-start: " + (residentAutoStartEnabled ? "enabled" : "disabled") + "; installed_app=" + installDir);
            // Keep the lightweight CC Switch trigger watcher independent from the tray/Bridge
            // lifetime. Exit Everything may stop the functional components, but opening CC Switch
            // later should relaunch CodexBridge without requiring Start CodexBridge.cmd again.
            Program.EnsureCcSwitchWatcherRunning(Application.ExecutablePath);
            Log("CC Switch trigger watcher ensured; it remains armed across Exit Everything.");

            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    EnsureBridgeRunning();
                }
                catch (Exception ex)
                {
                    // A bridge-manager startup failure must never kill the tray launcher.
                    // On .NET Framework, an unhandled ThreadPool exception terminates the
                    // whole process; keep the launcher alive so the user can inspect logs
                    // or retry from the tray.
                    Log("ERROR startup bridge ensure: " + ex);
                    try { Balloon("Codex Bridge Launcher", "Bridge startup failed. Launcher is still running; open Launcher Log for details.", ToolTipIcon.Error); } catch { }
                }

                try
                {
                    RememberLaunchTargets();
                }
                catch (Exception ex)
                {
                    Log("WARNING startup launch-target discovery failed: " + ex);
                }
            });

            pollTimer = new System.Windows.Forms.Timer();
            pollTimer.Interval = 400;
            pollTimer.Tick += PollTimerTick;
            pollTimer.Start();

            UpdateStatusText("Starting / waiting for route...");
            Balloon("Codex Bridge Launcher", residentAutoStartEnabled
                ? "Ready. CodexBridge is configured to start with Windows; provider switching and compatibility supervision are active."
                : "Ready. CodexBridge Windows auto-start is disabled; you can enable it from the tray if desired.", ToolTipIcon.Info);
        }


        private static Icon LoadLauncherIcon()
        {
            try
            {
                Icon extracted = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                if (extracted != null)
                {
                    Icon clone = (Icon)extracted.Clone();
                    extracted.Dispose();
                    return clone;
                }
            }
            catch { }
            try { return (Icon)SystemIcons.Application.Clone(); }
            catch { return SystemIcons.Application; }
        }

        private ContextMenuStrip BuildMenu()
        {
            ContextMenuStrip menu = new ContextMenuStrip();
            statusItem = new ToolStripMenuItem("Status: starting...");
            statusItem.Enabled = false;
            menu.Items.Add(statusItem);
            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem restartCodex = new ToolStripMenuItem("Restart Codex");
            restartCodex.Click += delegate { QueueManualAction("Manual Codex restart", delegate { RestartCodex("manual tray action"); }); };
            menu.Items.Add(restartCodex);

            ToolStripMenuItem restartCc = new ToolStripMenuItem("Restart CC Switch");
            restartCc.Click += delegate { QueueManualAction("Manual CC Switch restart", delegate { RestartCcSwitch(); }); };
            menu.Items.Add(restartCc);

            ToolStripMenuItem ensureBridge = new ToolStripMenuItem("Ensure Bridge Running");
            ensureBridge.Click += delegate { QueueManualAction("Ensure Bridge", EnsureBridgeRunning); };
            menu.Items.Add(ensureBridge);

            pauseItem = new ToolStripMenuItem("Pause automatic restarts");
            pauseItem.CheckOnClick = true;
            pauseItem.CheckedChanged += delegate
            {
                paused = pauseItem.Checked;
                Log(paused ? "Automatic restart watcher paused." : "Automatic restart watcher resumed.");
                UpdateStatusText(paused ? "Paused" : "Watching provider switches");
            };
            menu.Items.Add(pauseItem);

            startupItem = new ToolStripMenuItem("Start CodexBridge with Windows");
            startupItem.CheckOnClick = true;
            startupItem.Checked = IsStartupRegistered();
            startupItem.CheckedChanged += delegate
            {
                try
                {
                    SetStartupRegistration(startupItem.Checked);
                    Log("Resident CodexBridge auto-start " + (startupItem.Checked ? "enabled." : "disabled."));
                    Balloon("Codex Bridge Launcher", startupItem.Checked
                        ? "Enabled. CodexBridge starts at Windows sign-in so Official conversations work even when CC Switch is closed."
                        : "Disabled. CodexBridge will no longer start automatically at Windows sign-in.", ToolTipIcon.Info);
                }
                catch (Exception ex)
                {
                    Log("ERROR changing autostart registration: " + ex);
                    Balloon("Codex Bridge Launcher", "Could not change Windows startup setting: " + ex.Message, ToolTipIcon.Error);
                }
            };
            menu.Items.Add(startupItem);

            ToolStripMenuItem openAppFolder = new ToolStripMenuItem("Open Installed App Folder");
            openAppFolder.Click += delegate { OpenFolder(installDir); };
            menu.Items.Add(openAppFolder);

            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem openBridge = new ToolStripMenuItem("Open Bridge Runtime Log");
            openBridge.Click += delegate { OpenTextFile(bridgeStderrLog); };
            menu.Items.Add(openBridge);

            ToolStripMenuItem openBridgeStartup = new ToolStripMenuItem("Open Bridge Startup Log");
            openBridgeStartup.Click += delegate { OpenTextFile(bridgeStdoutLog); };
            menu.Items.Add(openBridgeStartup);

            ToolStripMenuItem openLauncher = new ToolStripMenuItem("Open Launcher Log");
            openLauncher.Click += delegate { OpenTextFile(launcherLog); };
            menu.Items.Add(openLauncher);

            ToolStripMenuItem openFolder = new ToolStripMenuItem("Open Log Folder");
            openFolder.Click += delegate { OpenLogFolder(); };
            menu.Items.Add(openFolder);

            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem exit = new ToolStripMenuItem("Exit Everything...");
            exit.Click += delegate { ExitLauncher(); };
            menu.Items.Add(exit);

            ToolStripMenuItem uninstall = new ToolStripMenuItem("Uninstall CodexBridge...");
            uninstall.Click += delegate { UninstallCodexBridge(); };
            menu.Items.Add(uninstall);
            return menu;
        }

        private string PreferredStartupExe()
        {
            string installedExe = Path.Combine(installDir, "CodexBridgeLauncher.exe");
            if (File.Exists(installedExe)) return installedExe;
            return Application.ExecutablePath;
        }

        private bool IsStartupRegistered()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(StartupRegistryPath, false))
                {
                    if (key == null) return false;
                    object raw = key.GetValue(StartupValueName);
                    if (raw == null) return false;
                    string value = raw.ToString() ?? "";
                    string exe = PreferredStartupExe();
                    return value.IndexOf(exe, StringComparison.OrdinalIgnoreCase) >= 0 &&
                        value.IndexOf("--autostart", StringComparison.OrdinalIgnoreCase) >= 0;
                }
            }
            catch { return false; }
        }

        private void SetStartupRegistration(bool enabled)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupRegistryPath))
            {
                if (key == null) throw new Exception("Could not open the current-user Startup registry key.");
                if (enabled)
                {
                    string exe = PreferredStartupExe();
                    key.SetValue(StartupValueName, "\"" + exe + "\" --autostart", RegistryValueKind.String);
                    Program.StopCcSwitchWatcher();
                }
                else
                {
                    key.DeleteValue(StartupValueName, false);
                    Program.StopCcSwitchWatcher();
                }
            }
        }

        private void OpenFolder(string path)
        {
            try
            {
                Directory.CreateDirectory(path);
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "explorer.exe";
                psi.Arguments = "\"" + path + "\"";
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            catch (Exception ex) { Log("ERROR opening folder: " + ex.Message); }
        }

        private void QueueManualAction(string name, Action action)
        {
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    if (exiting) return;
                    Log(name + " requested.");
                    if (exiting) return;
                    action();
                }
                catch (Exception ex)
                {
                    Log("ERROR " + name + ": " + ex.Message);
                    Balloon("Codex Bridge Launcher", name + " failed: " + ex.Message, ToolTipIcon.Error);
                }
            });
        }

        private void PollTimerTick(object sender, EventArgs e)
        {
            if (exiting || paused) return;
            RouteSnapshot route = ReadRouteSnapshot();
            if (route == null) return;

            if (!baselineInitialized)
            {
                baselineInitialized = true;
                lastHandledKey = route.Key;
                SaveStateValue("last_handled_route", lastHandledKey);
                pendingKey = "";
                UpdateStatusText("Route: " + FriendlyRoute(route));
                Log("Initial route: " + route.Key + ". No restart triggered.");
                // A launcher started while a third-party route is already selected
                // should also heal a previously closed CC Switch proxy.
                SuperviseThirdPartyProxy(route);
                return;
            }

            if (route.Key == lastHandledKey)
            {
                pendingKey = "";
                // A third-party route depends on the CC Switch proxy at :15721.
                // Closing the CC Switch window/process should not silently make the
                // current GLM/DeepSeek/Qwen route unusable. Keep the proxy healthy
                // independently from route-change handling. Explicit Launcher Exit
                // stops the timer first, so this supervisor never fights a deliberate
                // full shutdown.
                SuperviseThirdPartyProxy(route);
                return;
            }

            if (handling) return;

            if (pendingKey != route.Key)
            {
                pendingKey = route.Key;
                pendingSinceUtc = DateTime.UtcNow;
                return;
            }

            if ((DateTime.UtcNow - pendingSinceUtc).TotalMilliseconds < 1000) return;

            lastHandledKey = route.Key;
            SaveStateValue("last_handled_route", lastHandledKey);
            pendingKey = "";
            handling = true;
            UpdateStatusText("Switching: " + FriendlyRoute(route));
            Log("Provider switch detected: " + route.Key);

            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    if (exiting) return;
                    if (string.Equals(route.Kind, "third-party", StringComparison.OrdinalIgnoreCase))
                    {
                        RestartCcSwitch();
                        if (exiting) return;
                        Thread.Sleep(500);
                        if (exiting) return;
                        RestartCodex("third-party route " + route.Model);
                    }
                    else
                    {
                        Thread.Sleep(300);
                        if (exiting) return;
                        RestartCodex("Official route / ChatGPT account reload");
                    }
                    Log("Switch handling complete. Bridge was not restarted.");
                    Balloon("Provider switch complete", FriendlyRoute(route) + " is ready. Bridge remained resident.", ToolTipIcon.Info);
                }
                catch (Exception ex)
                {
                    Log("ERROR handling switch: " + ex);
                    Balloon("Provider switch failed", ex.Message, ToolTipIcon.Error);
                }
                finally
                {
                    handling = false;
                    UpdateStatusText("Route: " + FriendlyRoute(route));
                }
            });
        }

        private static string FriendlyRoute(RouteSnapshot route)
        {
            if (route == null) return "unknown";
            if (route.Kind == "official") return "Official" + (string.IsNullOrEmpty(route.Model) ? "" : " / " + route.Model);
            return "Third-party" + (string.IsNullOrEmpty(route.Model) ? "" : " / " + route.Model);
        }

        private RouteSnapshot ReadRouteSnapshot()
        {
            string json = ReadTextFileSafe(routeStatePath);
            if (string.IsNullOrEmpty(json)) return null;
            string kind = JsonString(json, "route_kind");
            string model = JsonString(json, "route_model");
            string source = JsonString(json, "source_path");
            if (kind != "official" && kind != "third-party") return null;
            RouteSnapshot r = new RouteSnapshot();
            r.Kind = kind;
            r.Model = model ?? "";
            r.Source = source ?? "";
            r.Key = kind == "official" ? "official" : "third-party|" + r.Model;
            return r;
        }

        private bool IsCustomDirectOfficialRoute()
        {
            try
            {
                string configPath = Path.Combine(codexHome, "config.toml");
                if (!File.Exists(configPath)) return false;
                string text = File.ReadAllText(configPath);
                Match provider = Regex.Match(text, "(?m)^\\s*model_provider\\s*=\\s*[\"\']custom[\"\']\\s*(?:#.*)?$");
                if (!provider.Success) return false;

                Match section = Regex.Match(text,
                    "(?ms)^\\s*\\[model_providers\\.(?:custom|\"custom\")\\]\\s*$([\\s\\S]*?)(?=^\\s*\\[|\\z)");
                if (!section.Success) return false;
                Match baseUrl = Regex.Match(section.Groups[1].Value,
                    "(?m)^\\s*base_url\\s*=\\s*[\"\']([^\"\']+)[\"\']\\s*(?:#.*)?$");
                if (!baseUrl.Success) return false;
                string value = baseUrl.Groups[1].Value.Trim().TrimEnd('/');
                return string.Equals(value, "https://chatgpt.com/backend-api/codex", StringComparison.OrdinalIgnoreCase);
            }
            catch { return false; }
        }

        private void EnsureBridgeRunning()
        {
            lock (bridgeLifecycleSync)
            {
                if (exiting)
                {
                    Log("Skipping Bridge ensure because Exit Everything is in progress.");
                    return;
                }

                if (!File.Exists(managerScript))
                {
                    Log("ERROR bridge manager not found: " + managerScript);
                    Balloon("Codex Bridge Launcher", "codex_bridge_manager.ps1 not found next to the launcher.", ToolTipIcon.Error);
                    return;
                }

                bool wasDirectOfficialHandoff = IsCustomDirectOfficialRoute();
                if (wasDirectOfficialHandoff)
                    Log("Direct Official custom-provider handoff detected; Bridge startup will rebind custom.base_url to :15722 and restart Codex after the Bridge is ready.");

                Log("Ensuring resident Bridge is running...");
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Program.PowerShellExePath();
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + managerScript.Replace("\"", "\\\"") + "\" start -Background";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = launcherRuntimeDir;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;

                StringBuilder managerOut = new StringBuilder();
                StringBuilder managerErr = new StringBuilder();
                Process p = new Process();
                p.StartInfo = psi;
                p.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) lock (managerOut) managerOut.AppendLine(e.Data);
                };
                p.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) lock (managerErr) managerErr.AppendLine(e.Data);
                };
                try
                {
                    if (!p.Start()) throw new Exception("Could not start bridge manager PowerShell process.");
                    lock (bridgeEnsureProcessSync)
                    {
                        bridgeEnsureProcess = p;
                    }
                    if (exiting)
                    {
                        try { if (!p.HasExited) p.Kill(); } catch { }
                    }
                    p.BeginOutputReadLine();
                    p.BeginErrorReadLine();
                    if (!p.WaitForExit(60000))
                    {
                        try { p.Kill(); } catch { }
                        if (exiting)
                        {
                            Log("Bridge manager startup was cancelled during Exit Everything.");
                            return;
                        }
                        throw new Exception("Bridge manager did not return within 60 seconds.");
                    }
                    // Flush asynchronous OutputDataReceived/ErrorDataReceived callbacks.
                    try { p.WaitForExit(); } catch { }

                    string stdout = managerOut.ToString().Trim();
                    string stderr = managerErr.ToString().Trim();
                    if (!string.IsNullOrEmpty(stdout)) Log("Bridge manager stdout:\r\n" + stdout);
                    if (!string.IsNullOrEmpty(stderr)) Log("Bridge manager stderr:\r\n" + stderr);
                    if (exiting)
                    {
                        Log("Bridge manager startup finished/cancelled during Exit Everything; ignoring its result.");
                        return;
                    }
                    if (p.ExitCode != 0)
                    {
                        string detail = !string.IsNullOrEmpty(stderr) ? stderr : stdout;
                        throw new Exception("Bridge manager exited with code " + p.ExitCode +
                            (string.IsNullOrEmpty(detail) ? "." : ": " + detail));
                    }
                    Log("Bridge manager completed; resident Bridge should be active.");
                }
                finally
                {
                    lock (bridgeEnsureProcessSync)
                    {
                        if (Object.ReferenceEquals(bridgeEnsureProcess, p)) bridgeEnsureProcess = null;
                    }
                    try { p.Dispose(); } catch { }
                }

                // Exit Everything may be confirmed while a startup ensure that began earlier
                // is still waiting for the manager. Never let that stale ensure restart Codex.
                if (exiting)
                {
                    Log("Bridge ensure completed during Exit Everything; skipping post-ensure Codex restart.");
                    return;
                }

                if (wasDirectOfficialHandoff)
                {
                    RestartCodex("Bridge re-enabled after direct Official custom-provider handoff");
                    Log("Codex restarted after custom.base_url was rebound to the local Bridge.");
                }
            }
        }

        private void SuperviseThirdPartyProxy(RouteSnapshot route)
        {
            if (route == null || !string.Equals(route.Kind, "third-party", StringComparison.OrdinalIgnoreCase))
                return;
            if (thirdPartyProxyRecoveryQueued || handling) return;
            if (DateTime.UtcNow < nextThirdPartyProxyHealthUtc) return;
            nextThirdPartyProxyHealthUtc = DateTime.UtcNow.AddSeconds(2);

            if (TestTcpPort("127.0.0.1", 15721, 120)) return;

            thirdPartyProxyRecoveryQueued = true;
            handling = true;
            UpdateStatusText("Recovering CC Switch proxy for " + route.Model + "...");
            Log("Third-party route is active but CC Switch proxy :15721 is unavailable; scheduling automatic recovery without changing provider/model.");
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    if (exiting) return;
                    EnsureCcSwitchProxyRunning();
                    if (exiting) return;
                    Log("Third-party CC Switch proxy recovery complete; route remains " + route.Key + ".");
                    Balloon("CC Switch proxy restored", "Third-party route " + route.Model + " is available again.", ToolTipIcon.Info);
                }
                catch (Exception ex)
                {
                    Log("ERROR recovering CC Switch proxy for active third-party route: " + ex);
                    Balloon("CC Switch proxy unavailable", "Could not restore the third-party proxy automatically. Open CC Switch once or check Launcher Log.", ToolTipIcon.Error);
                }
                finally
                {
                    nextThirdPartyProxyHealthUtc = DateTime.UtcNow.AddSeconds(3);
                    thirdPartyProxyRecoveryQueued = false;
                    handling = false;
                    UpdateStatusText("Route: " + FriendlyRoute(route));
                }
            });
        }

        private bool StartCcSwitchFromRememberedTarget()
        {
            string exe = GetState("cc_switch_exe");
            string shortcut = GetState("cc_switch_shortcut");
            bool started = false;
            if (!string.IsNullOrEmpty(exe) && File.Exists(exe)) started = StartDetached(exe, null);
            if (!started)
            {
                string discovered = DiscoverCcSwitchExe();
                if (!string.IsNullOrEmpty(discovered))
                {
                    SaveStateValue("cc_switch_exe", discovered);
                    started = StartDetached(discovered, null);
                }
            }
            if (!started && !string.IsNullOrEmpty(shortcut) && File.Exists(shortcut))
                started = StartShell(shortcut);
            if (!started)
            {
                string link = DiscoverShortcut("*CC*Switch*.lnk");
                if (!string.IsNullOrEmpty(link))
                {
                    SaveStateValue("cc_switch_shortcut", link);
                    started = StartShell(link);
                }
            }
            return started;
        }

        private bool WaitForCcSwitchProxy(int timeoutMilliseconds)
        {
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMilliseconds);
            while (DateTime.UtcNow < deadline)
            {
                if (TestTcpPort("127.0.0.1", 15721, 220)) return true;
                Thread.Sleep(250);
            }
            return TestTcpPort("127.0.0.1", 15721, 220);
        }

        private void EnsureCcSwitchProxyRunning()
        {
            if (exiting) return;
            if (TestTcpPort("127.0.0.1", 15721, 220)) return;

            List<Process> processes = FindCcSwitchProcesses();
            RememberCcSwitch(processes);

            // The process can still be alive briefly while its proxy is coming up.
            // Give it a short grace period before treating it as unhealthy.
            if (processes.Count > 0 && WaitForCcSwitchProxy(2500))
            {
                Log("CC Switch process was already alive and proxy :15721 recovered without a restart.");
                return;
            }

            if (processes.Count > 0)
            {
                Log("CC Switch process exists but proxy :15721 is unavailable; restarting CC Switch for recovery.");
                for (int i = 0; i < processes.Count; i++) KillProcessTree(processes[i].Id);
                Thread.Sleep(600);
            }
            else
            {
                Log("CC Switch was closed while a third-party route remained active; relaunching it automatically.");
            }

            if (!StartCcSwitchFromRememberedTarget())
                throw new Exception("Could not locate/relaunch CC Switch. Open CC Switch once so Codex Bridge can learn its executable path.");

            if (!WaitForCcSwitchProxy(20000))
                throw new Exception("CC Switch was relaunched, but proxy port 15721 did not become ready within 20 seconds.");

            Log("CC Switch proxy ready on 127.0.0.1:15721.");
        }

        private void RestartCcSwitch()
        {
            if (exiting)
            {
                Log("Skipping CC Switch restart because Exit Everything is in progress.");
                return;
            }
            Log("Restarting CC Switch for third-party route...");
            List<Process> processes = FindCcSwitchProcesses();
            RememberCcSwitch(processes);
            for (int i = 0; i < processes.Count; i++) KillProcessTree(processes[i].Id);
            Thread.Sleep(600);

            if (!StartCcSwitchFromRememberedTarget())
                throw new Exception("Could not locate/relaunch CC Switch. Open CC Switch once, then retry.");

            if (WaitForCcSwitchProxy(20000)) Log("CC Switch proxy ready on 127.0.0.1:15721.");
            else Log("WARNING CC Switch restarted but port 15721 was not ready after 20 seconds.");
        }

        private void RestartCodex(string reason)
        {
            if (exiting)
            {
                Log("Skipping Codex restart because Exit Everything is in progress: " + reason);
                return;
            }
            Log("Restarting Codex: " + reason);
            List<Process> processes = FindCodexProcesses();
            bool hadGui = false;
            string guiExe = "";
            for (int i = 0; i < processes.Count; i++)
            {
                try
                {
                    if (processes[i].MainWindowHandle != IntPtr.Zero)
                    {
                        hadGui = true;
                        string path = SafeProcessPath(processes[i]);
                        if (!string.IsNullOrEmpty(path)) guiExe = path;
                    }
                }
                catch { }
            }
            if (!string.IsNullOrEmpty(guiExe)) SaveStateValue("codex_gui_exe", guiExe);
            for (int i = 0; i < processes.Count; i++) KillProcessTree(processes[i].Id);
            Thread.Sleep(700);

            if (hadGui)
            {
                string exe = GetState("codex_gui_exe");
                if (!string.IsNullOrEmpty(exe) && File.Exists(exe))
                {
                    if (StartDetached(exe, null))
                    {
                        Log("Codex GUI relaunched.");
                        return;
                    }
                }
                Log("WARNING Codex GUI was closed but could not be relaunched automatically.");
                return;
            }

            for (int i = 0; i < 40; i++)
            {
                Thread.Sleep(250);
                if (FindCodexProcesses().Count > 0)
                {
                    Log("Codex backend respawned by its host.");
                    return;
                }
            }
            Log("Codex backend terminated. VS Code/Cursor should recreate it on the next Codex interaction.");
        }

        private List<Process> FindCcSwitchProcesses()
        {
            List<Process> result = new List<Process>();
            Process[] all = Process.GetProcesses();
            for (int i = 0; i < all.Length; i++)
            {
                Process p = all[i];
                try
                {
                    string name = p.ProcessName ?? "";
                    string title = p.MainWindowTitle ?? "";
                    string path = SafeProcessPath(p);
                    if (Regex.IsMatch(name, "(?i)^cc[-_ ]?switch$|^ccswitch$") ||
                        Regex.IsMatch(path ?? "", "(?i)cc[-_ ]?switch|ccswitch") ||
                        Regex.IsMatch(title, "(?i)CC\\s*Switch"))
                    {
                        result.Add(p);
                    }
                }
                catch { }
            }
            return result;
        }

        private List<Process> FindCodexProcesses()
        {
            List<Process> result = new List<Process>();
            Process[] all = Process.GetProcesses();
            for (int i = 0; i < all.Length; i++)
            {
                Process p = all[i];
                try
                {
                    string name = p.ProcessName ?? "";
                    string path = SafeProcessPath(p) ?? "";
                    if (Regex.IsMatch(name, "(?i)^codex$") || Regex.IsMatch(path, "(?i)\\\\OpenAI\\\\Codex\\\\"))
                        result.Add(p);
                }
                catch { }
            }
            return result;
        }

        private void RememberLaunchTargets()
        {
            RememberCcSwitch(FindCcSwitchProcesses());
            List<Process> codex = FindCodexProcesses();
            for (int i = 0; i < codex.Count; i++)
            {
                try
                {
                    if (codex[i].MainWindowHandle != IntPtr.Zero)
                    {
                        string path = SafeProcessPath(codex[i]);
                        if (!string.IsNullOrEmpty(path)) SaveStateValue("codex_gui_exe", path);
                    }
                }
                catch { }
            }
        }

        private void RememberCcSwitch(List<Process> processes)
        {
            for (int i = 0; i < processes.Count; i++)
            {
                string path = SafeProcessPath(processes[i]);
                if (!string.IsNullOrEmpty(path) && File.Exists(path))
                {
                    SaveStateValue("cc_switch_exe", path);
                    return;
                }
            }
            string shortcut = DiscoverShortcut("*CC*Switch*.lnk");
            if (!string.IsNullOrEmpty(shortcut)) SaveStateValue("cc_switch_shortcut", shortcut);
        }

        private static string SafeProcessPath(Process p)
        {
            try { return p.MainModule == null ? "" : p.MainModule.FileName; }
            catch { return ""; }
        }

        private string DiscoverCcSwitchExe()
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            string[] candidates = new string[]
            {
                Path.Combine(local, "Programs", "CC Switch", "CC Switch.exe"),
                Path.Combine(local, "Programs", "CCSwitch", "CCSwitch.exe"),
                Path.Combine(local, "CC Switch", "CC Switch.exe"),
                Path.Combine(local, "CCSwitch", "CCSwitch.exe"),
                Path.Combine(pf, "CC Switch", "CC Switch.exe"),
                Path.Combine(pf, "CCSwitch", "CCSwitch.exe"),
                Path.Combine(pf86, "CC Switch", "CC Switch.exe"),
                Path.Combine(pf86, "CCSwitch", "CCSwitch.exe")
            };
            for (int i = 0; i < candidates.Length; i++) if (File.Exists(candidates[i])) return candidates[i];
            return "";
        }

        private static string DiscoverShortcut(string pattern)
        {
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
            string[] roots = new string[]
            {
                Path.Combine(appData, "Microsoft", "Windows", "Start Menu", "Programs"),
                Path.Combine(programData, "Microsoft", "Windows", "Start Menu", "Programs")
            };
            for (int i = 0; i < roots.Length; i++)
            {
                try
                {
                    if (!Directory.Exists(roots[i])) continue;
                    string[] links = Directory.GetFiles(roots[i], pattern, SearchOption.AllDirectories);
                    if (links.Length > 0) return links[0];
                }
                catch { }
            }
            return "";
        }

        private static void KillProcessTree(int pid)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe");
                psi.Arguments = "/PID " + pid + " /T /F";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                Process p = Process.Start(psi);
                if (p != null) p.WaitForExit(8000);
            }
            catch
            {
                try { Process.GetProcessById(pid).Kill(); } catch { }
            }
        }

        private bool StartDetached(string file, string args)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = file;
                psi.Arguments = args ?? "";
                psi.UseShellExecute = true;
                string executableDirectory = Path.GetDirectoryName(file);
                psi.WorkingDirectory = (!string.IsNullOrEmpty(executableDirectory) && Directory.Exists(executableDirectory))
                    ? executableDirectory
                    : launcherRuntimeDir;
                Process.Start(psi);
                return true;
            }
            catch { return false; }
        }

        private bool StartShell(string path)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = path;
                psi.UseShellExecute = true;
                // A .lnk may define its own Start In directory. If it does not, use a
                // launcher-owned runtime directory instead of inheriting the package cwd.
                psi.WorkingDirectory = launcherRuntimeDir;
                Process.Start(psi);
                return true;
            }
            catch { return false; }
        }

        private static bool TestTcpPort(string host, int port, int timeoutMs)
        {
            TcpClient client = new TcpClient();
            try
            {
                IAsyncResult ar = client.BeginConnect(host, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs, false)) return false;
                client.EndConnect(ar);
                return true;
            }
            catch { return false; }
            finally { try { client.Close(); } catch { } }
        }

        private void OpenTextFile(string path)
        {
            try
            {
                if (!File.Exists(path)) File.WriteAllText(path, "", new UTF8Encoding(false));
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "notepad.exe";
                psi.Arguments = "\"" + path + "\"";
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            catch (Exception ex) { Log("ERROR opening log: " + ex.Message); }
        }

        private void OpenLogFolder()
        {
            try
            {
                Directory.CreateDirectory(logDir);
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "explorer.exe";
                psi.Arguments = "\"" + logDir + "\"";
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            catch (Exception ex) { Log("ERROR opening log folder: " + ex.Message); }
        }

        private void UpdateStatusText(string text)
        {
            if (tray == null || tray.ContextMenuStrip == null) return;
            try
            {
                ToolStrip menu = tray.ContextMenuStrip;
                if (menu.InvokeRequired)
                {
                    menu.BeginInvoke(new Action<string>(UpdateStatusText), text);
                    return;
                }
                statusItem.Text = "Status: " + text;
            }
            catch { }
        }

        private void Balloon(string title, string message, ToolTipIcon icon)
        {
            try
            {
                if (tray == null) return;
                tray.BalloonTipTitle = title;
                tray.BalloonTipText = message;
                tray.BalloonTipIcon = icon;
                tray.ShowBalloonTip(2500);
            }
            catch { }
        }

        private void StopBridgeForUpdate()
        {
            // Serialize stop against any in-flight EnsureBridgeRunning call. This prevents
            // an older startup ensure from finishing after Exit Everything and reviving the
            // Bridge or restarting Codex while shutdown is already in progress.
            lock (bridgeLifecycleSync)
            {
                if (!File.Exists(managerScript))
                {
                    Log("WARNING bridge manager not found while stopping Bridge: " + managerScript);
                    return;
                }
                Log("Stopping resident Bridge for update-folder unlock...");
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Program.PowerShellExePath();
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + managerScript.Replace("\"", "\\\"") + "\" stop";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = launcherRuntimeDir;
                using (Process p = Process.Start(psi))
                {
                    if (p != null && !p.WaitForExit(20000))
                    {
                        try { p.Kill(); } catch { }
                        throw new Exception("Bridge manager stop did not return within 20 seconds.");
                    }
                }
                Log("Bridge stop command completed. Manager also scans for orphan codex_provider_bridge.py processes.");
            }
        }

        private void PrepareDirectOfficialHandoff()
        {
            if (!File.Exists(managerScript))
                throw new FileNotFoundException("Bridge manager not found while preparing direct Official handoff.", managerScript);

            Log("Preparing graceful detach: keeping model_provider=custom while switching custom.base_url directly to the Official ChatGPT Codex backend...");
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = Program.PowerShellExePath();
            psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + managerScript.Replace("\"", "\\\"") + "\" prepare-direct-official";
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.WorkingDirectory = launcherRuntimeDir;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            using (Process p = Process.Start(psi))
            {
                if (p == null) throw new Exception("Could not start Bridge manager for direct Official handoff.");
                string stdout = p.StandardOutput.ReadToEnd();
                string stderr = p.StandardError.ReadToEnd();
                if (!p.WaitForExit(20000))
                {
                    try { p.Kill(); } catch { }
                    throw new Exception("Bridge manager prepare-direct-official did not return within 20 seconds.");
                }
                if (!string.IsNullOrWhiteSpace(stdout)) Log("Direct Official handoff manager stdout:\r\n" + stdout.Trim());
                if (!string.IsNullOrWhiteSpace(stderr)) Log("Direct Official handoff manager stderr:\r\n" + stderr.Trim());
                if (p.ExitCode != 0)
                    throw new Exception("Bridge manager prepare-direct-official failed with code " + p.ExitCode +
                        (string.IsNullOrWhiteSpace(stderr) ? "" : ": " + stderr.Trim()));
            }
            Log("Direct Official custom-provider route prepared. Bridge remains alive until Codex has restarted.");
        }

        private void StopCcSwitchForExit()
        {
            List<Process> processes = FindCcSwitchProcesses();
            if (processes.Count == 0)
            {
                Log("CC Switch was already stopped during Exit Everything.");
                return;
            }

            Log("Stopping CC Switch during Exit Everything...");
            for (int i = 0; i < processes.Count; i++)
            {
                try { KillProcessTree(processes[i].Id); } catch { }
                try { processes[i].Dispose(); } catch { }
            }
            Log("CC Switch stop completed.");
        }

        private static bool IsTraditionalChineseUiCulture(string cultureName)
        {
            if (String.IsNullOrEmpty(cultureName)) return false;
            return cultureName.Equals("zh-TW", StringComparison.OrdinalIgnoreCase) ||
                   cultureName.Equals("zh-HK", StringComparison.OrdinalIgnoreCase) ||
                   cultureName.Equals("zh-MO", StringComparison.OrdinalIgnoreCase) ||
                   cultureName.StartsWith("zh-Hant", StringComparison.OrdinalIgnoreCase);
        }

        private static void GetExitDialogText(out string title, out string body)
        {
            string cultureName = "";
            try
            {
                cultureName = CultureInfo.CurrentUICulture.Name ?? "";
            }
            catch
            {
                cultureName = "";
            }

            if (cultureName.StartsWith("zh", StringComparison.OrdinalIgnoreCase))
            {
                if (IsTraditionalChineseUiCulture(cultureName))
                {
                    title = "警告：徹底退出 CodexBridge？";
                    body =
                        "徹底退出將關閉 CodexBridge 和 CC Switch。\r\n" +
                        "目前的 Codex 對話將暫時無法繼續。\r\n\r\n" +
                        "重新開啟 CC Switch 後，CodexBridge 會自動啟動。";
                }
                else
                {
                    title = "警告：彻底退出 CodexBridge？";
                    body =
                        "彻底退出将关闭 CodexBridge 和 CC Switch。\r\n" +
                        "当前 Codex 对话将暂时无法继续。\r\n\r\n" +
                        "重新打开 CC Switch 后，CodexBridge 会自动启动。";
                }
                return;
            }

            title = "Warning: Exit CodexBridge completely?";
            body =
                "This will close CodexBridge and CC Switch.\r\n" +
                "Current Codex conversations will be temporarily unavailable.\r\n\r\n" +
                "Opening CC Switch later will automatically start CodexBridge again.";
        }

        private static void GetUninstallDialogText(out string title, out string body)
        {
            string cultureName = "";
            try { cultureName = CultureInfo.CurrentUICulture.Name ?? ""; } catch { }

            if (cultureName.StartsWith("zh", StringComparison.OrdinalIgnoreCase))
            {
                if (IsTraditionalChineseUiCulture(cultureName))
                {
                    title = "解除安裝 CodexBridge？";
                    body =
                        "這將解除安裝 CodexBridge，關閉 Bridge 和 CC Switch，並刪除本機程式、日誌和執行階段檔案。\r\n\r\n" +
                        "Codex 設定將恢復到安裝前狀態。聊天記錄不會被刪除。";
                }
                else
                {
                    title = "卸载 CodexBridge？";
                    body =
                        "这将卸载 CodexBridge，关闭 Bridge 和 CC Switch，并删除本地程序、日志和运行时文件。\r\n\r\n" +
                        "Codex 配置将恢复到安装前状态。聊天记录不会删除。";
                }
                return;
            }

            title = "Uninstall CodexBridge?";
            body =
                "This will uninstall CodexBridge, stop Bridge and CC Switch, and delete local program files, logs, and runtimes.\r\n\r\n" +
                "Codex configuration will be restored to its pre-install state. Chat history will not be deleted.";
        }

        private void UninstallCodexBridge()
        {
            if (exiting) return;

            string title;
            string body;
            GetUninstallDialogText(out title, out body);
            DialogResult answer = MessageBox.Show(
                body,
                title,
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2);
            if (answer != DialogResult.Yes)
            {
                Log("Uninstall cancelled by user.");
                return;
            }

            string script = Path.Combine(baseDir, "UninstallCodexBridge.ps1");
            if (!File.Exists(script))
            {
                MessageBox.Show(
                    "Uninstaller not found:\r\n" + script,
                    "CodexBridge",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return;
            }

            exiting = true;
            try { pollTimer.Stop(); } catch { }
            try
            {
                if (tray.ContextMenuStrip != null) tray.ContextMenuStrip.Close();
                tray.Visible = false;
            }
            catch { }
            CancelInFlightBridgeEnsure();
            Program.StopCcSwitchWatcher();

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Program.PowerShellExePath();
                psi.Arguments =
                    "-NoProfile -ExecutionPolicy Bypass -File \"" + script.Replace("\"", "\\\"") +
                    "\" -Confirmed -ParentPid " + Process.GetCurrentProcess().Id;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = launcherRuntimeDir;
                Process.Start(psi);
                Log("Uninstall requested. Handed cleanup to the dedicated uninstaller.");
                FinalizeExitOnUiThread();
            }
            catch (Exception ex)
            {
                exiting = false;
                try { tray.Visible = true; } catch { }
                try { pollTimer.Start(); } catch { }
                Log("ERROR starting uninstaller: " + ex);
                MessageBox.Show(
                    "Could not start the CodexBridge uninstaller.\r\n\r\n" + ex.Message,
                    "CodexBridge",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }

        private void CancelInFlightBridgeEnsure()
        {
            Process p = null;
            lock (bridgeEnsureProcessSync)
            {
                p = bridgeEnsureProcess;
            }
            if (p == null) return;

            try
            {
                if (!p.HasExited)
                {
                    Log("Cancelling in-flight Bridge manager startup for Exit Everything.");
                    p.Kill();
                }
            }
            catch (Exception ex)
            {
                Log("WARNING cancelling in-flight Bridge manager startup: " + ex.Message);
            }
        }

        private void PerformExitShutdown()
        {
            try
            {
                StopBridgeForUpdate();
            }
            catch (Exception ex)
            {
                Log("WARNING stopping Bridge during Exit Everything: " + ex.Message);
            }

            try
            {
                StopCcSwitchForExit();
            }
            catch (Exception ex)
            {
                Log("WARNING stopping CC Switch during Exit Everything: " + ex.Message);
            }

            Log("Exit Everything complete: tray launcher, resident Bridge, and CC Switch stopped. config.toml and Codex were left untouched; CC Switch trigger watcher remains armed for automatic relaunch.");
            FinalizeExitOnUiThread();
        }

        private void FinalizeExitOnUiThread()
        {
            try
            {
                ContextMenuStrip menu = tray == null ? null : tray.ContextMenuStrip;
                if (menu != null && menu.InvokeRequired)
                {
                    menu.BeginInvoke(new Action(FinalizeExitOnUiThread));
                    return;
                }
            }
            catch
            {
                try { Application.Exit(); } catch { }
                return;
            }

            try { tray.Dispose(); } catch { }
            try { pollTimer.Dispose(); } catch { }
            Application.ExitThread();
        }

        private void ExitLauncher()
        {
            if (exiting) return;

            string exitTitle;
            string exitBody;
            GetExitDialogText(out exitTitle, out exitBody);

            DialogResult answer = MessageBox.Show(
                exitBody,
                exitTitle,
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2);

            if (answer != DialogResult.Yes)
            {
                Log("Exit Everything cancelled by user.");
                return;
            }

            // Explicit functional shutdown only. Do not rewrite config.toml, do not perform
            // native-Official handoff, and do not restart Codex. Keep the lightweight CC Switch
            // trigger watcher alive so opening CC Switch later can relaunch CodexBridge automatically.
            // Leaving custom.base_url on :15722 preserves the exact compatibility path and avoids
            // mutating conversation history.
            exiting = true;
            try { pollTimer.Stop(); } catch { }
            Log("Exit Everything confirmed. Cancelling startup work, then stopping Bridge and CC Switch in the background; config.toml and Codex will be left untouched; CC Switch trigger watcher remains armed.");

            // Close the menu/tray immediately so the UI never appears hung while PowerShell or an
            // older startup ensure is winding down. The functional shutdown continues below on a
            // worker thread and the process exits only after Bridge + CC Switch stop attempts finish.
            try
            {
                if (tray.ContextMenuStrip != null)
                {
                    tray.ContextMenuStrip.Enabled = false;
                    tray.ContextMenuStrip.Close();
                }
            }
            catch { }
            try { tray.Visible = false; } catch { }

            // A startup EnsureBridgeRunning can hold bridgeLifecycleSync for up to 60 seconds while
            // waiting for the manager. Cancel that specific manager process first, so the shutdown
            // worker never waits on the old startup path and cannot revive/restart anything.
            CancelInFlightBridgeEnsure();
            ThreadPool.QueueUserWorkItem(delegate { PerformExitShutdown(); });
        }

        private void Log(string message)
        {
            try
            {
                lock (sync)
                {
                    Directory.CreateDirectory(logDir);
                    File.AppendAllText(launcherLog,
                        DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + message + Environment.NewLine,
                        new UTF8Encoding(false));
                }
            }
            catch { }
        }

        private string ReadTextFileSafe(string path)
        {
            for (int i = 0; i < 6; i++)
            {
                try
                {
                    if (!File.Exists(path)) return "";
                    return File.ReadAllText(path, Encoding.UTF8);
                }
                catch { Thread.Sleep(60); }
            }
            return "";
        }

        private static string JsonString(string json, string key)
        {
            Match m = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"\\\\])*)\\\"", RegexOptions.CultureInvariant);
            if (!m.Success) return "";
            return JsonUnescape(m.Groups[1].Value);
        }

        private static string JsonUnescape(string value)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (c != '\\' || i + 1 >= value.Length) { sb.Append(c); continue; }
                char n = value[++i];
                if (n == '\\') sb.Append('\\');
                else if (n == '"') sb.Append('"');
                else if (n == 'n') sb.Append('\n');
                else if (n == 'r') sb.Append('\r');
                else if (n == 't') sb.Append('\t');
                else if (n == 'b') sb.Append('\b');
                else if (n == 'f') sb.Append('\f');
                else if (n == 'u' && i + 4 < value.Length)
                {
                    string hex = value.Substring(i + 1, 4);
                    int code;
                    if (int.TryParse(hex, System.Globalization.NumberStyles.HexNumber, null, out code))
                    {
                        sb.Append((char)code);
                        i += 4;
                    }
                    else sb.Append(n);
                }
                else sb.Append(n);
            }
            return sb.ToString();
        }

        private static string JsonEscape(string value)
        {
            if (value == null) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n").Replace("\t", "\\t");
        }

        private void LoadState()
        {
            string json = ReadTextFileSafe(statePath);
            if (string.IsNullOrEmpty(json)) return;
            string[] keys = new string[] { "cc_switch_exe", "cc_switch_shortcut", "codex_gui_exe", "last_handled_route" };
            for (int i = 0; i < keys.Length; i++)
            {
                string v = JsonString(json, keys[i]);
                if (!string.IsNullOrEmpty(v)) state[keys[i]] = v;
            }
        }

        private string GetState(string key)
        {
            lock (sync)
            {
                string value;
                return state.TryGetValue(key, out value) ? value : "";
            }
        }

        private void SaveStateValue(string key, string value)
        {
            lock (sync)
            {
                state[key] = value ?? "";
                state["updated_at"] = DateTime.Now.ToString("o");
                StringBuilder sb = new StringBuilder();
                sb.Append("{\n");
                int index = 0;
                foreach (KeyValuePair<string, string> pair in state)
                {
                    if (index++ > 0) sb.Append(",\n");
                    sb.Append("  \"").Append(JsonEscape(pair.Key)).Append("\": \"").Append(JsonEscape(pair.Value)).Append("\"");
                }
                sb.Append("\n}\n");
                string temp = statePath + ".tmp-" + Process.GetCurrentProcess().Id;
                File.WriteAllText(temp, sb.ToString(), new UTF8Encoding(false));
                try
                {
                    if (File.Exists(statePath)) File.Replace(temp, statePath, null);
                    else File.Move(temp, statePath);
                }
                catch
                {
                    try
                    {
                        if (File.Exists(statePath)) File.Delete(statePath);
                        File.Move(temp, statePath);
                    }
                    catch { try { if (File.Exists(temp)) File.Delete(temp); } catch { } }
                }
            }
        }
    }

    internal static class Program
    {
        private static void EmergencyLog(string message)
        {
            try
            {
                string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge");
                Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "launcher-crash.log"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + message + Environment.NewLine,
                    new UTF8Encoding(false));
            }
            catch { }
        }


        private const string StartupRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValueName = "CodexBridgeLauncher";
        private const string UninstallRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexBridge";
        private const string ProductVersion = "0.1.2";

        internal static string PowerShellExePath()
        {
            string windir = Environment.GetEnvironmentVariable("WINDIR") ?? "";
            string candidate = Path.Combine(windir, @"System32\WindowsPowerShell\v1.0\powershell.exe");
            if (File.Exists(candidate)) return candidate;
            candidate = Path.Combine(windir, @"Sysnative\WindowsPowerShell\v1.0\powershell.exe");
            if (File.Exists(candidate)) return candidate;
            return "powershell.exe";
        }

        private static string StableInstallDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge", "app");
        }

        private static bool PathsEqual(string a, string b)
        {
            try
            {
                return string.Equals(Path.GetFullPath(a).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
                    Path.GetFullPath(b).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
                    StringComparison.OrdinalIgnoreCase);
            }
            catch { return string.Equals(a ?? "", b ?? "", StringComparison.OrdinalIgnoreCase); }
        }

        private static void RegisterStableAutostart(string exePath)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupRegistryPath))
            {
                if (key == null) throw new Exception("Could not open the current-user Startup registry key.");
                key.SetValue(StartupValueName, "\"" + exePath + "\" --autostart", RegistryValueKind.String);
            }
        }

        private static string StableStateRoot()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge");
        }

        private static void CapturePreinstallConfigIfNeeded()
        {
            try
            {
                string stateDir = Path.Combine(StableStateRoot(), "uninstall");
                string marker = Path.Combine(stateDir, "preinstall-state.txt");
                string snapshot = Path.Combine(stateDir, "preinstall-config.toml");
                if (File.Exists(marker)) return;

                Directory.CreateDirectory(stateDir);
                string codexDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex");
                string config = Path.Combine(codexDir, "config.toml");
                if (!File.Exists(config))
                {
                    File.WriteAllText(marker, "absent" + Environment.NewLine, new UTF8Encoding(false));
                    return;
                }

                string current = File.ReadAllText(config);
                bool alreadyManaged =
                    current.IndexOf("127.0.0.1:15722", StringComparison.OrdinalIgnoreCase) >= 0 ||
                    current.IndexOf("cpb-", StringComparison.OrdinalIgnoreCase) >= 0;

                string source = config;
                if (alreadyManaged && Directory.Exists(codexDir))
                {
                    string[] backups = Directory.GetFiles(codexDir, "config.toml.bridge-backup-*", SearchOption.TopDirectoryOnly);
                    Array.Sort(backups, StringComparer.OrdinalIgnoreCase);
                    source = "";
                    for (int i = 0; i < backups.Length; i++)
                    {
                        string candidateText = File.ReadAllText(backups[i]);
                        bool candidateManaged =
                            candidateText.IndexOf("127.0.0.1:15722", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            candidateText.IndexOf("cpb-", StringComparison.OrdinalIgnoreCase) >= 0;
                        if (!candidateManaged)
                        {
                            source = backups[i];
                            break;
                        }
                    }
                    if (String.IsNullOrEmpty(source))
                    {
                        File.WriteAllText(marker, "unknown" + Environment.NewLine, new UTF8Encoding(false));
                        return;
                    }
                }

                File.Copy(source, snapshot, true);
                File.WriteAllText(marker, "existing" + Environment.NewLine, new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                EmergencyLog("WARNING could not capture pre-install Codex config for uninstall: " + ex.Message);
            }
        }

        private static void RegisterWindowsUninstallEntry(string installedExe, string installDir)
        {
            try
            {
                string uninstaller = Path.Combine(installDir, "UninstallCodexBridge.ps1");
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegistryPath))
                {
                    if (key == null) return;
                    string ps = PowerShellExePath();
                    string uninstallString =
                        "\"" + ps + "\" -NoProfile -ExecutionPolicy Bypass -File \"" + uninstaller + "\"";
                    key.SetValue("DisplayName", "CodexBridge", RegistryValueKind.String);
                    key.SetValue("DisplayVersion", ProductVersion, RegistryValueKind.String);
                    key.SetValue("Publisher", "StrengW", RegistryValueKind.String);
                    key.SetValue("InstallLocation", installDir, RegistryValueKind.String);
                    key.SetValue("DisplayIcon", installedExe, RegistryValueKind.String);
                    key.SetValue("UninstallString", uninstallString, RegistryValueKind.String);
                    key.SetValue("QuietUninstallString", uninstallString + " -Silent", RegistryValueKind.String);
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }
            catch (Exception ex)
            {
                EmergencyLog("WARNING could not register Windows uninstall entry: " + ex.Message);
            }
        }

        private static void CopyRuntimeFile(string sourceDir, string destDir, string fileName, bool required)
        {
            string source = Path.Combine(sourceDir, fileName);
            string dest = Path.Combine(destDir, fileName);
            if (!File.Exists(source))
            {
                if (required) throw new FileNotFoundException("Required runtime file is missing", source);
                return;
            }
            File.Copy(source, dest, true);
        }

        private static void StopInstalledLauncherForUpdate(string installDir)
        {
            try
            {
                int selfPid = Process.GetCurrentProcess().Id;
                Process[] launchers = Process.GetProcessesByName("CodexBridgeLauncher");
                for (int i = 0; i < launchers.Length; i++)
                {
                    Process p = launchers[i];
                    try
                    {
                        if (p.Id == selfPid) continue;
                        string path = (p.MainModule == null) ? "" : p.MainModule.FileName;
                        if (string.IsNullOrEmpty(path)) continue;
                        string dir = Path.GetDirectoryName(path) ?? "";
                        if (!PathsEqual(dir, installDir)) continue;
                        p.Kill();
                        try { p.WaitForExit(5000); } catch { }
                    }
                    catch { }
                }
            }
            catch { }
        }

        private static bool InstallAndRelaunchIfNeeded(string[] args)
        {
            string sourceDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string installDir = StableInstallDir();
            if (PathsEqual(sourceDir, installDir))
            {
                // Respect the user's tray toggle. First install registers the CC Switch watcher,
                // but ordinary manual launches from the stable app folder must not
                // silently re-enable it after the user disabled auto-start with CC Switch.
                return false;
            }

            try
            {
                CapturePreinstallConfigIfNeeded();
                Directory.CreateDirectory(installDir);
                StopInstalledLauncherForUpdate(installDir);
                string installedExe = Path.Combine(installDir, "CodexBridgeLauncher.exe");
                File.Copy(Application.ExecutablePath, installedExe, true);
                bool hasStandaloneBridge = File.Exists(Path.Combine(sourceDir, "codex_provider_bridge.exe"));
                CopyRuntimeFile(sourceDir, installDir, "codex_provider_bridge.exe", hasStandaloneBridge);
                CopyRuntimeFile(sourceDir, installDir, "codex_provider_bridge.py", !hasStandaloneBridge);
                CopyRuntimeFile(sourceDir, installDir, "codex_bridge_manager.ps1", true);
                CopyRuntimeFile(sourceDir, installDir, "codex_bridge_manager.sh", false);
                CopyRuntimeFile(sourceDir, installDir, "CodexBridgeLauncher.ico", false);
                CopyRuntimeFile(sourceDir, installDir, "codex_bridge_launcher.ps1", false);
                CopyRuntimeFile(sourceDir, installDir, "UninstallCodexBridge.ps1", true);
                StopCcSwitchWatcher();
                RegisterStableAutostart(installedExe);
                RegisterWindowsUninstallEntry(installedExe, installDir);

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = installedExe;
                psi.Arguments = "--installed";
                psi.UseShellExecute = true;
                psi.WorkingDirectory = installDir;
                Process.Start(psi);
                EmergencyLog("Installed/updated stable launcher at " + installDir + "; resident Windows autostart enabled; relaunched installed copy.");
                return true;
            }
            catch (Exception ex)
            {
                EmergencyLog("Stable install/update failed: " + ex);
                try
                {
                    MessageBox.Show("Could not install Codex Bridge into %LOCALAPPDATA%\\CodexProviderBridge\\app.\r\n\r\n" + ex.Message,
                        "Codex Bridge Launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                catch { }
                return false;
            }
        }

        private const string FullLauncherMutexName = "Local\\CodexProviderBridgeNativeLauncher";
        private const string CcSwitchWatcherMutexName = "Local\\CodexProviderBridgeCcSwitchWatcher";
        private const string CcSwitchWatcherStopEventName = "Local\\CodexProviderBridgeCcSwitchWatcherStop";

        private static bool HasArg(string[] args, string wanted)
        {
            if (args == null) return false;
            for (int i = 0; i < args.Length; i++)
            {
                if (string.Equals(args[i], wanted, StringComparison.OrdinalIgnoreCase)) return true;
            }
            return false;
        }

        private static void StaticLauncherLog(string message)
        {
            try
            {
                string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge");
                Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "launcher.log"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + message + Environment.NewLine,
                    new UTF8Encoding(false));
            }
            catch { }
        }

        private static bool IsFullLauncherRunning()
        {
            try
            {
                using (Mutex existing = Mutex.OpenExisting(FullLauncherMutexName)) { return true; }
            }
            catch (WaitHandleCannotBeOpenedException) { return false; }
            catch (UnauthorizedAccessException) { return true; }
            catch { return false; }
        }

        private static bool IsCcSwitchRunning()
        {
            string[] names = new string[] { "cc-switch", "CC Switch", "cc_switch", "ccswitch" };
            for (int i = 0; i < names.Length; i++)
            {
                Process[] found = null;
                try
                {
                    found = Process.GetProcessesByName(names[i]);
                    if (found != null && found.Length > 0) return true;
                }
                catch { }
                finally
                {
                    if (found != null)
                    {
                        for (int j = 0; j < found.Length; j++)
                        {
                            try { found[j].Dispose(); } catch { }
                        }
                    }
                }
            }
            return false;
        }

        private static void LaunchFullLauncherFromWatcher(string exePath)
        {
            try
            {
                if (IsFullLauncherRunning()) return;
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = exePath;
                psi.Arguments = "--ccswitch-trigger";
                psi.UseShellExecute = true;
                psi.WorkingDirectory = Path.GetDirectoryName(exePath) ?? StableInstallDir();
                Process.Start(psi);
                StaticLauncherLog("CC Switch watcher launched the tray launcher.");
            }
            catch (Exception ex)
            {
                StaticLauncherLog("WARNING CC Switch watcher could not launch tray launcher: " + ex.Message);
            }
        }

        internal static void EnsureCcSwitchWatcherRunning(string exePath)
        {
            try
            {
                bool alreadyRunning = false;
                try
                {
                    using (Mutex existing = Mutex.OpenExisting(CcSwitchWatcherMutexName)) { alreadyRunning = true; }
                }
                catch (WaitHandleCannotBeOpenedException) { }
                catch (UnauthorizedAccessException) { alreadyRunning = true; }
                if (alreadyRunning) return;

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = exePath;
                psi.Arguments = "--watch-ccswitch";
                psi.UseShellExecute = true;
                psi.WorkingDirectory = Path.GetDirectoryName(exePath) ?? StableInstallDir();
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                StaticLauncherLog("WARNING could not start CC Switch watcher: " + ex.Message);
            }
        }

        internal static void StopCcSwitchWatcher()
        {
            try
            {
                using (EventWaitHandle stop = EventWaitHandle.OpenExisting(CcSwitchWatcherStopEventName))
                {
                    stop.Set();
                }
            }
            catch (WaitHandleCannotBeOpenedException) { }
            catch (Exception ex) { StaticLauncherLog("WARNING could not stop CC Switch watcher: " + ex.Message); }
        }

        private static void RunCcSwitchWatcher()
        {
            bool createdNew;
            using (Mutex watcherMutex = new Mutex(true, CcSwitchWatcherMutexName, out createdNew))
            {
                if (!createdNew) return;
                using (EventWaitHandle stop = new EventWaitHandle(false, EventResetMode.AutoReset, CcSwitchWatcherStopEventName))
                {
                    string exePath = Application.ExecutablePath;
                    StaticLauncherLog("CC Switch trigger watcher started. It will launch Codex Bridge when CC Switch is running.");
                    DateTime lastLaunchAttemptUtc = DateTime.MinValue;
                    while (true)
                    {
                        if (stop.WaitOne(700)) break;
                        if (!IsCcSwitchRunning()) continue;
                        if (IsFullLauncherRunning()) continue;
                        if ((DateTime.UtcNow - lastLaunchAttemptUtc).TotalSeconds < 3) continue;
                        lastLaunchAttemptUtc = DateTime.UtcNow;
                        LaunchFullLauncherFromWatcher(exePath);
                    }
                    StaticLauncherLog("CC Switch trigger watcher stopped.");
                }
                try { watcherMutex.ReleaseMutex(); } catch { }
            }
        }

        private static bool SourceIsNewerThanExe(string baseDir)
        {
            try
            {
                string exe = Application.ExecutablePath;
                if (string.IsNullOrEmpty(exe) || !File.Exists(exe)) return false;
                DateTime exeTime = File.GetLastWriteTimeUtc(exe);
                string[] inputs = new string[]
                {
                    Path.Combine(baseDir, "CodexBridgeLauncher.cs"),
                    Path.Combine(baseDir, "CodexBridgeLauncher.ico")
                };
                for (int i = 0; i < inputs.Length; i++)
                {
                    if (File.Exists(inputs[i]) && File.GetLastWriteTimeUtc(inputs[i]) > exeTime.AddMilliseconds(500)) return true;
                }
            }
            catch { }
            return false;
        }

        private static bool ScheduleSelfRebuildIfNeeded()
        {
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (!SourceIsNewerThanExe(baseDir)) return false;
                string builder = Path.Combine(baseDir, "BuildCodexBridgeLauncher.ps1");
                if (!File.Exists(builder)) return false;

                string runtimeDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge", "launcher-runtime");
                Directory.CreateDirectory(runtimeDir);
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Program.PowerShellExePath();
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + builder.Replace("\"", "\\\"") + "\" -LaunchAfterBuild -WaitForPid " + Process.GetCurrentProcess().Id;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = runtimeDir;
                Process.Start(psi);
                EmergencyLog("Launcher source/icon is newer than EXE; scheduled silent self-rebuild and relaunch.");
                return true;
            }
            catch (Exception ex)
            {
                EmergencyLog("Self-rebuild scheduling failed: " + ex);
                return false;
            }
        }

        [STAThread]
        private static void Main(string[] args)
        {
            if (ScheduleSelfRebuildIfNeeded()) return;
            if (InstallAndRelaunchIfNeeded(args)) return;
            if (HasArg(args, "--watch-ccswitch"))
            {
                RunCcSwitchWatcher();
                return;
            }

            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += delegate(object sender, ThreadExceptionEventArgs e)
            {
                EmergencyLog("UI thread exception: " + e.Exception);
            };
            AppDomain.CurrentDomain.UnhandledException += delegate(object sender, UnhandledExceptionEventArgs e)
            {
                EmergencyLog("Unhandled exception (terminating=" + e.IsTerminating + "): " + (e.ExceptionObject == null ? "<null>" : e.ExceptionObject.ToString()));
            };

            bool createdNew;
            Mutex mutex = new Mutex(true, FullLauncherMutexName, out createdNew);
            if (!createdNew)
            {
                if (!HasArg(args, "--ccswitch-trigger") && !HasArg(args, "--autostart"))
                {
                    MessageBox.Show("Codex Bridge Launcher is already running in the system tray.", "Codex Bridge Launcher", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
                mutex.Dispose();
                return;
            }

            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new LauncherContext(mutex));
            }
            catch (Exception ex)
            {
                EmergencyLog("Fatal launcher exception: " + ex);
                try
                {
                    MessageBox.Show("Codex Bridge Launcher crashed. See %LOCALAPPDATA%\\CodexProviderBridge\\launcher-crash.log",
                        "Codex Bridge Launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                catch { }
            }
        }
    }
}
