using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace CodexBridgeSetupApp
{
    internal static class Program
    {
        private const string SetupVersion = "1.2.1-standard-uninstall";
        private const string PayloadResourceName = "CodexBridgePayload.zip";
        private const string StartupRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValueName = "CodexBridgeLauncher";
        private const string UninstallRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexBridge";
        private const string ProductVersion = "0.1.1";
        private const string WatcherStopEventName = @"Local\CodexProviderBridgeCcSwitchWatcherStop";
        private const string SetupMutexName = @"Local\CodexBridgeSetup";
        private static string rootOverride = null;

        private static string RootDir()
        {
            if (!string.IsNullOrEmpty(rootOverride)) return rootOverride;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexProviderBridge");
        }

        private static string PowerShellExePath()
        {
            string windir = Environment.GetEnvironmentVariable("WINDIR") ?? "";
            string candidate = Path.Combine(windir, @"System32\WindowsPowerShell\v1.0\powershell.exe");
            if (File.Exists(candidate)) return candidate;
            candidate = Path.Combine(windir, @"Sysnative\WindowsPowerShell\v1.0\powershell.exe");
            if (File.Exists(candidate)) return candidate;
            return "powershell.exe";
        }

        private static string ArgValue(string[] args, string name)
        {
            if (args == null) return null;
            for (int i = 0; i + 1 < args.Length; i++)
            {
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
            }
            return null;
        }

        private static bool HasArg(string[] args, string name)
        {
            if (args == null) return false;
            for (int i = 0; i < args.Length; i++)
            {
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return true;
            }
            return false;
        }

        private static void ValidateEnvironment()
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT)
                throw new PlatformNotSupportedException("CodexBridge Windows release requires Windows.");
            if (!Environment.Is64BitOperatingSystem)
                throw new PlatformNotSupportedException("CodexBridge currently supports 64-bit Windows only.");
            string ps = PowerShellExePath();
            if (!File.Exists(ps) && string.Equals(ps, "powershell.exe", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    ProcessStartInfo probe = new ProcessStartInfo();
                    probe.FileName = ps;
                    probe.Arguments = "-NoProfile -Command exit 0";
                    probe.UseShellExecute = false;
                    probe.CreateNoWindow = true;
                    using (Process p = Process.Start(probe))
                    {
                        if (p == null || !p.WaitForExit(5000) || p.ExitCode != 0)
                            throw new InvalidOperationException("Windows PowerShell is unavailable.");
                    }
                }
                catch { throw new InvalidOperationException("Windows PowerShell 5.1 or newer is required."); }
            }
        }

        private static string AppDir()
        {
            return Path.Combine(RootDir(), "app");
        }

        private static string LogPath()
        {
            return Path.Combine(RootDir(), "setup.log");
        }

        private static void Log(string message)
        {
            try
            {
                Directory.CreateDirectory(RootDir());
                File.AppendAllText(LogPath(), DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + message + Environment.NewLine, new UTF8Encoding(false));
            }
            catch { }
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

        private static void SignalWatcherStop()
        {
            try
            {
                using (EventWaitHandle stop = EventWaitHandle.OpenExisting(WatcherStopEventName))
                {
                    stop.Set();
                }
            }
            catch { }
        }

        private static void KillInstalledLaunchers(string appDir)
        {
            SignalWatcherStop();
            Thread.Sleep(250);
            try
            {
                foreach (Process p in Process.GetProcessesByName("CodexBridgeLauncher"))
                {
                    try
                    {
                        string path = p.MainModule == null ? "" : p.MainModule.FileName;
                        if (string.IsNullOrEmpty(path)) continue;
                        string dir = Path.GetDirectoryName(path) ?? "";
                        if (!PathsEqual(dir, appDir)) continue;
                        p.Kill();
                        try { p.WaitForExit(5000); } catch { }
                    }
                    catch { }
                }
            }
            catch { }
        }

        private static void StopResidentBridge(string appDir)
        {
            try
            {
                string manager = Path.Combine(appDir, "codex_bridge_manager.ps1");
                if (!File.Exists(manager)) return;
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = PowerShellExePath();
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + manager + "\" stop";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = appDir;
                using (Process p = Process.Start(psi))
                {
                    if (p != null) p.WaitForExit(20000);
                }
            }
            catch (Exception ex)
            {
                Log("WARNING stop resident bridge failed: " + ex.Message);
            }
        }

        private static void ExtractEmbeddedPayload(string stagingDir)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream input = asm.GetManifestResourceStream(PayloadResourceName))
            {
                if (input == null) throw new InvalidOperationException("Embedded runtime payload is missing.");
                string zipPath = Path.Combine(stagingDir, "payload.zip");
                using (FileStream output = File.Create(zipPath)) input.CopyTo(output);
                ZipFile.ExtractToDirectory(zipPath, stagingDir);
                File.Delete(zipPath);
            }
        }

        private static void CopyDirectory(string sourceDir, string destDir)
        {
            Directory.CreateDirectory(destDir);
            foreach (string file in Directory.GetFiles(sourceDir))
            {
                string name = Path.GetFileName(file);
                File.Copy(file, Path.Combine(destDir, name), true);
            }
            foreach (string dir in Directory.GetDirectories(sourceDir))
            {
                string name = Path.GetFileName(dir);
                CopyDirectory(dir, Path.Combine(destDir, name));
            }
        }

        private static void CapturePreinstallConfigIfNeeded()
        {
            try
            {
                string stateDir = Path.Combine(RootDir(), "uninstall");
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
                Log("WARNING could not capture pre-install Codex config for uninstall: " + ex.Message);
            }
        }

        private static void RegisterWindowsUninstallEntry(string installedLauncher, string appDir)
        {
            try
            {
                string uninstaller = Path.Combine(appDir, "UninstallCodexBridge.ps1");
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegistryPath))
                {
                    if (key == null) return;
                    string ps = PowerShellExePath();
                    string uninstallString = "\"" + ps + "\" -NoProfile -ExecutionPolicy Bypass -File \"" + uninstaller + "\"";
                    key.SetValue("DisplayName", "CodexBridge", RegistryValueKind.String);
                    key.SetValue("DisplayVersion", ProductVersion, RegistryValueKind.String);
                    key.SetValue("Publisher", "StrengW", RegistryValueKind.String);
                    key.SetValue("InstallLocation", appDir, RegistryValueKind.String);
                    key.SetValue("DisplayIcon", installedLauncher, RegistryValueKind.String);
                    key.SetValue("UninstallString", uninstallString, RegistryValueKind.String);
                    key.SetValue("QuietUninstallString", uninstallString + " -Silent", RegistryValueKind.String);
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }
            catch (Exception ex)
            {
                Log("WARNING could not register Windows uninstall entry: " + ex.Message);
            }
        }

        private static void RegisterWatcherAutostart(string launcherExe)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupRegistryPath))
            {
                if (key == null) throw new InvalidOperationException("Could not open the current-user Startup registry key.");
                key.SetValue(StartupValueName, "\"" + launcherExe + "\" --watch-ccswitch", RegistryValueKind.String);
            }
        }

        private static void StartInstalled(string launcherExe, string appDir)
        {
            ProcessStartInfo watcher = new ProcessStartInfo();
            watcher.FileName = launcherExe;
            watcher.Arguments = "--watch-ccswitch";
            watcher.UseShellExecute = true;
            watcher.WorkingDirectory = appDir;
            Process.Start(watcher);

            ProcessStartInfo launcher = new ProcessStartInfo();
            launcher.FileName = launcherExe;
            launcher.Arguments = "--installed";
            launcher.UseShellExecute = true;
            launcher.WorkingDirectory = appDir;
            Process.Start(launcher);
        }

        private static void WriteVersionMarker()
        {
            File.WriteAllText(Path.Combine(RootDir(), "installed-version.txt"), SetupVersion + Environment.NewLine, new UTF8Encoding(false));
        }

        private static void Install(bool registerAutostart, bool launchAfterInstall)
        {
            string root = RootDir();
            string appDir = AppDir();
            Directory.CreateDirectory(root);
            Log("Setup " + SetupVersion + " started from " + Application.ExecutablePath);
            CapturePreinstallConfigIfNeeded();

            KillInstalledLaunchers(appDir);
            StopResidentBridge(appDir);

            string stagingDir = Path.Combine(root, "setup-staging-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stagingDir);
            try
            {
                ExtractEmbeddedPayload(stagingDir);
                string launcherInPayload = Path.Combine(stagingDir, "CodexBridgeLauncher.exe");
                if (!File.Exists(launcherInPayload)) throw new FileNotFoundException("Payload does not contain CodexBridgeLauncher.exe.", launcherInPayload);
                if (!File.Exists(Path.Combine(stagingDir, "codex_provider_bridge.exe"))) throw new FileNotFoundException("Payload does not contain the standalone codex_provider_bridge.exe runtime.");
                if (!File.Exists(Path.Combine(stagingDir, "codex_bridge_manager.ps1"))) throw new FileNotFoundException("Payload does not contain codex_bridge_manager.ps1.");

                Directory.CreateDirectory(appDir);
                CopyDirectory(stagingDir, appDir);

                string installedLauncher = Path.Combine(appDir, "CodexBridgeLauncher.exe");
                if (registerAutostart) RegisterWatcherAutostart(installedLauncher);
                RegisterWindowsUninstallEntry(installedLauncher, appDir);
                WriteVersionMarker();
                if (launchAfterInstall) StartInstalled(installedLauncher, appDir);
                Log("Install/update complete. app=" + appDir + "; autostart=" + registerAutostart + "; launched=" + launchAfterInstall + ".");
            }
            finally
            {
                try { Directory.Delete(stagingDir, true); } catch { }
            }
        }

        [STAThread]
        private static void Main(string[] args)
        {
            bool silent = HasArg(args, "--silent");
            bool noLaunch = HasArg(args, "--no-launch");
            bool noAutostart = HasArg(args, "--no-autostart");
            string requestedRoot = ArgValue(args, "--root");
            if (!string.IsNullOrWhiteSpace(requestedRoot)) rootOverride = Path.GetFullPath(requestedRoot.Trim().Trim('"'));

            bool created;
            using (Mutex mutex = new Mutex(true, SetupMutexName, out created))
            {
                if (!created)
                {
                    if (!silent) MessageBox.Show("Codex Bridge setup is already running.", "Codex Bridge Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    Environment.ExitCode = 2;
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                try
                {
                    ValidateEnvironment();
                    Install(!noAutostart, !noLaunch);
                    if (!silent)
                    {
                        MessageBox.Show(
                            "Codex Bridge is installed and running.\r\n\r\nFrom now on, use CC Switch normally. If a third-party route is active and the CC Switch proxy is closed, Codex Bridge will restore it automatically. The lightweight watcher also brings the launcher back when CC Switch opens.",
                            "Codex Bridge Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    }
                    Environment.ExitCode = 0;
                }
                catch (Exception ex)
                {
                    Log("ERROR setup failed: " + ex);
                    Environment.ExitCode = 1;
                    if (!silent)
                    {
                        MessageBox.Show(
                            "Codex Bridge setup failed.\r\n\r\n" + ex.Message + "\r\n\r\nLog: " + LogPath(),
                            "Codex Bridge Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    }
                }
            }
        }
    }
}
