using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace CodexBridgeLauncherApp
{
    internal enum ReleaseUpdateStatus
    {
        Failed,
        UpToDate,
        UpdateAvailable
    }

    internal sealed class ReleaseUpdateResult
    {
        internal ReleaseUpdateStatus Status;
        internal string LatestVersion = "";
        internal string ReleaseUrl = "";
        internal string Error = "";
    }

    internal static class ReleaseUpdateChecker
    {
        internal const string ApiUrl = "https://api.github.com/repos/StrengW/cc-switch-codex-cross-provider-bridge/releases/latest";
        internal const string ReleaseUrl = "https://github.com/StrengW/cc-switch-codex-cross-provider-bridge/releases";

        internal static void CheckAsync(string currentVersion, Action<ReleaseUpdateResult> completed)
        {
            ThreadPool.QueueUserWorkItem(delegate
            {
                ReleaseUpdateResult result = Check(currentVersion);
                try { if (completed != null) completed(result); } catch { }
            });
        }

        internal static ReleaseUpdateResult Check(string currentVersion)
        {
            string apiError = "";
            try
            {
                EnsureModernTls();
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(ApiUrl);
                request.Method = "GET";
                request.Accept = "application/vnd.github+json";
                request.UserAgent = "CodexBridge-Launcher/" + currentVersion;
                request.Timeout = 5000;
                request.ReadWriteTimeout = 5000;
                using (WebResponse response = request.GetResponse())
                using (Stream stream = response.GetResponseStream())
                using (StreamReader reader = new StreamReader(stream ?? Stream.Null, Encoding.UTF8))
                {
                    string json = reader.ReadToEnd();
                    string tag = JsonString(json, "tag_name");
                    string latest = NormalizeVersion(tag);
                    if (latest.Length == 0) return Failed("GitHub latest release did not contain a SemVer tag.");
                    string url = JsonString(json, "html_url");
                    if (url.Length == 0) url = ReleaseUrl;
                    return Build(latest, url, currentVersion);
                }
            }
            catch (Exception ex)
            {
                apiError = DescribeError(ex);
            }

            // Some networks block or rate-limit the GitHub REST API even though the regular
            // github.com site is reachable, so retry through the public releases/latest
            // redirect, which does not consume the unauthenticated API quota.
            try
            {
                string latest = NormalizeVersion(LatestTagFromRedirect(currentVersion));
                if (latest.Length > 0) return Build(latest, ReleaseUrl, currentVersion);
            }
            catch { }

            return Failed(apiError);
        }

        private static ReleaseUpdateResult Build(string latest, string url, string currentVersion)
        {
            return new ReleaseUpdateResult
            {
                Status = CompareVersions(latest, currentVersion) > 0
                    ? ReleaseUpdateStatus.UpdateAvailable
                    : ReleaseUpdateStatus.UpToDate,
                LatestVersion = latest,
                ReleaseUrl = url
            };
        }

        private static string LatestTagFromRedirect(string currentVersion)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(ReleaseUrl + "/latest");
            request.Method = "HEAD";
            request.AllowAutoRedirect = false;
            request.UserAgent = "CodexBridge-Launcher/" + currentVersion;
            request.Timeout = 5000;
            request.ReadWriteTimeout = 5000;
            try
            {
                using (WebResponse response = request.GetResponse())
                {
                    return TagFromLocation(response.Headers["Location"]);
                }
            }
            catch (WebException ex)
            {
                if (ex.Response == null) return "";
                return TagFromLocation(ex.Response.Headers["Location"]);
            }
        }

        private static string TagFromLocation(string location)
        {
            if (String.IsNullOrEmpty(location)) return "";
            int index = location.LastIndexOf("/tag/", StringComparison.OrdinalIgnoreCase);
            if (index < 0) return "";
            return location.Substring(index + 5);
        }

        private static string DescribeError(Exception ex)
        {
            WebException web = ex as WebException;
            if (web == null) return ex.Message;
            if (web.Status == WebExceptionStatus.SecureChannelFailure)
                return "TLS handshake failed (SecureChannelFailure); a proxy or firewall may be intercepting HTTPS.";
            return web.Status + ": " + web.Message;
        }

        internal static int CompareVersions(string left, string right)
        {
            int[] a = VersionParts(left);
            int[] b = VersionParts(right);
            for (int i = 0; i < 3; i++)
            {
                if (a[i] != b[i]) return a[i].CompareTo(b[i]);
            }
            return 0;
        }

        private static void EnsureModernTls()
        {
            try
            {
                // This launcher is compiled without an app.config, so the runtime treats it as a
                // .NET 4.0 application and ServicePointManager.SecurityProtocol defaults to
                // Ssl3|Tls only. GitHub requires TLS 1.2, and without this the update check fails
                // with "could not create SSL/TLS secure channel" (WebException SecureChannelFailure).
                ServicePointManager.SecurityProtocol = ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12;
            }
            catch { }
        }

        private static int[] VersionParts(string value)
        {
            Match match = Regex.Match(value ?? "", "^(?:v)?(\\d+)\\.(\\d+)\\.(\\d+)", RegexOptions.CultureInvariant);
            if (!match.Success) return new int[] { 0, 0, 0 };
            return new int[]
            {
                ParsePart(match.Groups[1].Value),
                ParsePart(match.Groups[2].Value),
                ParsePart(match.Groups[3].Value)
            };
        }

        private static int ParsePart(string value)
        {
            int parsed;
            return int.TryParse(value, out parsed) ? parsed : 0;
        }

        private static string NormalizeVersion(string tag)
        {
            Match match = Regex.Match(tag ?? "", "^(?:v)?(\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.-]+)?)$", RegexOptions.CultureInvariant);
            return match.Success ? match.Groups[1].Value : "";
        }

        private static string JsonString(string json, string key)
        {
            Match match = Regex.Match(json ?? "", "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"\\\\])*)\\\"", RegexOptions.CultureInvariant);
            return match.Success ? JsonUnescape(match.Groups[1].Value) : "";
        }

        private static string JsonUnescape(string value)
        {
            return (value ?? "").Replace("\\/", "/").Replace("\\\"", "\"").Replace("\\\\", "\\");
        }

        private static ReleaseUpdateResult Failed(string message)
        {
            return new ReleaseUpdateResult { Status = ReleaseUpdateStatus.Failed, Error = message ?? "" };
        }
    }
}
