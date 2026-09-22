using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
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
        private readonly LauncherUiText ui = new LauncherUiText();
        private readonly Dictionary<string, string> state = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private string lastHandledKey = "";
        private string pendingKey = "";
        private DateTime pendingSinceUtc = DateTime.MinValue;
        private bool baselineInitialized;
        private string lastLoggedRouteSig = "";
        private bool handling;
        private bool thirdPartyProxyUnavailable;
        // Set only while the bounded Provider/auth repair restart is running, so the
        // proxy supervisor stays quiet during the expected :15721 drop. Cleared in a
        // finally. It never triggers a restart by itself.
        private volatile bool ccSwitchRepairInProgress;
        // One-shot latch: the route key for which a repair restart was already
        // attempted within the current switch edge. Re-armed at the start of every
        // genuine switch edge so returning to the SAME third-party provider is
        // repaired again.
        private string ccSwitchRepairDoneKey = "";
        // Deferred reconciliation: when a switch edge's action is suppressed by the
        // cooldown or an open flap circuit, the edge is already consumed
        // (lastHandledKey advanced), so remember the route key and re-apply it once
        // the route settles and the guard clears. Without this a rate-limited switch
        // leaves Codex on a stale config and CC Switch unrepaired (login screen later).
        private string pendingRouteReconcileKey = "";
        private const string ReconcileSentinelKey = "__reconcile_pending__";
        // Circuit breaker against a route-flap Codex restart storm. While CC Switch
        // and the Bridge settle a handoff, route_kind can oscillate
        // (official<->third-party); each oscillation edge would otherwise restart
        // Codex, so restarts are rate limited and, after repeated flaps, paused
        // until the route stays stable again.
        private DateTime lastRouteRestartUtc = DateTime.MinValue;
        private DateTime flapStableSinceUtc = DateTime.MinValue;
        private int suppressedRouteRestartCount;
        private bool routeFlapCircuitOpen;
        private const double RouteRestartCooldownSeconds = 8.0;
        private const int RouteFlapThreshold = 3;
        private const double RouteFlapSettleSeconds = 15.0;
        private volatile bool exiting;
        private ToolStripMenuItem statusItem;
        private ToolStripMenuItem pauseItem;
        private bool paused;
        // Durable "restart Codex" reminder. An editor-hosted Codex backend is never
        // terminated, so a provider switch only takes effect after the user reloads
        // Codex. A balloon alone is far too easy to miss: Windows shows it for a few
        // seconds and keeps no record of it (runtime evidence: the toast is delivered
        // and cleared ~7s later, and never reaches the notification store). The tray
        // therefore also carries a badge, a tooltip and a bold menu line until the
        // Codex process identity actually changes.
        private ToolStripMenuItem pendingRestartItem;
        private Icon badgedTrayIcon;
        private string pendingCodexRestartReason = "";
        private string pendingCodexProcessSig = "";
        private DateTime lastPendingCodexCheckUtc = DateTime.MinValue;
        // Guards the modal restart dialog. Read and written only inside the UI-thread
        // callback that raises it, so switches arriving while one dialog is already
        // waiting cannot stack a second dialog on top.
        private bool restartDialogOpen;
        // Dedicated UI-thread dispatcher with a real handle, created on the UI thread in
        // the constructor. The tray menu cannot serve as the dispatcher: its handle is
        // created lazily on the first right-click and, until then,
        // ToolStrip.InvokeRequired reports FALSE, so a worker thread (the switch handler
        // runs on the thread pool) would run the action on itself. A modal dialog created
        // on a pool thread has no UI message pump and no foreground rights, which is how
        // the restart reminder ended up behind the user's editor instead of on top of it.
        private readonly Control uiDispatcher;
        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint flags);
        private static readonly IntPtr HwndTopMost = new IntPtr(-1);
        private const uint SwpNoMove = 0x0002;
        private const uint SwpNoSize = 0x0001;
        private const uint SwpNoActivate = 0x0010;
        private readonly string installDir;
        private const string StartupRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValueName = "CodexBridgeLauncher";
        public LauncherContext(Mutex singleInstanceMutex)
        {
            mutex = singleInstanceMutex;
            // Bind the dispatcher to this (UI) thread before any worker can use it.
            // Control.CreateControl() skips controls that are not visible, so the handle is
            // forced through the Handle property instead: it creates the handle
            // unconditionally, on this (UI) thread.
            uiDispatcher = new Control();
            uiDispatcher.Handle.ToString();
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
            tray.Text = ui.T("Codex Bridge Launcher");
            tray.Visible = true;
            tray.ContextMenuStrip = BuildMenu();
            tray.DoubleClick += delegate { OpenLogFolder(); };

            Log("Launcher " + LauncherVersion + " started. base=" + baseDir + "; cwd=" + Environment.CurrentDirectory);
            Log("Policy: CC Switch is the upstream lifecycle owner. CodexBridge never revives CC Switch in the background when proxy :15721 drops or the user closes it, and never selects or launches it via system discovery, a remembered path, or a default install path. The single exception is the provable Provider/auth switch repair flow, which may restart the already-bound live instance once (bounded, loop-free). Official routes may run with CC Switch closed. Exit CodexBridge is an explicit shutdown and keeps the lightweight watcher alive.");
            Log("Tray initialized; startup background failures are isolated from the UI process.");
            bool watcherStartupEnabled = Program.IsWatcherStartupRegistered();
            Log("CC Switch watcher startup: " + (watcherStartupEnabled ? "enabled" : "not registered") + "; installed_app=" + installDir);

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
                    try { Balloon(ui.T("Codex Bridge Launcher"), ui.T("Bridge startup failed. Launcher is still running; open Launcher Log for details."), ToolTipIcon.Error); } catch { }
                }
            });

            pollTimer = new System.Windows.Forms.Timer();
            pollTimer.Interval = 400;
            pollTimer.Tick += PollTimerTick;
            pollTimer.Start();

            UpdateStatusText(ui.T("Starting / waiting for route..."));
            Balloon(ui.T("Codex Bridge Launcher"),
                ui.T("Ready. The CC Switch watcher starts with Windows and launches CodexBridge when CC Switch opens."), ToolTipIcon.Info);
            CheckForUpdates(false);
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
            statusItem = new ToolStripMenuItem(ui.T("Status: starting..."));
            statusItem.Enabled = false;
            menu.Items.Add(statusItem);
            pendingRestartItem = new ToolStripMenuItem(ui.T("Restart Codex in your editor to apply the new provider"));
            pendingRestartItem.Enabled = false;
            pendingRestartItem.Visible = false;
            try { pendingRestartItem.Font = new Font(pendingRestartItem.Font, FontStyle.Bold); } catch { }
            menu.Items.Add(pendingRestartItem);
            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem restartCodex = new ToolStripMenuItem(ui.T("Restart Codex"));
            restartCodex.Click += delegate { QueueManualAction(ui.T("Manual Codex restart"), delegate { RestartCodex("manual tray action"); }); };
            menu.Items.Add(restartCodex);

            ToolStripMenuItem ensureBridge = new ToolStripMenuItem(ui.T("Ensure Bridge Running"));
            ensureBridge.Click += delegate { QueueManualAction(ui.T("Ensure Bridge"), EnsureBridgeRunning); };
            menu.Items.Add(ensureBridge);

            pauseItem = new ToolStripMenuItem(ui.T("Pause automatic restarts"));
            pauseItem.CheckOnClick = true;
            pauseItem.CheckedChanged += delegate
            {
                paused = pauseItem.Checked;
                Log(paused ? "Automatic restart watcher paused." : "Automatic restart watcher resumed.");
                UpdateStatusText(ui.T(paused ? "Paused" : "Watching provider switches"));
            };
            menu.Items.Add(pauseItem);

            ToolStripMenuItem openAppFolder = new ToolStripMenuItem(ui.T("Open Installed App Folder"));
            openAppFolder.Click += delegate { OpenFolder(installDir); };
            menu.Items.Add(openAppFolder);

            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem openBridge = new ToolStripMenuItem(ui.T("Open Bridge Runtime Log"));
            openBridge.Click += delegate { OpenTextFile(bridgeStderrLog); };
            menu.Items.Add(openBridge);

            ToolStripMenuItem openBridgeStartup = new ToolStripMenuItem(ui.T("Open Bridge Startup Log"));
            openBridgeStartup.Click += delegate { OpenTextFile(bridgeStdoutLog); };
            menu.Items.Add(openBridgeStartup);

            ToolStripMenuItem openLauncher = new ToolStripMenuItem(ui.T("Open Launcher Log"));
            openLauncher.Click += delegate { OpenTextFile(launcherLog); };
            menu.Items.Add(openLauncher);

            ToolStripMenuItem openFolder = new ToolStripMenuItem(ui.T("Open Log Folder"));
            openFolder.Click += delegate { OpenLogFolder(); };
            menu.Items.Add(openFolder);

            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem checkUpdates = new ToolStripMenuItem(ui.T("Check for Updates..."));
            checkUpdates.Click += delegate { CheckForUpdates(true); };
            menu.Items.Add(checkUpdates);

            menu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem exit = new ToolStripMenuItem(ui.T("Exit CodexBridge..."));
            exit.Click += delegate { ExitLauncher(); };
            menu.Items.Add(exit);

            ToolStripMenuItem uninstall = new ToolStripMenuItem(ui.T("Uninstall CodexBridge..."));
            uninstall.Click += delegate { UninstallCodexBridge(); };
            menu.Items.Add(uninstall);
            return menu;
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
                    Balloon(ui.T("Codex Bridge Launcher"), ui.F("{0} failed: {1}", name, ex.Message), ToolTipIcon.Error);
                }
            });
        }

        private void PollTimerTick(object sender, EventArgs e)
        {
            if (exiting) return;
            // Deliberately independent of "paused": this only notices that the user has
            // already reloaded Codex, so the durable reminder can be withdrawn.
            ClearPendingCodexRestartIfApplied();
            if (paused) return;
            RouteSnapshot route = ReadRouteSnapshot();
            if (route == null) return;

            // Diagnostic: log the raw sidecar identity whenever it changes, so a switch
            // that fails to trigger can be traced to the exact fields the bridge wrote.
            string routeSig = route.Kind + "|model=" + route.Model + "|source=" + route.Source;
            if (routeSig != lastLoggedRouteSig)
            {
                lastLoggedRouteSig = routeSig;
                Log("Route snapshot: kind=" + route.Kind + "; model=" + route.Model +
                    "; source=" + route.Source + "; key=" + route.Key);
            }

            if (!baselineInitialized)
            {
                baselineInitialized = true;
                lastHandledKey = route.Key;
                SaveStateValue("last_handled_route", lastHandledKey);
                pendingKey = "";
                UpdateStatusText(ui.F("Route: {0}", FriendlyRoute(route)));
                Log("Initial route: " + route.Key + ". No restart triggered.");
                SuperviseThirdPartyProxy(route);
                return;
            }

            if (route.Key == lastHandledKey)
            {
                pendingKey = "";
                // The route is stable on this tick. If the flap circuit is open,
                // re-arm it only after the route has stayed stable long enough, so a
                // self-sustaining oscillation cannot resume restarting Codex.
                if (routeFlapCircuitOpen)
                {
                    if (flapStableSinceUtc == DateTime.MinValue) flapStableSinceUtc = DateTime.UtcNow;
                    else if ((DateTime.UtcNow - flapStableSinceUtc).TotalSeconds >= RouteFlapSettleSeconds)
                    {
                        routeFlapCircuitOpen = false;
                        suppressedRouteRestartCount = 0;
                        lastRouteRestartUtc = DateTime.UtcNow;
                        flapStableSinceUtc = DateTime.MinValue;
                        Log("Route flap circuit re-armed after the route stayed stable.");
                    }
                }
                // Deferred reconciliation: a switch whose action was suppressed by the
                // cooldown or an open circuit is still pending. Now that the route has
                // settled here and the guard has cleared, re-handle it once as a fresh
                // edge so the final provider ends repaired/restarted instead of stale
                // (Codex on an old config, or CC Switch left unrepaired).
                if (pendingRouteReconcileKey == route.Key && !routeFlapCircuitOpen && !handling)
                {
                    double sinceLastRestart = (DateTime.UtcNow - lastRouteRestartUtc).TotalSeconds;
                    if (lastRouteRestartUtc == DateTime.MinValue || sinceLastRestart >= RouteRestartCooldownSeconds)
                    {
                        pendingRouteReconcileKey = "";
                        // Force the settled route to be picked up again by the edge path.
                        lastHandledKey = ReconcileSentinelKey;
                        Log("Reconciling settled route after a suppressed switch: " + route.Key);
                    }
                }
                // A third-party route depends on the CC Switch proxy at :15721.
                // Observe availability without controlling the upstream process.
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
            flapStableSinceUtc = DateTime.MinValue;
            handling = true;
            UpdateStatusText(ui.F("Switching: {0}", FriendlyRoute(route)));
            Log("Provider switch detected: " + route.Key);

            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    if (exiting) return;
                    // A genuine switch edge re-arms the one-shot repair latch, so
                    // returning to the SAME third-party provider (e.g. DeepSeek ->
                    // Official -> DeepSeek) is repaired again instead of falling
                    // straight to the login screen. This runs BEFORE the flap-circuit
                    // gate so the bookkeeping is never skipped while the circuit is open.
                    ccSwitchRepairDoneKey = "";
                    // Settle briefly on a third-party edge so CC Switch finishes moving
                    // auth.json to its no-live-ChatGPT-credential state before we read it;
                    // a just-left Official credential would otherwise mask the repair need.
                    if (string.Equals(route.Kind, "third-party", StringComparison.OrdinalIgnoreCase))
                        Thread.Sleep(800);
                    if (exiting) return;
                    // While the flap circuit is open, pause ALL route-triggered
                    // disruption (the plain Codex restart and the CC Switch repair) so
                    // a flapping route cannot keep restarting anything.
                    if (routeFlapCircuitOpen)
                    {
                        // Defer to reconciliation: this edge is already consumed, so
                        // remember it and re-apply once the route settles and re-arms.
                        pendingRouteReconcileKey = route.Key;
                        Log("WARNING route-switch handling paused: flap circuit is open (key=" + route.Key + ").");
                        return;
                    }
                    if (string.Equals(route.Kind, "third-party", StringComparison.OrdinalIgnoreCase))
                    {
                        // Edge-triggered Provider/auth repair: EVERY genuine switch onto
                        // a third-party route restarts the already-bound live CC Switch
                        // instance ONCE (bounded, loop-free) so it re-materializes a
                        // consistent credential, then reloads Codex. Third-party mode pins
                        // requires_openai_auth=true while CC Switch moves auth.json off the
                        // live ChatGPT credential, so reloading Codex without first
                        // restarting CC Switch lands on the login screen. Gating this on a
                        // point-in-time credential read raced with CC Switch's own write and
                        // silently skipped the repair on a repeat switch to the SAME provider
                        // (Official -> DeepSeek -> Official -> DeepSeek). The one-shot latch
                        // still bounds it to once per edge and the flap circuit still bounds
                        // rapid switching, so it never revives CC Switch on a proxy drop or
                        // after the user closes it.
                        if (ccSwitchRepairDoneKey != route.Key)
                        {
                            bool repaired = false;
                            ccSwitchRepairInProgress = true;
                            try
                            {
                                UpdateStatusText(ui.T("Repairing provider switch (restarting CC Switch once)..."));
                                string boundPath;
                                if (TryBindLiveCcSwitchExecutablePath(out boundPath))
                                    repaired = RestartBoundCcSwitchInstanceOnce(boundPath);
                                else
                                    Log("WARNING CC Switch repair skipped: no live verified CC Switch instance to bind.");
                                ccSwitchRepairDoneKey = route.Key;
                            }
                            finally
                            {
                                ccSwitchRepairInProgress = false;
                            }

                            if (repaired)
                            {
                                Log("Third-party switch repaired; restarting Codex against the restored credential.");
                                // A successful bounded repair always reloads Codex and
                                // re-arms the flap circuit breaker (repair is one-shot per key).
                                suppressedRouteRestartCount = 0;
                                routeFlapCircuitOpen = false;
                                lastRouteRestartUtc = DateTime.UtcNow;
                                pendingRouteReconcileKey = "";
                                RestartCodex("third-party route " + route.Model + " after CC Switch repair");
                            }
                            else if (IsThirdPartyAuthRepairNeeded(route))
                            {
                                // CC Switch could not be restarted and the credential is
                                // genuinely absent: reloading Codex now would land on the
                                // login screen, so skip it and ask the user to reopen CC
                                // Switch. This edge is TERMINAL: do NOT set
                                // pendingRouteReconcileKey here. Deferring a FAILED repair
                                // to reconciliation re-fires the same edge, re-arms the
                                // one-shot latch, and kills/relaunches CC Switch forever
                                // (the observed infinite restart loop). The next genuine
                                // provider switch re-arms the latch and retries once.
                                Balloon(ui.T("Provider switch repair"), ui.T("Repair failed: please reopen CC Switch, then switch the provider again."), ToolTipIcon.Warning);
                                Log("WARNING third-party auth repair did not complete; skipping Codex restart to avoid the login screen. Not reconciling: a failed repair must not retry in a loop.");
                                return;
                            }
                            else
                            {
                                // CC Switch was not running to repair, but a live credential
                                // is present, so reloading Codex is safe.
                                if (!RestartCodexForRouteSwitch("third-party route " + route.Model, route.Key))
                                {
                                    pendingRouteReconcileKey = route.Key;
                                    return;
                                }
                                pendingRouteReconcileKey = "";
                            }
                        }
                        else
                        {
                            if (!RestartCodexForRouteSwitch("third-party route " + route.Model, route.Key))
                            {
                                pendingRouteReconcileKey = route.Key;
                                return;
                            }
                            pendingRouteReconcileKey = "";
                        }
                    }
                    else
                    {
                        Thread.Sleep(300);
                        if (exiting) return;
                        if (!RestartCodexForRouteSwitch("Official route / ChatGPT account reload", route.Key))
                        {
                            pendingRouteReconcileKey = route.Key;
                            return;
                        }
                        pendingRouteReconcileKey = "";
                    }
                    Log("Switch handling complete. Bridge was not restarted; CC Switch remained under user control.");
                    Balloon(ui.T("Provider switch complete"), ui.F("{0} is ready. Bridge remained resident.", FriendlyRoute(route)), ToolTipIcon.Info);
                }
                catch (Exception ex)
                {
                    Log("ERROR handling switch: " + ex);
                    Balloon(ui.T("Provider switch failed"), ex.Message, ToolTipIcon.Error);
                }
                finally
                {
                    handling = false;
                    UpdateStatusText(ui.F("Route: {0}", FriendlyRoute(route)));
                }
            });
        }

        private string FriendlyRoute(RouteSnapshot route)
        {
            if (route == null) return ui.T("unknown");
            return ui.Route(route.Kind, route.Model);
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
            // Key the switch edge on the route MODEL. Runtime evidence (the "Route
            // snapshot" diagnostic in PollTimerTick) proved the sidecar's source_path is
            // CONSTANT across every provider -- CC Switch writes all providers into one
            // cc-switch-model-catalog.json -- so source_path cannot distinguish one
            // third-party provider from another, while route_model changes on every real
            // switch (Official gpt-* -> third-party glm-*/deepseek-*). Kind is folded in
            // so Official <-> third-party always produces an edge.
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

        // Read-only check for the provable Provider/auth repair condition:
        // third-party route + active custom provider requires_openai_auth=true +
        // auth.json has no live ChatGPT credential. Never writes auth.json; logs
        // only structural booleans (token values are never read into a log).
        private bool IsThirdPartyAuthRepairNeeded(RouteSnapshot route)
        {
            try
            {
                if (route == null || !string.Equals(route.Kind, "third-party", StringComparison.OrdinalIgnoreCase))
                    return false;

                string configPath = Path.Combine(codexHome, "config.toml");
                if (!File.Exists(configPath)) return false;
                string text = File.ReadAllText(configPath);
                Match provider = Regex.Match(text, "(?m)^\\s*model_provider\\s*=\\s*[\"']custom[\"']\\s*(?:#.*)?$");
                if (!provider.Success) return false;
                Match section = Regex.Match(text,
                    "(?ms)^\\s*\\[model_providers\\.(?:custom|\"custom\")\\]\\s*$([\\s\\S]*?)(?=^\\s*\\[|\\z)");
                if (!section.Success) return false;
                Match requiresAuth = Regex.Match(section.Groups[1].Value,
                    "(?m)^\\s*requires_openai_auth\\s*=\\s*true\\s*(?:#.*)?$");
                if (!requiresAuth.Success) return false;

                bool liveCred = HasLiveChatGptCredential();
                Log("Third-party auth repair check: requires_openai_auth=true; live_chatgpt_cred=" + (liveCred ? "true" : "false"));
                return !liveCred;
            }
            catch (Exception ex)
            {
                Log("WARNING third-party auth repair check failed: " + ex.Message);
                return false;
            }
        }

        // Read-only structural check of ~/.codex/auth.json for a live ChatGPT
        // credential (a non-empty access_token or refresh_token). Never writes
        // auth.json and never logs token values.
        private bool HasLiveChatGptCredential()
        {
            try
            {
                string authPath = Path.Combine(codexHome, "auth.json");
                if (!File.Exists(authPath)) return false;
                string json = ReadTextFileSafe(authPath);
                if (string.IsNullOrEmpty(json)) return false;
                string access = JsonString(json, "access_token");
                string refresh = JsonString(json, "refresh_token");
                return !string.IsNullOrEmpty(access) || !string.IsNullOrEmpty(refresh);
            }
            catch { return false; }
        }

        private void EnsureBridgeRunning()
        {
            lock (bridgeLifecycleSync)
            {
                if (exiting)
                {
                    Log("Skipping Bridge ensure because Exit CodexBridge is in progress.");
                    return;
                }

                if (!File.Exists(managerScript))
                {
                    Log("ERROR bridge manager not found: " + managerScript);
                    Balloon(ui.T("Codex Bridge Launcher"), ui.T("codex_bridge_manager.ps1 not found next to the launcher."), ToolTipIcon.Error);
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
                            Log("Bridge manager startup was cancelled during Exit CodexBridge.");
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
                        Log("Bridge manager startup finished/cancelled during Exit CodexBridge; ignoring its result.");
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

                // Exit CodexBridge may be confirmed while a startup ensure that began earlier
                // is still waiting for the manager. Never let that stale ensure restart Codex.
                if (exiting)
                {
                    Log("Bridge ensure completed during Exit CodexBridge; skipping post-ensure Codex restart.");
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
            // Stay quiet during the bounded repair restart: the :15721 drop there is
            // expected and must not be reported as unavailable or trigger anything.
            if (ccSwitchRepairInProgress) return;
            bool available = TestTcpPort("127.0.0.1", 15721, 120);
            if (available)
            {
                if (thirdPartyProxyUnavailable)
                {
                    thirdPartyProxyUnavailable = false;
                    Log("Third-party route recovered: CC Switch proxy :15721 is available again.");
                    Balloon(ui.T("CC Switch proxy restored"), ui.F("Third-party route {0} is available again.", route.Model), ToolTipIcon.Info);
                }
                return;
            }

            if (thirdPartyProxyUnavailable) return;
            thirdPartyProxyUnavailable = true;
            UpdateStatusText(ui.F("Third-party route unavailable: {0}", route.Model));
            Log("Third-party route unavailable: CC Switch is not running or proxy :15721 is unavailable. CodexBridge will not start or restart CC Switch.");
            Balloon(ui.T("CC Switch proxy unavailable"), ui.T("Third-party route unavailable: please open CC Switch."), ToolTipIcon.Warning);
        }

        private void RestartCodex(string reason, bool allowDuringExit = false)
        {
            if (exiting && !allowDuringExit)
            {
                Log("Skipping Codex restart because Exit CodexBridge is in progress: " + reason);
                return;
            }
            Log("Restarting Codex: " + reason);
            List<Process> processes = FindCodexProcesses();
            if (processes.Count == 0)
            {
                Log("Codex is not running; nothing to restart.");
                return;
            }
            // Every current Codex form is a headless "app-server" backend driven by a
            // GUI host (VS Code/Cursor, or the ChatGPT desktop app): codex.exe itself
            // never owns a top-level window, so MainWindowHandle is always 0 and there
            // is no standalone Codex GUI for CodexBridge to cycle. Terminating a
            // host-owned backend leaves the host on a "click to restart" page, and
            // because route switches repeat, CodexBridge would keep killing the
            // respawning backend and make that page flicker between the restart,
            // restarting and login states. So during normal operation never terminate
            // it: let the host own its lifecycle and ask the user to restart Codex so
            // it reloads the new route/credential.
            if (!exiting)
            {
                Log("Codex is a host-owned app-server backend (no GUI window of its own); not terminating it. Please restart Codex to apply: " + reason);
                RaisePendingCodexRestart(reason, processes);
                ShowRestartCodexDialog();
                Balloon(ui.T("Restart Codex to apply"), ui.T("Provider switched. Please restart Codex in your editor (VS Code/Cursor) to apply the new route."), ToolTipIcon.Info);
                return;
            }

            // Exit handoff only (exiting == true): really cycle the backend so the host
            // respawns it against the direct-Official config. Any outstanding reminder
            // is stale because this path does restart Codex.
            ClearPendingCodexRestart();
            for (int i = 0; i < processes.Count; i++) KillProcessTree(processes[i].Id);
            Thread.Sleep(700);
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

        // Restarts Codex for a route-switch edge, but rate limited: never more than
        // once per RouteRestartCooldownSeconds. A genuine user switch is seconds to
        // minutes apart; a flapping route (official<->third-party oscillation while a
        // handoff settles) re-arrives inside the cooldown, so its restarts are
        // suppressed. After RouteFlapThreshold suppressions the circuit opens and all
        // route-triggered restarts pause until the route has been stable, which breaks
        // the "stuck restarting Codex" loop. Returns false when the restart was skipped.
        private bool RestartCodexForRouteSwitch(string reason, string routeKey)
        {
            if (routeFlapCircuitOpen)
            {
                Log("WARNING route-switch Codex restart skipped: flap circuit is open (key=" + routeKey + ").");
                return false;
            }
            double sinceLast = (DateTime.UtcNow - lastRouteRestartUtc).TotalSeconds;
            if (lastRouteRestartUtc != DateTime.MinValue && sinceLast < RouteRestartCooldownSeconds)
            {
                suppressedRouteRestartCount++;
                Log("WARNING route-switch Codex restart suppressed to break a flap loop: key=" + routeKey +
                    "; since_last_restart_s=" + sinceLast.ToString("0.0", CultureInfo.InvariantCulture) +
                    "; suppressed_count=" + suppressedRouteRestartCount);
                if (suppressedRouteRestartCount >= RouteFlapThreshold)
                {
                    routeFlapCircuitOpen = true;
                    Log("ERROR route flap circuit opened after " + suppressedRouteRestartCount +
                        " suppressed restarts; automatic Codex restarts are paused until the route stays stable.");
                    Balloon(ui.T("Route flapping detected"), ui.T("The provider route kept flipping, so CodexBridge paused automatic Codex restarts to avoid a restart loop. Reopen CC Switch, then switch the provider once more; CodexBridge resumes automatically."), ToolTipIcon.Warning);
                }
                return false;
            }
            suppressedRouteRestartCount = 0;
            lastRouteRestartUtc = DateTime.UtcNow;
            RestartCodex(reason);
            return true;
        }

        private void RestartCodexForExit()
        {
            RestartCodex("Official direct handoff before Bridge stop", true);
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
                    string path = SafeProcessPath(p);
                    // Only the process name and the executable path may identify CC Switch.
                    // A window title is user-controlled (browser tabs, editors, chats) and must
                    // never decide which process gets killed or remembered as CC Switch.
                    if (IsCcSwitchName(name) || IsCcSwitchExecutablePath(path))
                    {
                        Log("Matched CC Switch process: name=" + name + "; path=" + (String.IsNullOrEmpty(path) ? "<unavailable>" : path));
                        result.Add(p);
                    }
                }
                catch { }
            }
            return result;
        }

        private static bool IsCcSwitchName(string value)
        {
            if (String.IsNullOrEmpty(value)) return false;
            return Regex.IsMatch(value, "(?i)^cc[-_ ]?switch$");
        }

        private static bool IsCcSwitchExecutablePath(string path)
        {
            if (String.IsNullOrEmpty(path)) return false;
            string fileName = "";
            string directoryName = "";
            try { fileName = Path.GetFileNameWithoutExtension(path) ?? ""; } catch { }
            try { directoryName = Path.GetFileName(Path.GetDirectoryName(path) ?? "") ?? ""; } catch { }
            return IsCcSwitchName(fileName) || IsCcSwitchName(directoryName);
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

        private static string SafeProcessPath(Process p)
        {
            try { return p.MainModule == null ? "" : p.MainModule.FileName; }
            catch { return ""; }
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
            RunOnUiThread(delegate
            {
                if (tray == null || tray.ContextMenuStrip == null) return;
                try { statusItem.Text = ui.Status(text); } catch { }
            });
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

        private static string ProcessSignature(List<Process> processes)
        {
            StringBuilder signature = new StringBuilder();
            for (int i = 0; i < processes.Count; i++)
            {
                try
                {
                    signature.Append(processes[i].Id.ToString(CultureInfo.InvariantCulture));
                    signature.Append(':');
                    signature.Append(processes[i].StartTime.ToFileTimeUtc().ToString(CultureInfo.InvariantCulture));
                    signature.Append('|');
                }
                catch { }
            }
            return signature.ToString();
        }

        private string CurrentCodexProcessSignature()
        {
            List<Process> processes = FindCodexProcesses();
            try { return ProcessSignature(processes); }
            finally
            {
                for (int i = 0; i < processes.Count; i++) { try { processes[i].Dispose(); } catch { } }
            }
        }

        private Icon BuildBadgedTrayIcon()
        {
            try
            {
                using (Bitmap canvas = new Bitmap(32, 32))
                {
                    using (Graphics g = Graphics.FromImage(canvas))
                    {
                        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                        g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                        using (Bitmap baseIcon = launcherIcon.ToBitmap())
                        {
                            g.DrawImage(baseIcon, new Rectangle(0, 0, 32, 32));
                        }
                        // Bottom-right red dot: "a provider switch is waiting for you".
                        using (SolidBrush fill = new SolidBrush(Color.FromArgb(255, 200, 32, 48))) g.FillEllipse(fill, 16, 16, 15, 15);
                        using (Pen ring = new Pen(Color.White, 2f)) g.DrawEllipse(ring, 17, 17, 13, 13);
                        // The native handle is intentionally kept for the process lifetime:
                        // the badge is built at most once and reused by every later reminder.
                        return Icon.FromHandle(canvas.GetHicon());
                    }
                }
            }
            catch (Exception ex)
            {
                Log("WARNING could not build the badged tray icon: " + ex.Message);
                return null;
            }
        }

        private void SetTrayTooltip(string text)
        {
            // NotifyIcon.Text throws past 63 characters; clamp rather than lose the badge.
            try { tray.Text = text.Length > 63 ? text.Substring(0, 63) : text; } catch { }
        }

        private void RaisePendingCodexRestart(string reason, List<Process> codexProcesses)
        {
            pendingCodexRestartReason = reason;
            pendingCodexProcessSig = ProcessSignature(codexProcesses);
            RunOnUiThread(delegate
            {
                if (tray == null) return;
                if (badgedTrayIcon == null) badgedTrayIcon = BuildBadgedTrayIcon();
                if (badgedTrayIcon != null) { try { tray.Icon = badgedTrayIcon; } catch { } }
                SetTrayTooltip(ui.T("CodexBridge: restart Codex to apply the new provider"));
                if (pendingRestartItem != null) pendingRestartItem.Visible = true;
            });
            UpdateStatusText(ui.T("Waiting for you to restart Codex"));
            Log("Persistent Codex-restart reminder raised; it stays in the tray until Codex is reloaded: " + reason);
        }

        private void ShowRestartCodexDialog()
        {
            // A modal alert matching the macOS launcher (which already raises its own
            // alert dialog). The balloon is transient and the tray badge is passive:
            // neither can interrupt a user who never looks at the tray, so a switch that
            // only takes effect after reloading Codex could silently stay unapplied.
            // Raised once per switch edge: while a dialog is already waiting, later
            // switches only refresh the tray reminder behind it.
            if (exiting) return;
            RunOnUiThread(delegate
            {
                if (exiting || restartDialogOpen) return;
                restartDialogOpen = true;
                try
                {
                    ShowRestartCodexDialogCore();
                }
                catch (Exception ex) { Log("WARNING could not show the restart-Codex dialog: " + ex.Message); }
                finally { restartDialogOpen = false; }
            });
        }

        private void ShowRestartCodexDialogCore()
        {
            // Not MessageBox: an ownerless MessageBox is an ordinary top-level window, and
            // the Windows foreground lock forbids a background process (this tray launcher)
            // from activating it, so the dialog opened BEHIND the maximized editor the user
            // was working in. A WS_EX_TOPMOST window is exempt from that rule: it stays
            // above every non-topmost window whether or not it is the active window.
            using (Form dialog = new Form())
            {
                dialog.Text = ui.T("Restart Codex to apply");
                dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialog.MinimizeBox = false;
                dialog.MaximizeBox = false;
                dialog.ShowInTaskbar = true;
                dialog.TopMost = true;
                dialog.StartPosition = FormStartPosition.CenterScreen;
                dialog.ClientSize = new Size(470, 210);

                PictureBox glyph = new PictureBox();
                glyph.Image = SystemIcons.Warning.ToBitmap();
                glyph.SizeMode = PictureBoxSizeMode.AutoSize;
                glyph.Location = new Point(20, 24);

                Label body = new Label();
                body.Text = ui.T("Provider switched. Please restart Codex in your editor (VS Code/Cursor) to apply the new route.")
                    + "\r\n\r\n"
                    + ui.T("Codex keeps the previous provider until it is reloaded. The tray warning stays until then, and this reminder returns on the next switch.");
                body.Location = new Point(74, 22);
                body.Size = new Size(dialog.ClientSize.Width - 94, dialog.ClientSize.Height - 82);

                Button confirm = new Button();
                confirm.Text = ui.T("OK");
                confirm.Size = new Size(88, 28);
                confirm.Location = new Point(dialog.ClientSize.Width - confirm.Width - 20, dialog.ClientSize.Height - confirm.Height - 16);
                confirm.DialogResult = DialogResult.OK;

                dialog.Controls.Add(glyph);
                dialog.Controls.Add(body);
                dialog.Controls.Add(confirm);
                dialog.AcceptButton = confirm;
                dialog.CancelButton = confirm;
                // Topmost is asserted once at creation; re-assert it after the window is
                // shown and once a second while it waits. The dialog is the last line of
                // defence for a switch that only takes effect after a Codex reload, so it
                // must stay reachable no matter what else the user puts on screen.
                // SWP_NOACTIVATE keeps the re-assert from stealing keyboard focus.
                dialog.Shown += delegate
                {
                    ReassertTopMost(dialog);
                    try { dialog.Activate(); } catch { }
                };
                System.Windows.Forms.Timer pin = new System.Windows.Forms.Timer();
                pin.Interval = 1000;
                pin.Tick += delegate { ReassertTopMost(dialog); };
                dialog.FormClosed += delegate { pin.Stop(); pin.Dispose(); };
                pin.Start();
                dialog.ShowDialog();
            }
        }

        private static void ReassertTopMost(Form dialog)
        {
            try
            {
                if (dialog == null || dialog.IsDisposed || !dialog.IsHandleCreated) return;
                SetWindowPos(dialog.Handle, HwndTopMost, 0, 0, 0, 0, SwpNoMove | SwpNoSize | SwpNoActivate);
            }
            catch { }
        }

        private void ClearPendingCodexRestart()
        {
            pendingCodexRestartReason = "";
            pendingCodexProcessSig = "";
            RunOnUiThread(delegate
            {
                if (tray == null) return;
                try { tray.Icon = launcherIcon; } catch { }
                SetTrayTooltip(ui.T("Codex Bridge Launcher"));
                if (pendingRestartItem != null) pendingRestartItem.Visible = false;
            });
        }

        private void ClearPendingCodexRestartIfApplied()
        {
            if (pendingCodexRestartReason.Length == 0) return;
            // Throttled: the poll timer ticks every 400ms while a user reload takes
            // seconds, and enumerating processes is not free.
            if ((DateTime.UtcNow - lastPendingCodexCheckUtc).TotalSeconds < 2.0) return;
            lastPendingCodexCheckUtc = DateTime.UtcNow;
            string current = CurrentCodexProcessSignature();
            if (current.Length == 0) return;               // Codex is not up yet; keep waiting.
            if (current == pendingCodexProcessSig) return; // Unchanged; the reminder still applies.
            Log("Codex was reloaded by the user; clearing the persistent restart reminder (was: " + pendingCodexRestartReason + ").");
            ClearPendingCodexRestart();
            UpdateStatusText(ui.T("Watching provider switches"));
        }

        private void CheckForUpdates(bool manual)
        {
            if (exiting || (!manual && !ShouldCheckForUpdates())) return;
            ReleaseUpdateChecker.CheckAsync(Program.PublicVersion, delegate(ReleaseUpdateResult result)
            {
                if (result == null) return;
                if (result.Status == ReleaseUpdateStatus.UpdateAvailable)
                {
                    Log("Update check: version " + result.LatestVersion + " is available (current " + Program.PublicVersion + ").");
                    SaveStateValue("latest_release_version", result.LatestVersion);
                    SaveStateValue("latest_release_url", result.ReleaseUrl);
                    RunOnUiThread(delegate { ShowUpdatePrompt(result); });
                }
                else if (result.Status == ReleaseUpdateStatus.Failed)
                {
                    Log("Update check failed: " + result.Error);
                    if (manual) ShowUpdateFailure(result.Error);
                }
                else if (manual)
                {
                    Log("Update check: already up to date (" + Program.PublicVersion + ").");
                    RunOnUiThread(delegate
                    {
                        Balloon(ui.T("CodexBridge is up to date"), ui.F("Current version: {0}.", Program.PublicVersion), ToolTipIcon.Info);
                    });
                }
            });
        }

        private void ShowUpdateFailure(string error)
        {
            RunOnUiThread(delegate
            {
                Balloon(
                    ui.T("Could not check for updates"),
                    ui.F("The latest release could not be checked. {0}", error) + " " +
                        ui.T("If this keeps failing, a proxy or firewall is usually blocking api.github.com."),
                    ToolTipIcon.Error);
            });
        }

        private bool ShouldCheckForUpdates()
        {
            DateTime previous;
            string value = GetState("update_checked_at_utc");
            if (DateTime.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out previous) &&
                (DateTime.UtcNow - previous.ToUniversalTime()).TotalHours < 24) return false;
            SaveStateValue("update_checked_at_utc", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            return true;
        }

        private void ShowUpdatePrompt(ReleaseUpdateResult result)
        {
            if (exiting) return;
            DialogResult answer = MessageBox.Show(
                ui.F("Version {0} is available (current {1}). Open the GitHub Release page now?", result.LatestVersion, Program.PublicVersion),
                ui.T("CodexBridge update available"),
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Information,
                MessageBoxDefaultButton.Button2);
            if (answer == DialogResult.Yes) OpenReleasePage(result.ReleaseUrl);
        }

        private void OpenReleasePage(string url)
        {
            try
            {
                if (String.IsNullOrEmpty(url) || !url.StartsWith("https://github.com/", StringComparison.OrdinalIgnoreCase)) url = ReleaseUpdateChecker.ReleaseUrl;
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = url;
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                Log("ERROR opening Release page: " + ex.Message);
            }
        }

        private void RunOnUiThread(Action action)
        {
            try
            {
                if (action == null) return;
                if (uiDispatcher.InvokeRequired) { uiDispatcher.BeginInvoke(action); return; }
                action();
            }
            catch (Exception ex) { Log("WARNING update UI callback failed: " + ex.Message); }
        }

        private void StopBridgeForUpdate()
        {
            // Serialize stop against any in-flight EnsureBridgeRunning call. This prevents
            // an older startup ensure from finishing after Exit CodexBridge and reviving the
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

        private void KillResidualBridgeProcesses()
        {
            string command = "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | " +
                "Where-Object { $_.CommandLine -match '(?i)codex_provider_bridge(?:\\.py)?' } | " +
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }";
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = Program.PowerShellExePath();
            psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -Command \"" + command.Replace("\"", "\\\"") + "\"";
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.WorkingDirectory = launcherRuntimeDir;
            try
            {
                using (Process p = Process.Start(psi))
                {
                    if (p != null && !p.WaitForExit(5000))
                    {
                        Log("WARNING residual Bridge cleanup command timed out; killing cleanup process.");
                        try { p.Kill(); } catch { }
                    }
                }
                Log("Residual Bridge cleanup scan completed.");
            }
            catch (Exception ex)
            {
                Log("WARNING residual Bridge cleanup scan failed: " + ex.Message);
            }
        }

        private void StopBridgeForExit()
        {
            if (!File.Exists(managerScript))
            {
                Log("WARNING Bridge manager not found during Exit CodexBridge: " + managerScript);
                return;
            }

            Log("Stopping resident Bridge for Exit CodexBridge (bounded path)...");
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = Program.PowerShellExePath();
            psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + managerScript.Replace("\"", "\\\"") + "\" stop";
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.WorkingDirectory = launcherRuntimeDir;
            Process manager = null;
            try
            {
                manager = Process.Start(psi);
                if (manager == null) throw new Exception("Could not start Bridge manager stop process.");
                if (!manager.WaitForExit(12000))
                {
                    Log("WARNING Bridge manager stop timed out after 12 seconds; killing manager and entering residual cleanup fallback.");
                    try { manager.Kill(); } catch { }
                    try { manager.WaitForExit(2000); } catch { }
                }
                else
                {
                    Log("Bridge stop command completed during Exit CodexBridge.");
                }
            }
            catch (Exception ex)
            {
                Log("WARNING Bridge manager stop failed during Exit CodexBridge: " + ex.Message);
            }
            finally
            {
                if (manager != null) try { manager.Dispose(); } catch { }
            }

            KillResidualBridgeProcesses();
            DateTime deadline = DateTime.UtcNow.AddSeconds(5);
            while (DateTime.UtcNow < deadline && TestTcpPort("127.0.0.1", 15722, 180)) Thread.Sleep(250);
            if (TestTcpPort("127.0.0.1", 15722, 180))
                Log("WARNING Bridge port :15722 is still listening after bounded cleanup.");
            else
                Log("Bridge port :15722 is no longer listening.");
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
                Log("CC Switch was already stopped during Exit CodexBridge.");
                WaitForPortClosed("CC Switch", 15721, 4000);
                return;
            }

            Log("Stopping CC Switch during Exit CodexBridge (graceful then bounded force stop)...");
            for (int i = 0; i < processes.Count; i++)
            {
                try
                {
                    if (processes[i].MainWindowHandle != IntPtr.Zero) processes[i].CloseMainWindow();
                }
                catch { }
            }

            DateTime gracefulDeadline = DateTime.UtcNow.AddSeconds(3);
            while (DateTime.UtcNow < gracefulDeadline && AnyProcessesAlive(processes)) Thread.Sleep(150);
            if (AnyProcessesAlive(processes))
            {
                Log("WARNING CC Switch graceful stop timed out; forcing remaining process trees.");
                for (int i = 0; i < processes.Count; i++)
                {
                    try { if (!processes[i].HasExited) KillProcessTree(processes[i].Id); } catch { }
                }
            }
            DateTime processDeadline = DateTime.UtcNow.AddSeconds(3);
            while (DateTime.UtcNow < processDeadline && AnyProcessesAlive(processes)) Thread.Sleep(150);
            if (AnyProcessesAlive(processes))
                Log("WARNING one or more CC Switch processes remain after bounded force stop.");
            else
                Log("CC Switch processes are no longer running.");
            for (int i = 0; i < processes.Count; i++) try { processes[i].Dispose(); } catch { }
            WaitForPortClosed("CC Switch", 15721, 5000);
            Log("CC Switch stop completed during Exit CodexBridge.");
        }

        private static bool AnyProcessesAlive(List<Process> processes)
        {
            for (int i = 0; i < processes.Count; i++)
            {
                try { if (!processes[i].HasExited) return true; } catch { }
            }
            return false;
        }

        private void WaitForPortClosed(string name, int port, int timeoutMilliseconds)
        {
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMilliseconds);
            while (DateTime.UtcNow < deadline && TestTcpPort("127.0.0.1", port, 180)) Thread.Sleep(200);
            if (TestTcpPort("127.0.0.1", port, 180)) Log("WARNING " + name + " port :" + port + " is still listening after stop.");
            else Log(name + " port :" + port + " is closed.");
        }

        // Bind ONLY the currently-running, path-verified CC Switch instance. The
        // bound path comes from the live process (SafeProcessPath, validated by
        // IsCcSwitchExecutablePath, never a window title). It is held in memory for
        // this single repair only: never discovered, never read from a persisted /
        // remembered / default install path, and never written back to state.
        private bool TryBindLiveCcSwitchExecutablePath(out string boundPath)
        {
            boundPath = "";
            List<Process> processes = FindCcSwitchProcesses();
            for (int i = 0; i < processes.Count; i++)
            {
                try
                {
                    if (processes[i].HasExited) continue;
                    string path = SafeProcessPath(processes[i]);
                    if (!string.IsNullOrEmpty(path) && IsCcSwitchExecutablePath(path))
                    {
                        boundPath = path;
                        break;
                    }
                }
                catch { }
            }
            for (int i = 0; i < processes.Count; i++) { try { processes[i].Dispose(); } catch { } }
            return !string.IsNullOrEmpty(boundPath);
        }

        // The ONLY new CC Switch stop+start path. Restarts the already-bound live
        // instance once, bounded and loop-free: graceful stop -> bounded force ->
        // wait :15721 closed -> relaunch the SAME bound path -> wait :15721 up ->
        // short settle for auth.json. Any failure/timeout returns false (no retry).
        private bool RestartBoundCcSwitchInstanceOnce(string boundPath)
        {
            if (string.IsNullOrEmpty(boundPath) || !File.Exists(boundPath))
            {
                Log("WARNING CC Switch repair aborted: bound executable path is not usable.");
                return false;
            }

            // CC Switch is a Tauri app that ignores WM_CLOSE (CloseMainWindow only hides
            // it to the tray), so a graceful stop always times out and wastes the restart
            // budget. Terminate the whole tree directly -- the approach that reliably
            // brought :15721 back -- then make sure every child (including WebView2) is
            // really gone and the port is released before relaunching, so the new instance
            // is not blocked by a leftover profile/instance lock and its route service binds.
            Log("CC Switch repair: stopping the bound instance (force; CC Switch ignores a graceful close)...");
            List<Process> processes = FindCcSwitchProcesses();
            for (int i = 0; i < processes.Count; i++)
            {
                try { if (!processes[i].HasExited) KillProcessTree(processes[i].Id); } catch { }
            }
            DateTime processDeadline = DateTime.UtcNow.AddSeconds(5);
            while (DateTime.UtcNow < processDeadline && AnyProcessesAlive(processes)) Thread.Sleep(150);
            for (int i = 0; i < processes.Count; i++) { try { processes[i].Dispose(); } catch { } }
            WaitForPortClosed("CC Switch", 15721, 5000);

            Log("CC Switch repair: relaunching the same bound instance...");
            if (!StartDetached(boundPath, ""))
            {
                Log("ERROR CC Switch repair could not relaunch the bound instance.");
                return false;
            }

            // CC Switch normally opens :15721 within a few seconds of launch. If it does
            // not, log whether the relaunched process is even still alive so a silent exit
            // (single-instance handoff / WebView2 profile lock) is visible in the log.
            DateTime proxyDeadline = DateTime.UtcNow.AddSeconds(20);
            int waitedMs = 0;
            bool proxyUp = TestTcpPort("127.0.0.1", 15721, 200);
            while (!proxyUp && DateTime.UtcNow < proxyDeadline)
            {
                Thread.Sleep(500);
                waitedMs += 500;
                if (waitedMs % 5000 == 0)
                    Log("CC Switch repair wait: :15721 still down after " + (waitedMs / 1000) +
                        "s; cc-switch processes alive=" + CountCcSwitchProcessesQuiet());
                proxyUp = TestTcpPort("127.0.0.1", 15721, 200);
            }
            if (!proxyUp)
            {
                Log("WARNING CC Switch repair timed out waiting for proxy :15721 to come back (cc-switch alive=" +
                    CountCcSwitchProcessesQuiet() + ").");
                return false;
            }
            Thread.Sleep(1500);
            Log("CC Switch repair completed: bound instance restarted and proxy :15721 is up.");
            return true;
        }

        // Quiet CC Switch process count for repair diagnostics. FindCcSwitchProcesses logs
        // every match, which is far too noisy to call inside a wait loop.
        private int CountCcSwitchProcessesQuiet()
        {
            int count = 0;
            Process[] all = Process.GetProcesses();
            for (int i = 0; i < all.Length; i++)
            {
                try
                {
                    string name = all[i].ProcessName ?? "";
                    if (IsCcSwitchName(name) || IsCcSwitchExecutablePath(SafeProcessPath(all[i]))) count++;
                }
                catch { }
                try { all[i].Dispose(); } catch { }
            }
            return count;
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
                    title = "警告：退出 CodexBridge？";
                    body =
                        "這將關閉 CodexBridge、Bridge 和 CC Switch。\r\n\r\n" +
                        "重新開啟 CC Switch 後，CodexBridge 會自動啟動。";
                }
                else
                {
                    title = "警告：退出 CodexBridge？";
                    body =
                        "这将关闭 CodexBridge、Bridge 和 CC Switch。\r\n\r\n" +
                        "重新打开 CC Switch 后，CodexBridge 会自动启动。";
                }
                return;
            }

            title = "Warning: Exit CodexBridge?";
            body =
                "This will close CodexBridge, the Bridge, and CC Switch.\r\n\r\n" +
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
                    ui.F("Uninstaller not found:\r\n{0}", script),
                    ui.T("CodexBridge"),
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
                    ui.F("Could not start the CodexBridge uninstaller.\r\n\r\n{0}", ex.Message),
                    ui.T("CodexBridge"),
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
                    Log("Cancelling in-flight Bridge manager startup for Exit CodexBridge.");
                    p.Kill();
                }
            }
            catch (Exception ex)
            {
                Log("WARNING cancelling in-flight Bridge manager startup: " + ex.Message);
            }
        }

        private void ClearDirectOfficialHandoffLatch()
        {
            try
            {
                string latch = Path.Combine(codexHome, "cpb-native-detach.flag");
                if (File.Exists(latch)) File.Delete(latch);
                Log("Direct Official handoff latch cleared.");
            }
            catch (Exception ex)
            {
                Log("WARNING could not clear direct Official handoff latch: " + ex.Message);
            }
        }

        private void AbortExitAfterHandoffFailure(Exception error)
        {
            ClearDirectOfficialHandoffLatch();
            exiting = false;
            handling = false;
            Log("Exit CodexBridge cancelled because Official handoff failed; Bridge was kept running: " + error.Message);
            RunOnUiThread(delegate
            {
                try { tray.Visible = true; } catch { }
                try { if (tray.ContextMenuStrip != null) tray.ContextMenuStrip.Enabled = true; } catch { }
                try { pollTimer.Start(); } catch { }
                Balloon(ui.T("Exit CodexBridge cancelled"), ui.T("Official handoff failed. Bridge remains running; no components were stopped."), ToolTipIcon.Error);
            });
        }

        private void PerformExitShutdown()
        {
            RouteSnapshot route = ReadRouteSnapshot();
            bool official = (route != null && string.Equals(route.Kind, "official", StringComparison.OrdinalIgnoreCase)) || IsCustomDirectOfficialRoute();
            if (official)
            {
                try
                {
                    Log("Official Exit CodexBridge: preparing direct Official handoff before stopping Bridge.");
                    PrepareDirectOfficialHandoff();
                    if (!IsCustomDirectOfficialRoute())
                        throw new Exception("Official handoff verification did not confirm custom.base_url=https://chatgpt.com/backend-api/codex.");
                    RestartCodexForExit();
                    Log("Official direct handoff verified and Codex restart completed; continuing shutdown.");
                }
                catch (Exception ex)
                {
                    AbortExitAfterHandoffFailure(ex);
                    return;
                }
            }

            try
            {
                StopBridgeForExit();
            }
            catch (Exception ex)
            {
                Log("WARNING stopping Bridge during Exit CodexBridge: " + ex.Message);
            }

            try
            {
                StopCcSwitchForExit();
            }
            catch (Exception ex)
            {
                Log("WARNING stopping CC Switch during Exit CodexBridge: " + ex.Message);
            }

            Log("Exit CodexBridge complete: full Launcher, resident Bridge, and CC Switch stopped; watcher remains armed for the next user-launched CC Switch.");
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
                Log("Exit CodexBridge cancelled by user.");
                return;
            }

            // Explicit shutdown keeps the watcher alive. Official routes perform the existing
            // direct handoff inside the shutdown worker before the Bridge is stopped; third-party
            // routes stop without a handoff.
            exiting = true;
            try { pollTimer.Stop(); } catch { }
            Log("Exit CodexBridge confirmed. Cancelling startup work, then performing bounded handoff/Bridge/CC Switch shutdown; watcher remains armed.");

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
                        DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + Sanitize(message) + Environment.NewLine,
                        new UTF8Encoding(false));
                }
            }
            catch { }
        }

        // Unified log redaction. Every persisted launcher.log line flows through
        // Log(), including captured Bridge-manager stdout/stderr and exception
        // details, so sanitizing at this single chokepoint covers them all. The
        // diagnostics we intentionally keep (timestamp, route, provider/model,
        // HTTP status, retry reason, ports, counts, fingerprints) never match
        // these credential / personal-path patterns.
        private static string Sanitize(string message)
        {
            if (string.IsNullOrEmpty(message)) return message;
            string text = message;
            text = Regex.Replace(text, @"(?i)\b(proxy-authorization|authorization)\s*:\s*[^\r\n]+", "$1: [REDACTED]");
            text = Regex.Replace(text, @"(?i)\b(set-cookie|cookie)\s*:\s*[^\r\n]+", "$1: [REDACTED]");
            text = Regex.Replace(text, @"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}", "$1 [REDACTED]");
            text = Regex.Replace(text, @"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|id[_-]?token|secret|password|passwd)""?(\s*[:=]\s*""?)[^\s"",;}\]]+", "$1$2[REDACTED]");
            text = Regex.Replace(text, @"\bsk-[A-Za-z0-9_-]{6,}", "[REDACTED_KEY]");
            text = Regex.Replace(text, @"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}", "[REDACTED_JWT]");
            text = Regex.Replace(text, @"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@", "$1[REDACTED]@");
            text = Regex.Replace(text, @"(?i)([?&](?:token|access_token|api_key|apikey|key|code|secret|signature|sig|password)=)[^&#\s]+", "$1[REDACTED]");
            text = Regex.Replace(text, @"/Users/[^/\s""']{1,64}/", "/Users/<user>/");
            text = Regex.Replace(text, @"([A-Za-z]:)\\Users\\[^\\\s""']{1,64}\\", "$1\\Users\\<user>\\");
            text = Regex.Replace(text, @"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]");
            return text;
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
            string[] keys = new string[] { "last_handled_route", "update_checked_at_utc", "latest_release_version", "latest_release_url" };
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
        private const string ProductVersion = "0.1.8";
        internal static string PublicVersion { get { return ProductVersion; } }

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

        internal static bool IsWatcherStartupRegistered()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(StartupRegistryPath, false))
                {
                    if (key == null) return false;
                    object raw = key.GetValue(StartupValueName);
                    string value = raw == null ? "" : raw.ToString() ?? "";
                    return value.IndexOf("--watch-ccswitch", StringComparison.OrdinalIgnoreCase) >= 0 &&
                        value.IndexOf("--autostart", StringComparison.OrdinalIgnoreCase) < 0;
                }
            }
            catch { return false; }
        }

        private static void MigrateLegacyStartupRegistration(string exePath)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(StartupRegistryPath, false))
                {
                    if (key == null) return;
                    object raw = key.GetValue(StartupValueName);
                    string value = raw == null ? "" : raw.ToString() ?? "";
                    if (value.IndexOf("--autostart", StringComparison.OrdinalIgnoreCase) < 0 &&
                        value.IndexOf("--watch-ccswitch", StringComparison.OrdinalIgnoreCase) >= 0) return;
                }
                RegisterWatcherAutostart(exePath);
                StaticLauncherLog("Migrated legacy full Launcher Windows startup registration to --watch-ccswitch.");
            }
            catch (Exception ex)
            {
                StaticLauncherLog("WARNING could not migrate legacy Windows startup registration: " + ex.Message);
            }
        }

        private static void RegisterWatcherAutostart(string exePath)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupRegistryPath))
            {
                if (key == null) throw new Exception("Could not open the current-user Startup registry key.");
                key.SetValue(StartupValueName, "\"" + exePath + "\" --watch-ccswitch", RegistryValueKind.String);
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
                RegisterWatcherAutostart(installedExe);
                EnsureCcSwitchWatcherRunning(installedExe);
                RegisterWindowsUninstallEntry(installedExe, installDir);

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = installedExe;
                psi.Arguments = "--installed";
                psi.UseShellExecute = true;
                psi.WorkingDirectory = installDir;
                Process.Start(psi);
                EmergencyLog("Installed/updated stable launcher at " + installDir + "; CC Switch watcher startup registered; relaunched installed copy.");
                return true;
            }
            catch (Exception ex)
            {
                EmergencyLog("Stable install/update failed: " + ex);
                try
                {
                    LauncherUiText text = new LauncherUiText();
                    MessageBox.Show(text.F("Could not install Codex Bridge into %LOCALAPPDATA%\\CodexProviderBridge\\app.\r\n\r\n{0}", ex.Message),
                        text.T("Codex Bridge Launcher"), MessageBoxButtons.OK, MessageBoxIcon.Error);
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
                    StaticLauncherLog("CC Switch trigger watcher started. It launches CodexBridge only on a CC Switch start edge.");
                    // Baseline the current state before edge detection. If CC Switch was
                    // already running when Windows logged in, that is not a new user launch.
                    bool previousCcSwitchRunning = IsCcSwitchRunning();
                    bool launchAttemptedForRun = false;
                    while (true)
                    {
                        if (stop.WaitOne(700)) break;
                        bool currentCcSwitchRunning = IsCcSwitchRunning();
                        if (!currentCcSwitchRunning)
                        {
                            launchAttemptedForRun = false;
                        }
                        else if (currentCcSwitchRunning && !previousCcSwitchRunning && !launchAttemptedForRun)
                        {
                            launchAttemptedForRun = true;
                            if (!IsFullLauncherRunning()) LaunchFullLauncherFromWatcher(exePath);
                            else StaticLauncherLog("CC Switch start edge observed while full Launcher is already running.");
                        }
                        previousCcSwitchRunning = currentCcSwitchRunning;
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
            MigrateLegacyStartupRegistration(Application.ExecutablePath);
            if (HasArg(args, "--autostart"))
            {
                MigrateLegacyStartupRegistration(Application.ExecutablePath);
                RunCcSwitchWatcher();
                return;
            }
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
                if (!HasArg(args, "--ccswitch-trigger"))
                {
                    LauncherUiText text = new LauncherUiText();
                    MessageBox.Show(text.T("Codex Bridge Launcher is already running in the system tray."), text.T("Codex Bridge Launcher"), MessageBoxButtons.OK, MessageBoxIcon.Information);
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
                    LauncherUiText text = new LauncherUiText();
                    MessageBox.Show(text.T("Codex Bridge Launcher crashed. See %LOCALAPPDATA%\\CodexProviderBridge\\launcher-crash.log"),
                        text.T("Codex Bridge Launcher"), MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                catch { }
            }
        }
    }
}
