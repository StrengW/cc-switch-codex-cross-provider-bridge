[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('auto', 'start', 'repair', 'status', 'doctor', 'stop', 'prepare-direct-official', 'prepare-detach', 'detach')]
    [string]$Command = 'auto',

    [string]$BridgeScript,
    [string]$CodexConfig,
    [string]$CodexExecutable,
    [string]$ListenAddress = '127.0.0.1',

    [ValidateRange(1, 65535)]
    [int]$BridgePort = 15722,

    [string]$UpstreamUrl = 'http://127.0.0.1:15721',
    [string]$ResponsesWebSocketUpstreamUrl = 'https://chatgpt.com/backend-api/codex',
    [string]$ProviderId = 'custom',
    [string]$ProviderName = 'OpenAI',
    [string]$OfficialProviderId = 'cc-switch-official',
    # When supplied for the official route, this is written to config.toml and
    # passed to the bridge so old third-party sessions are replayed with the
    # selected official model instead of their stale session model.
    [string]$Model,

    # Foreground is retained as a compatibility alias. Foreground mode is now
    # the default; use -Background only when a detached process is desired.
    [switch]$Foreground,
    [switch]$Background,
    [switch]$FixedPort,

    # v2.4 default: install a hash-neutral bundled model catalog exported by
    # the local Codex binary (or neutralize an existing user model_catalog_json),
    # removing only comp_hash before Codex starts. /models and models_cache.json
    # remain defense-in-depth fallbacks.
    # Use this switch for conservative pass-through behavior.
    [switch]$PreserveCompHash,

    # v2.5 default: add deterministic explicit GPT-5.6 prompt-cache breakpoints
    # to full replays while leaving the backend's native implicit-cache behavior unchanged.
    # Disable this if a backend does not yet accept the GPT-5.6 cache-control schema.
    [switch]$DisablePromptCacheOptimization,
    # v2.6 defaults to native implicit caching; opt in only when testing a backend
    # that explicitly accepts the legacy GPT-5.6 cache-control markers.
    [switch]$EnablePromptCacheOptimization,

    # v2.6 does not prune replay history by default. This opt-in retains the older
    # conservative dedupe/tool-pair compactor for diagnostics.
    [switch]$DisableSwitchReplayCompaction,
    [switch]$EnableSwitchReplayCompaction,

    # Disable durable per-provider response checkpoints/catch-up deltas. When set,
    # provider switches fall back to portable full replay + native prompt caching.
    [switch]$DisableProviderContinuation,

    [ValidateRange(0, 134217728)]
    [int]$SwitchReplayThresholdBytes = 65536,

    [ValidateRange(1, 50)]
    [int]$SwitchReplayRecentUserTurns = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$BridgeManagerVersion = '2.15.2-resident-lifecycle-fix'
if ($Foreground -and $Background) {
    throw 'Foreground and Background cannot be used together.'
}
if ($EnablePromptCacheOptimization -and $DisablePromptCacheOptimization) {
    throw 'EnablePromptCacheOptimization and DisablePromptCacheOptimization cannot be used together.'
}
if ($EnableSwitchReplayCompaction -and $DisableSwitchReplayCompaction) {
    throw 'EnableSwitchReplayCompaction and DisableSwitchReplayCompaction cannot be used together.'
}
$RunForeground = -not $Background

# Realtime voice must not inherit the local Responses bridge URL. ChatGPT-auth
# call creation uses the ChatGPT backend, while the sideband WebSocket uses the
# native OpenAI realtime endpoint. Ordinary /responses traffic still passes
# through the local bridge and CC Switch.
$RealtimeWsBaseUrl = 'https://api.openai.com/v1'
$RealtimeWebRtcCallBaseUrl = 'https://chatgpt.com/backend-api/codex'
# When the local Bridge is intentionally stopped, keep model_provider=custom but
# hand the same provider directly to the ChatGPT Codex backend. This preserves
# the stable provider identity used by the cross-provider workflow while avoiding
# a dead 127.0.0.1:15722 endpoint. OpenAI Codex itself uses this backend URL.
$DirectOfficialBaseUrl = 'https://chatgpt.com/backend-api/codex'

# Windows PowerShell 5.1 can expose an empty $PSScriptRoot while evaluating
# default expressions inside param(...). Resolve path defaults only after
# parameter binding has completed.
$ManagerScriptDirectory = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
    $PSScriptRoot
} elseif (-not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

if ([string]::IsNullOrWhiteSpace($BridgeScript)) {
    # Packaged builds may include a standalone bridge executable; source quick-start
    # users do not need Python installed. Source/developer builds fall back to
    # the Python script when the executable is not present.
    $standaloneBridge = Join-Path $ManagerScriptDirectory 'codex_provider_bridge.exe'
    if (Test-Path -LiteralPath $standaloneBridge -PathType Leaf) {
        $BridgeScript = $standaloneBridge
    } else {
        $BridgeScript = Join-Path $ManagerScriptDirectory 'codex_provider_bridge.py'
    }
}

if ([string]::IsNullOrWhiteSpace($CodexConfig)) {
    $UserProfileDirectory = [Environment]::GetFolderPath('UserProfile')
    if ([string]::IsNullOrWhiteSpace($UserProfileDirectory)) {
        $UserProfileDirectory = $env:USERPROFILE
    }
    if ([string]::IsNullOrWhiteSpace($UserProfileDirectory)) {
        throw 'Cannot locate the Windows user profile. Pass -CodexConfig explicitly.'
    }
    $CodexConfig = Join-Path (Join-Path $UserProfileDirectory '.codex') 'config.toml'
}

# Normalize paths before passing them to System.IO. This matters when the
# script is launched from a different working directory or when a caller
# supplies a relative -CodexConfig/-BridgeScript path. System.IO.File.Replace
# requires filesystem paths, not provider-relative or empty path fragments.
try {
    $CodexConfig = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($CodexConfig))
    $BridgeScript = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($BridgeScript))
} catch {
    throw "Invalid CodexConfig or BridgeScript path. Pass normal filesystem paths explicitly. Details: $($_.Exception.Message)"
}

$BridgeOwnedModelCatalogPath = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $CodexConfig) 'cpb-bundled-model-catalog.json'))
$ActiveNeutralModelCatalogPath = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $CodexConfig) 'cpb-active-model-catalog.json'))
$ScopedNeutralModelCatalogPath = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $CodexConfig) 'cpb-provider-model-catalog.json'))
$ActiveNeutralCatalogSidecarPath = $ActiveNeutralModelCatalogPath + '.source.json'
$NativeDetachFlagPath = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $CodexConfig) 'cpb-native-detach.flag'))
$CatalogGuardGeneration = 'provider-scoped-catalog-v1'
$script:ActiveCompHashNeutralCatalogPath = $null

if ($ListenAddress -notin @('127.0.0.1', 'localhost')) {
    throw 'For safety, ListenAddress must be 127.0.0.1 or localhost.'
}
if ($ProviderId -notmatch '^[A-Za-z0-9_-]+$') {
    throw 'ProviderId may contain only letters, digits, underscores, and hyphens.'
}

try {
    $UpstreamUri = [Uri]$UpstreamUrl
} catch {
    throw "Invalid UpstreamUrl: $UpstreamUrl"
}
if ($UpstreamUri.Scheme -ne 'http' -or -not $UpstreamUri.IsLoopback) {
    throw 'For safety, UpstreamUrl must be a local http:// URL.'
}

try {
    $ResponsesWebSocketUpstreamUri = [Uri]$ResponsesWebSocketUpstreamUrl
} catch {
    throw "Invalid ResponsesWebSocketUpstreamUrl: $ResponsesWebSocketUpstreamUrl"
}
if ($ResponsesWebSocketUpstreamUri.Scheme -ne 'https' -or
    $ResponsesWebSocketUpstreamUri.Host -ne 'chatgpt.com') {
    throw 'For safety, ResponsesWebSocketUpstreamUrl must use https://chatgpt.com/... because Codex authentication headers are forwarded to this endpoint.'
}

$StateDirectory = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA 'CodexProviderBridge'
} else {
    Join-Path $env:TEMP 'CodexProviderBridge'
}
$StateFile = Join-Path $StateDirectory 'bridge-state.json'
$StdoutLog = Join-Path $StateDirectory 'bridge-stdout.log'
$StderrLog = Join-Path $StateDirectory 'bridge-stderr.log'
$RuntimeWorkingDirectory = Join-Path $StateDirectory 'runtime-cwd'

function Test-TcpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMs = 600
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-PortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $Port
        )
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Find-AvailablePort {
    param(
        [Parameter(Mandatory = $true)][int]$StartPort,
        [int]$Attempts = 200
    )

    for ($candidate = $StartPort; $candidate -lt ($StartPort + $Attempts); $candidate++) {
        if ($candidate -gt 65535) {
            break
        }
        if (Test-PortAvailable -Port $candidate) {
            return $candidate
        }
    }
    throw "No free local TCP port found from $StartPort to $($StartPort + $Attempts - 1)."
}

function Read-BridgeState {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Warning "Ignoring unreadable state file: $StateFile"
        return $null
    }
}

function Get-ManagedBridgeProcess {
    param($State)

    if ($null -eq $State -or $null -eq $State.pid) {
        return $null
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($State.pid)" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    $expectedPath = [string]$State.bridge_script
    if ([string]::IsNullOrWhiteSpace($process.CommandLine) -or
        $process.CommandLine.IndexOf($expectedPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return $null
    }
    return $process
}

function Resolve-PythonCommand {
    # Launch the real interpreter, not py.exe. The source quick-start keeps a
    # private runtime under LocalAppData so users do not need to install Python.
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:CPB_PYTHON) -and (Test-Path -LiteralPath $env:CPB_PYTHON -PathType Leaf)) {
        $candidates += [IO.Path]::GetFullPath($env:CPB_PYTHON)
    }
    $privatePython = Join-Path $env:LOCALAPPDATA 'CodexProviderBridge\runtime\python\python.exe'
    if ((Test-Path -LiteralPath $privatePython -PathType Leaf) -and $candidates -notcontains $privatePython) {
        $candidates += $privatePython
    }
    foreach ($name in @('python.exe', 'python')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command -and $candidates -notcontains $command.Source) {
            $candidates += $command.Source
        }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        try {
            $launchedPath = (& $py.Source -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
            if (-not [string]::IsNullOrWhiteSpace($launchedPath)) {
                $launchedPath = [IO.Path]::GetFullPath($launchedPath.Trim())
                if ($candidates -notcontains $launchedPath) {
                    # Prefer the interpreter selected by the Python launcher
                    # over Windows Store aliases named python.exe.
                    $candidates = @($launchedPath) + @($candidates)
                }
            }
        } catch { }
    }
    foreach ($candidate in $candidates) {
        try {
            & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $versionText = (& $candidate -c 'import platform; print(platform.python_version())' 2>$null | Select-Object -First 1)
                return [pscustomobject]@{
                    FilePath = $candidate
                    PrefixArguments = @()
                    Version = $versionText
                }
            }
        } catch { }
    }
    if ($candidates.Count -gt 0) {
        throw 'Python was found, but Python 3.10 or newer is required.'
    }
    throw 'Python was not found. Re-run Start CodexBridge.cmd once to repair the private runtime.'
}

function Escape-TomlString {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Get-TopLevelTomlString {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*"((?:\\.|[^"\\])*)"\s*(?:#.*)?$'
    foreach ($line in [regex]::Split($Text, '\r?\n')) {
        if ($line -match '^\s*\[') {
            break
        }
        if ($line -match $pattern) {
            return $Matches[1].Replace('\"', '"').Replace('\\', '\')
        }
    }
    return $null
}

function Get-ProviderTomlString {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $escapedId = [regex]::Escape($Id)
    $sectionPattern = '^\s*\[model_providers\.(?:' + $escapedId + '|"' + $escapedId + '")\]\s*$'
    $valuePattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*(?:"((?:\\.|[^"\\])*)"|(true|false))\s*(?:#.*)?$'
    $insideSection = $false
    foreach ($line in [regex]::Split($Text, '\r?\n')) {
        if ($line -match '^\s*\[') {
            $insideSection = ($line -match $sectionPattern)
            continue
        }
        if ($insideSection -and $line -match $valuePattern) {
            if ($null -ne $Matches[1]) {
                return $Matches[1].Replace('\"', '"').Replace('\\', '\')
            }
            return $Matches[2]
        }
    }
    return $null
}

function Get-ProviderBaseUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Id
    )
    return Get-ProviderTomlString -Text $Text -Id $Id -Key 'base_url'
}

function Get-AutomaticModelOverride {
    # In auto mode, reuse an already-configured official-looking model so the
    # common workflow does not require repeating -Model on every invocation.
    # Third-party names are intentionally excluded; use -Model explicitly for
    # a non-standard official model name.
    if ($Command -ne 'auto' -or -not (Test-Path -LiteralPath $CodexConfig -PathType Leaf)) {
        return $null
    }
    $text = [IO.File]::ReadAllText($CodexConfig)
    $configuredModel = Get-TopLevelTomlString -Text $text -Key 'model'
    if (-not [string]::IsNullOrWhiteSpace($configuredModel) -and
        $configuredModel -match '(?i)^(gpt-|o[0-9]|codex)') {
        return $configuredModel
    }
    return $null
}

function Test-CodexConfigNeedsBridge {
    if (-not (Test-Path -LiteralPath $CodexConfig -PathType Leaf)) {
        return $false
    }

    $text = [IO.File]::ReadAllText($CodexConfig)
    $activeProvider = Get-TopLevelTomlString -Text $text -Key 'model_provider'
    if ($activeProvider -eq $OfficialProviderId) {
        return $true
    }
    if ([string]::IsNullOrWhiteSpace($activeProvider)) {
        $configuredModel = Get-TopLevelTomlString -Text $text -Key 'model'
        return (-not [string]::IsNullOrWhiteSpace($configuredModel) -and
            $configuredModel -match '(?i)^(gpt-|o[0-9]|codex)')
    }
    if ($activeProvider -ne $ProviderId) {
        return $false
    }

    $baseUrl = Get-ProviderBaseUrl -Text $text -Id $ProviderId
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
        return $false
    }
    try {
        $uri = [Uri]$baseUrl
    } catch {
        return $false
    }
    if ($uri.Scheme -ne 'http' -or -not $uri.IsLoopback) {
        return $false
    }

    $state = Read-BridgeState
    $knownPorts = @($BridgePort)
    if ($null -ne $state -and $null -ne $state.port) {
        $knownPorts += [int]$state.port
    }
    if ($uri.AbsolutePath.TrimEnd('/') -ne '/v1') {
        return $false
    }
    if ($uri.Port -in $knownPorts) {
        return $true
    }

    # The manager may move the bridge to one of the next 199 ports when the
    # preferred port is occupied. Recognize that managed range without relying
    # on the provider display name: v2.3.0 deliberately uses name = "OpenAI"
    # so Codex keeps native OpenAI feature gates such as remote compaction.
    $managedRangeMax = [Math]::Min(65535, $BridgePort + 199)
    $portLooksManaged = ($uri.Port -ge $BridgePort -and $uri.Port -le $managedRangeMax)
    return ($portLooksManaged -and $uri.Port -ne $UpstreamUri.Port)
}

function Get-FirstSectionIndex {
    param([Parameter(Mandatory = $true)]$Lines)
    for ($index = 0; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match '^\s*\[') {
            return $index
        }
    }
    return $Lines.Count
}

function Set-TopLevelTomlKey {
    param(
        [Parameter(Mandatory = $true)]$Lines,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $sectionStart = Get-FirstSectionIndex -Lines $Lines
    $keyPattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    for ($index = 0; $index -lt $sectionStart; $index++) {
        if ($Lines[$index] -match $keyPattern) {
            $Lines[$index] = "$Key = $Value"
            return
        }
    }
    $Lines.Insert($sectionStart, "$Key = $Value") | Out-Null
}

function Remove-TopLevelTomlKey {
    param(
        [Parameter(Mandatory = $true)]$Lines,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $sectionStart = Get-FirstSectionIndex -Lines $Lines
    $keyPattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    for ($index = $sectionStart - 1; $index -ge 0; $index--) {
        if ($Lines[$index] -match $keyPattern) {
            $Lines.RemoveAt($index)
        }
    }
}

function Find-TomlSection {
    param(
        [Parameter(Mandatory = $true)]$Lines,
        [Parameter(Mandatory = $true)][string]$HeaderPattern
    )

    $start = -1
    for ($index = 0; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match $HeaderPattern) {
            $start = $index
            break
        }
    }
    if ($start -lt 0) {
        return $null
    }

    $end = $Lines.Count
    for ($index = $start + 1; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match '^\s*\[') {
            $end = $index
            break
        }
    }
    return [pscustomobject]@{ Start = $start; End = $end }
}

function Set-SectionTomlKey {
    param(
        [Parameter(Mandatory = $true)]$Lines,
        [Parameter(Mandatory = $true)][string]$HeaderPattern,
        [Parameter(Mandatory = $true)][string]$NewHeader,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $section = Find-TomlSection -Lines $Lines -HeaderPattern $HeaderPattern
    if ($null -eq $section) {
        if ($Lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($Lines[$Lines.Count - 1])) {
            $Lines.Add('') | Out-Null
        }
        $Lines.Add($NewHeader) | Out-Null
        $Lines.Add("$Key = $Value") | Out-Null
        return
    }

    $keyPattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    for ($index = $section.Start + 1; $index -lt $section.End; $index++) {
        if ($Lines[$index] -match $keyPattern) {
            $Lines[$index] = "$Key = $Value"
            return
        }
    }
    $Lines.Insert($section.End, "$Key = $Value") | Out-Null
}

function Remove-SectionTomlKey {
    param(
        [Parameter(Mandatory = $true)]$Lines,
        [Parameter(Mandatory = $true)][string]$HeaderPattern,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $section = Find-TomlSection -Lines $Lines -HeaderPattern $HeaderPattern
    if ($null -eq $section) { return }
    $keyPattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    for ($index = $section.End - 1; $index -gt $section.Start; $index--) {
        if ($Lines[$index] -match $keyPattern) {
            $Lines.RemoveAt($index)
        }
    }
}

function Update-CodexConfig {
    param([Parameter(Mandatory = $true)][int]$Port)

    $configDirectory = Split-Path -Parent $CodexConfig
    if (-not (Test-Path -LiteralPath $configDirectory)) {
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    }

    $exists = Test-Path -LiteralPath $CodexConfig
    $original = if ($exists) {
        [IO.File]::ReadAllText($CodexConfig)
    } else {
        ''
    }
    $newline = if ($original.Contains("`r`n")) { "`r`n" } else { "`n" }
    $splitLines = if ($original.Length -eq 0) { @() } else { [regex]::Split($original, '\r?\n') }
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $splitLines) {
        $lines.Add([string]$line) | Out-Null
    }

    Set-TopLevelTomlKey -Lines $lines -Key 'model_provider' -Value (Escape-TomlString $ProviderId)
    # v2.3 restores Codex's native Responses transport policy. Older bridge
    # versions forced disable_response_storage=true for stateless HTTP replay;
    # remove that bridge-owned override so the client can use its normal
    # WebSocket continuation semantics.
    Remove-TopLevelTomlKey -Lines $lines -Key 'disable_response_storage'
    # Keep realtime voice outside the local Responses route. ChatGPT-auth call
    # creation uses the ChatGPT backend; the realtime sideband WebSocket uses
    # api.openai.com. Normal model HTTP requests still use the custom bridge.
    Set-TopLevelTomlKey -Lines $lines -Key 'experimental_realtime_ws_base_url' -Value (Escape-TomlString $RealtimeWsBaseUrl)
    Set-TopLevelTomlKey -Lines $lines -Key 'experimental_realtime_webrtc_call_base_url' -Value (Escape-TomlString $RealtimeWebRtcCallBaseUrl)
    if (-not [string]::IsNullOrWhiteSpace($Model)) {
        Set-TopLevelTomlKey -Lines $lines -Key 'model' -Value (Escape-TomlString $Model)
    }
    if ($PreserveCompHash) {
        $configuredCatalog = Get-ConfiguredModelCatalogPath
        if (-not [string]::IsNullOrWhiteSpace($configuredCatalog)) {
            $configuredFull = [IO.Path]::GetFullPath($configuredCatalog)
            if ($configuredFull -eq $ActiveNeutralModelCatalogPath) {
                $sourceCatalog = Get-ActiveNeutralCatalogSourcePath
                if (-not [string]::IsNullOrWhiteSpace($sourceCatalog) -and
                    (Test-Path -LiteralPath $sourceCatalog -PathType Leaf)) {
                    Set-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json' -Value (Escape-TomlString $sourceCatalog)
                } else {
                    Remove-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json'
                }
            } elseif ($configuredFull -eq $BridgeOwnedModelCatalogPath) {
                Remove-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json'
            }
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($script:ActiveCompHashNeutralCatalogPath)) {
        Set-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json' -Value (Escape-TomlString $script:ActiveCompHashNeutralCatalogPath)
    }

    $escapedProvider = [regex]::Escape($ProviderId)
    $providerPattern = '^\s*\[model_providers\.(?:' + $escapedProvider + '|"' + $escapedProvider + '")\]\s*$'
    $providerHeader = "[model_providers.$ProviderId]"
    $bridgeBaseUrl = "http://$ListenAddress`:$Port/v1"

    Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'name' -Value (Escape-TomlString $ProviderName)
    Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'base_url' -Value (Escape-TomlString $bridgeBaseUrl)
    Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'wire_api' -Value '"responses"'
    Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'requires_openai_auth' -Value 'true'
    # Old direct-handoff / proxy-managed configurations can leave a placeholder
    # bearer token behind. It is invalid against the native ChatGPT backend and
    # must not survive when the custom provider is rebound to the local Bridge.
    Remove-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -Key 'experimental_bearer_token'
    # Prefer Responses-over-WebSocket. v2.3 preserves Codex's native token policy:
    # a turn may start with full canonical history (eligible for prompt-cache reuse),
    # while same-turn follow-ups may use trusted previous_response_id + input delta.
    # The bridge does not invent cross-turn response chains. HTTP remains fallback.
    $websocketValue = if ($Model -match '^(?i:gpt-|o[0-9]|codex)') { 'true' } else { 'false' }
    Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'supports_websockets' -Value $websocketValue

    $featuresPattern = '^\s*\[features\]\s*$'
    Set-SectionTomlKey -Lines $lines -HeaderPattern $featuresPattern -NewHeader '[features]' -Key 'enable_request_compression' -Value 'false'

    $updated = [string]::Join($newline, $lines.ToArray())
    if ($updated -ceq $original) {
        Write-Host "Codex config is already correct: $CodexConfig"
        return $null
    }

    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $backup = $null
    if ($exists) {
        $backup = [IO.Path]::GetFullPath("$CodexConfig.bridge-backup-$timestamp")
    }

    $temporary = [IO.Path]::GetFullPath(
        (Join-Path $configDirectory ("config.toml.bridge-tmp-" + [Guid]::NewGuid().ToString('N')))
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($temporary, $updated, $utf8NoBom)
        if ($exists) {
            try {
                # Give File.Replace a real, fully resolved backup path. Passing
                # $null here is accepted by some .NET versions but has caused
                # the Windows PowerShell 5.1 "path is not of a legal form"
                # error in this workflow.
                [IO.File]::Replace($temporary, $CodexConfig, $backup, $true)
            } catch {
                # Keep the already-written temporary file and fall back to a
                # safe copy only when the atomic replace itself is unavailable.
                # The original config is copied to the timestamped backup
                # before it is overwritten.
                $replaceError = $_.Exception
                if (-not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
                    throw $replaceError
                }
                Copy-Item -LiteralPath $CodexConfig -Destination $backup -Force
                [IO.File]::Copy($temporary, $CodexConfig, $true)
                Remove-Item -LiteralPath $temporary -Force
                Write-Warning "Atomic config replacement was unavailable; used a backup-protected copy instead. Details: $($replaceError.Message)"
            }
        } else {
            [IO.File]::Move($temporary, $CodexConfig)
        }
    } catch {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
        throw
    }

    Write-Host "Updated Codex config: $CodexConfig"
    if ($null -ne $backup) {
        Write-Host "Backup created: $backup"
    }
    return $backup
}


function Get-ConfiguredModelCatalogPath {
    if (-not (Test-Path -LiteralPath $CodexConfig -PathType Leaf)) {
        return $null
    }
    $configDirectory = Split-Path -Parent $CodexConfig
    foreach ($line in [IO.File]::ReadAllLines($CodexConfig, [Text.Encoding]::UTF8)) {
        if ($line -match '^\s*\[') {
            break
        }
        if ($line -match '^\s*model_catalog_json\s*=\s*"([^"]+)"') {
            $value = $Matches[1] -replace '\\\\', '\\'
            $value = $value -replace '\\"', '"'
            if ([IO.Path]::IsPathRooted($value)) {
                return [IO.Path]::GetFullPath($value)
            }
            return [IO.Path]::GetFullPath((Join-Path $configDirectory $value))
        }
        if ($line -match "^\s*model_catalog_json\s*=\s*'([^']+)'") {
            $value = $Matches[1]
            if ([IO.Path]::IsPathRooted($value)) {
                return [IO.Path]::GetFullPath($value)
            }
            return [IO.Path]::GetFullPath((Join-Path $configDirectory $value))
        }
    }
    return $null
}

function Get-ActiveNeutralCatalogSourcePath {
    if (-not (Test-Path -LiteralPath $ActiveNeutralCatalogSidecarPath -PathType Leaf)) {
        return $null
    }
    try {
        $sidecar = [IO.File]::ReadAllText($ActiveNeutralCatalogSidecarPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($null -ne $sidecar -and $null -ne $sidecar.PSObject.Properties['source_path']) {
            $candidate = [string]$sidecar.source_path
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                return [IO.Path]::GetFullPath($candidate)
            }
        }
    } catch { }
    return $null
}

function Remove-CompHashPropertiesRecursive {
    param([object]$Node)
    if ($null -eq $Node) { return 0 }

    $removed = 0
    if ($Node -is [System.Collections.IDictionary]) {
        if ($Node.Contains('comp_hash')) {
            $Node.Remove('comp_hash')
            $removed++
        }
        foreach ($key in @($Node.Keys)) {
            $removed += Remove-CompHashPropertiesRecursive -Node $Node[$key]
        }
        return $removed
    }

    if ($Node -is [System.Collections.IEnumerable] -and -not ($Node -is [string])) {
        foreach ($item in @($Node)) {
            $removed += Remove-CompHashPropertiesRecursive -Node $item
        }
        return $removed
    }

    if ($Node -is [PSCustomObject]) {
        $property = $Node.PSObject.Properties['comp_hash']
        if ($null -ne $property) {
            $Node.PSObject.Properties.Remove('comp_hash')
            $removed++
        }
        foreach ($prop in @($Node.PSObject.Properties)) {
            $removed += Remove-CompHashPropertiesRecursive -Node $prop.Value
        }
    }
    return $removed
}

function Get-CodexExecutableVersion {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $line = (& $Path --version 2>$null | Select-Object -First 1)
        if ($line -match '(\d+\.\d+\.\d+(?:[-+][^\s]+)?)') {
            return $Matches[1]
        }
    } catch { }
    return ''
}

function Resolve-CodexExecutablePath {
    param([string]$PreferredVersion)

    if (-not [string]::IsNullOrWhiteSpace($CodexExecutable)) {
        $expanded = [Environment]::ExpandEnvironmentVariables($CodexExecutable)
        if (Test-Path -LiteralPath $expanded -PathType Leaf) {
            return [IO.Path]::GetFullPath($expanded)
        }
        $explicit = Get-Command $expanded -ErrorAction SilentlyContinue
        if ($null -ne $explicit) { return $explicit.Source }
        throw "Codex executable was not found: $CodexExecutable"
    }

    # Prefer the exact binary used by an already-running Codex process. This is
    # more reliable than PATH on machines that have Desktop/VS Code/CLI builds
    # installed side by side. models_cache.json is shared and can be rewritten
    # by another Codex version, so its client_version is only a selection hint,
    # never an authority that makes a different local binary invalid.
    $candidates = New-Object System.Collections.Generic.List[string]
    try {
        foreach ($process in @(Get-Process -Name codex -ErrorAction SilentlyContinue)) {
            try {
                $candidate = $process.Path
                if (-not [string]::IsNullOrWhiteSpace($candidate) -and
                    (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                    $full = [IO.Path]::GetFullPath($candidate)
                    if (-not ($candidates | Where-Object { $_ -ieq $full })) {
                        $candidates.Add($full)
                    }
                }
            } catch { }
        }
    } catch { }

    $command = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        $full = [IO.Path]::GetFullPath($command.Source)
        if (-not ($candidates | Where-Object { $_ -ieq $full })) {
            $candidates.Add($full)
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($PreferredVersion)) {
        foreach ($candidate in $candidates) {
            $candidateVersion = Get-CodexExecutableVersion -Path $candidate
            if ($candidateVersion -eq $PreferredVersion) {
                Write-Host "Codex executable auto-selected for client version ${PreferredVersion}: $candidate"
                return $candidate
            }
        }
    }

    if ($candidates.Count -gt 0) {
        $selected = $candidates[0]
        $selectedVersion = Get-CodexExecutableVersion -Path $selected
        if (-not [string]::IsNullOrWhiteSpace($PreferredVersion) -and
            -not [string]::IsNullOrWhiteSpace($selectedVersion) -and
            $PreferredVersion -ne $selectedVersion) {
            Write-Warning "models_cache.json was last written by Codex $PreferredVersion, while the selected active/local binary is $selectedVersion at '$selected'. The cache is regenerable and may have been written by another installed Codex version; continuing with the selected binary instead of treating the cache version as authoritative."
        }
        return $selected
    }

    throw 'Codex CLI was not found from a running Codex process or PATH. Pass -CodexExecutable explicitly.'
}

function Get-ModelsCacheClientVersion {
    $cachePath = Join-Path (Split-Path -Parent $CodexConfig) 'models_cache.json'
    if (-not (Test-Path -LiteralPath $cachePath -PathType Leaf)) { return $null }
    try {
        $cache = [IO.File]::ReadAllText($cachePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($null -ne $cache -and $null -ne $cache.PSObject.Properties['client_version']) {
            return [string]$cache.client_version
        }
    } catch { return $null }
    return $null
}

function Export-HashNeutralBundledModelCatalog {
    if ($PreserveCompHash) {
        $script:ActiveCompHashNeutralCatalogPath = $null
        return $null
    }
    $cacheVersion = Get-ModelsCacheClientVersion
    $codex = Resolve-CodexExecutablePath -PreferredVersion $cacheVersion
    $codexVersion = Get-CodexExecutableVersion -Path $codex
    if ([string]::IsNullOrWhiteSpace($codexVersion)) {
        throw "Could not determine the Codex version for '$codex'. Pass -CodexExecutable explicitly if this is not the client binary."
    }
    if (-not [string]::IsNullOrWhiteSpace($cacheVersion) -and $cacheVersion -ne $codexVersion) {
        Write-Warning "models_cache.json client_version is $cacheVersion but the selected Codex binary is $codexVersion. This is allowed because models_cache.json is a shared, regenerable cache; the bundled catalog will be exported from the selected binary itself."
    }

    $output = @(& $codex debug models --bundled 2>$null)
    if ($LASTEXITCODE -ne 0) {
        $tail = ($output | Select-Object -Last 8) -join [Environment]::NewLine
        throw "'codex debug models --bundled' failed.$([Environment]::NewLine)$tail"
    }
    $raw = $output -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "'codex debug models --bundled' returned no catalog JSON." }
    try { $catalog = $raw | ConvertFrom-Json }
    catch { throw "Could not parse bundled Codex model catalog JSON. Details: $($_.Exception.Message)" }

    $removed = Remove-CompHashPropertiesRecursive -Node $catalog
    $json = $catalog | ConvertTo-Json -Depth 100 -Compress
    $temporary = "$BridgeOwnedModelCatalogPath.bridge-tmp-$PID"
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temporary, $json, $utf8NoBom)
    Move-Item -LiteralPath $temporary -Destination $BridgeOwnedModelCatalogPath -Force
    if ([string]::IsNullOrWhiteSpace($script:ActiveCompHashNeutralCatalogPath)) {
        $script:ActiveCompHashNeutralCatalogPath = $BridgeOwnedModelCatalogPath
    }
    Write-Host "CompHash bundled-catalog guard: exported Codex $codexVersion catalog and removed comp_hash from $removed model entr$(if ($removed -eq 1) { 'y' } else { 'ies' }): $BridgeOwnedModelCatalogPath"
    Write-Host 'CompHash bundled-catalog guard: resident mirror guard will keep provider-switch config rewrites hash-neutral while the Bridge is running.'
    return $BridgeOwnedModelCatalogPath
}

function Update-ConfiguredModelCatalogCompHashGuard {
    $catalogPath = Get-ConfiguredModelCatalogPath
    if ([string]::IsNullOrWhiteSpace($catalogPath)) {
        return 0
    }
    $catalogPath = [IO.Path]::GetFullPath($catalogPath)
    if ($catalogPath -eq $BridgeOwnedModelCatalogPath) {
        if (-not $PreserveCompHash) {
            $script:ActiveCompHashNeutralCatalogPath = $BridgeOwnedModelCatalogPath
        }
        return 0
    }
    if ($catalogPath -eq $ActiveNeutralModelCatalogPath) {
        if (-not $PreserveCompHash) {
            $script:ActiveCompHashNeutralCatalogPath = $ActiveNeutralModelCatalogPath
        }
        return 0
    }
    $catalogDirectory = [IO.Path]::GetDirectoryName($catalogPath)
    $catalogName = [IO.Path]::GetFileName($catalogPath)
    $scopedDirectory = [IO.Path]::GetDirectoryName($ScopedNeutralModelCatalogPath)
    $scopedBaseName = [IO.Path]::GetFileNameWithoutExtension($ScopedNeutralModelCatalogPath)
    $scopedExtension = [IO.Path]::GetExtension($ScopedNeutralModelCatalogPath)
    $isScopedSnapshot = ($catalogDirectory -ieq $scopedDirectory) -and (
        ($catalogPath -ieq $ScopedNeutralModelCatalogPath) -or
        ($catalogName -match ('^' + [regex]::Escape($scopedBaseName) + '\.snapshot-[0-9a-fA-F]{8,}' + [regex]::Escape($scopedExtension) + '$'))
    )
    if ($isScopedSnapshot) {
        if (-not $PreserveCompHash) {
            # The resident bridge already published this hash-neutral provider-only
            # snapshot. Keep it wired through startup instead of copying it back
            # into the private learned catalog.
            $script:ActiveCompHashNeutralCatalogPath = $catalogPath
        }
        return 0
    }
    if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
        Write-Warning "CompHash static-catalog guard: model_catalog_json points to a missing file: $catalogPath"
        return 0
    }
    if ($PreserveCompHash) {
        return 0
    }

    try {
        $raw = [IO.File]::ReadAllText($catalogPath, [Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($raw)) { return 0 }
        $catalog = $raw | ConvertFrom-Json
        $removed = Remove-CompHashPropertiesRecursive -Node $catalog
        $json = $catalog | ConvertTo-Json -Depth 100 -Compress
        $temporary = "$ActiveNeutralModelCatalogPath.bridge-tmp-$PID"
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporary, $json, $utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $ActiveNeutralModelCatalogPath -Force

        $sourceInfo = [ordered]@{
            source_path = $catalogPath
            source_signature = @(
                ([IO.File]::GetLastWriteTimeUtc($catalogPath)).Ticks,
                ([IO.FileInfo]::new($catalogPath)).Length
            )
        } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($ActiveNeutralCatalogSidecarPath, $sourceInfo, $utf8NoBom)
        $script:ActiveCompHashNeutralCatalogPath = $ActiveNeutralModelCatalogPath
        Write-Host "CompHash static-catalog guard: copied provider catalog to bridge-owned neutral mirror; removed $removed comp_hash field$(if ($removed -eq 1) { '' } else { 's' }): $ActiveNeutralModelCatalogPath"
        return $removed
    } catch {
        Write-Warning "CompHash static-catalog guard could not mirror $catalogPath. Details: $($_.Exception.Message)"
        return 0
    }
}

function Update-ModelsCacheCompHashGuard {
    $codexHome = Split-Path -Parent $CodexConfig
    $cachePath = Join-Path $codexHome 'models_cache.json'

    if ($PreserveCompHash) {
        # The cache may have been neutralized by an earlier guarded run. It is
        # regenerable, so remove it and let Codex refetch unmodified metadata.
        if (Test-Path -LiteralPath $cachePath -PathType Leaf) {
            Remove-Item -LiteralPath $cachePath -Force
            Write-Host "CompHash cache guard: preserve requested; removed $cachePath so Codex can refetch unmodified model metadata."
        }
        return 0
    }

    if (-not (Test-Path -LiteralPath $cachePath -PathType Leaf)) {
        return 0
    }

    try {
        $raw = [IO.File]::ReadAllText($cachePath, [Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return 0
        }
        $catalog = $raw | ConvertFrom-Json
        if ($null -eq $catalog) {
            return 0
        }

        $removed = Remove-CompHashPropertiesRecursive -Node $catalog
        if ($removed -le 0) {
            return 0
        }

        # models_cache.json is a regenerable cache, not session history. Rewrite it
        # atomically enough for local use without creating backup-file clutter.
        $json = $catalog | ConvertTo-Json -Depth 100 -Compress
        $temporary = "$cachePath.bridge-tmp-$PID"
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporary, $json, $utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $cachePath -Force
        Write-Host "CompHash cache guard: removed comp_hash from $removed cached model entr$(if ($removed -eq 1) { 'y' } else { 'ies' }) in $cachePath"
        return $removed
    } catch {
        Write-Warning "CompHash cache guard could not update $cachePath. The live /models guard will still be used. Details: $($_.Exception.Message)"
        return 0
    }
}

function Start-Bridge {
    # Recover from an interrupted graceful-exit attempt. The handoff latch is only
    # meaningful while Exit is switching custom.base_url to direct Official; a
    # fresh start must re-enable the resident guard before wiring custom back to :15722.
    Remove-Item -LiteralPath $NativeDetachFlagPath -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path -LiteralPath $BridgeScript -PathType Leaf)) {
        throw "Bridge script not found: $BridgeScript"
    }
    $resolvedBridgeScript = (Resolve-Path -LiteralPath $BridgeScript).Path

    if (-not (Test-Path -LiteralPath $StateDirectory)) {
        New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    }

    # Do not freeze the Official model seen at bridge startup. CC Switch/Codex may
    # switch Luna/Sol while the bridge remains resident. -Model is now explicit-only.

    $existingState = Read-BridgeState
    $existingProcess = Get-ManagedBridgeProcess -State $existingState
    $existingModel = ''
    if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['model_override']) {
        $existingModel = [string]$existingState.model_override
    }
    $existingVersion = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['bridge_version']) {
        [string]$existingState.bridge_version
    } else { '' }
    $existingUpstream = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['upstream_url']) {
        [string]$existingState.upstream_url
    } else { '' }
    $existingWsUpstream = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['responses_ws_upstream_url']) {
        [string]$existingState.responses_ws_upstream_url
    } else { '' }
    $existingPreserveCompHash = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['preserve_comp_hash']) {
        [bool]$existingState.preserve_comp_hash
    } else {
        $false
    }
    $existingCatalogGuard = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['catalog_guard']) {
        [string]$existingState.catalog_guard
    } else { '' }
    $existingSwitchReplayCompaction = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['switch_replay_compaction']) {
        [bool]$existingState.switch_replay_compaction
    } else { $false }
    $existingSwitchReplayThresholdBytes = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['switch_replay_threshold_bytes']) {
        [int]$existingState.switch_replay_threshold_bytes
    } else { -1 }
    $existingSwitchReplayRecentUserTurns = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['switch_replay_recent_user_turns']) {
        [int]$existingState.switch_replay_recent_user_turns
    } else { -1 }
    $existingProviderContinuation = if ($null -ne $existingState -and
        $null -ne $existingState.PSObject.Properties['provider_continuation']) {
        [bool]$existingState.provider_continuation
    } else { $false }
    $requestedSwitchReplayCompaction = [bool]$EnableSwitchReplayCompaction -and -not [bool]$DisableSwitchReplayCompaction
    $requestedPromptCacheOptimization = [bool]$EnablePromptCacheOptimization -and -not [bool]$DisablePromptCacheOptimization
    $requestedProviderContinuation = -not [bool]$DisableProviderContinuation
    $requestedModel = if ([string]::IsNullOrWhiteSpace($Model)) {
        $existingModel
    } else {
        $Model.Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($requestedModel)) {
        $Model = $requestedModel
    }

    # Mirror any external provider catalog into a private hash-neutral learned copy,
    # and always keep an exact bundled neutral catalog ready for the Official route.
    # The resident bridge guard publishes a provider-scoped immutable picker catalog
    # after each CC Switch route rewrite.
    Update-ConfiguredModelCatalogCompHashGuard | Out-Null
    Export-HashNeutralBundledModelCatalog | Out-Null
    Update-ModelsCacheCompHashGuard | Out-Null

    if ($null -ne $existingProcess -and
        (Test-TcpEndpoint -Address $ListenAddress -Port ([int]$existingState.port))) {
        if ($RunForeground) {
            Write-Host 'Restarting the existing managed bridge in foreground mode.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingVersion -ne $BridgeManagerVersion) {
            Write-Host "Bridge version changed ($existingVersion -> $BridgeManagerVersion); restarting it."
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingUpstream -ne $UpstreamUrl -or $existingWsUpstream -ne $ResponsesWebSocketUpstreamUrl) {
            Write-Host 'Bridge upstream configuration changed; restarting it.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingModel -ne $requestedModel) {
            Write-Host "Bridge model override changed ($existingModel -> $requestedModel); restarting it."
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingSwitchReplayCompaction -ne $requestedSwitchReplayCompaction -or
                  $existingSwitchReplayThresholdBytes -ne $SwitchReplayThresholdBytes -or
                  $existingSwitchReplayRecentUserTurns -ne $SwitchReplayRecentUserTurns) {
            Write-Host 'Bridge switch-replay token policy changed; restarting it.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingProviderContinuation -ne $requestedProviderContinuation) {
            Write-Host 'Bridge provider-continuation policy changed; restarting it.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif ($existingPreserveCompHash -ne [bool]$PreserveCompHash) {
            Write-Host 'Bridge CompHash policy changed; restarting it.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } elseif (-not $PreserveCompHash -and $existingCatalogGuard -ne $CatalogGuardGeneration) {
            Write-Host 'Bridge resident catalog guard changed; restarting it.'
            Stop-Bridge -NoConfigWarning
            $existingState = $null
            $existingProcess = $null
        } else {
            Write-Host "Bridge is already running on http://$ListenAddress`:$($existingState.port)"
            Update-CodexConfig -Port ([int]$existingState.port) | Out-Null
            return
        }
    }

    if ($null -ne $existingState -and $null -eq $existingProcess) {
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }

    $selectedPort = $BridgePort
    if (-not (Test-PortAvailable -Port $selectedPort)) {
        if ($FixedPort) {
            throw "Port $selectedPort is already in use. Stop that process or choose another -BridgePort."
        }
        $selectedPort = Find-AvailablePort -StartPort ($BridgePort + 1)
        Write-Warning "Port $BridgePort is occupied; using $selectedPort instead."
    }

    $bridgeIsStandaloneExe = ([IO.Path]::GetExtension($resolvedBridgeScript) -ieq '.exe')
    if ($bridgeIsStandaloneExe) {
        $bridgeRuntimeFile = $resolvedBridgeScript
        $arguments = @(
            '--listen',
        "$ListenAddress`:$selectedPort",
        '--upstream',
        $UpstreamUrl,
        '--responses-ws-upstream',
        $ResponsesWebSocketUpstreamUrl,
        '--codex-config',
        ('"' + $CodexConfig.Replace('"', '\"') + '"'),
        '--bundled-neutral-catalog',
        ('"' + $BridgeOwnedModelCatalogPath.Replace('"', '\"') + '"'),
        '--active-neutral-catalog',
        ('"' + $ActiveNeutralModelCatalogPath.Replace('"', '\"') + '"'),
        '--official-provider-id',
        $OfficialProviderId,
        '--bridge-provider-id',
        $ProviderId,
        '--bridge-provider-name',
        $ProviderName,
        '--bridge-base-url',
        "http://$ListenAddress`:$selectedPort/v1",
        '--realtime-ws-base-url',
        $RealtimeWsBaseUrl,
        '--realtime-webrtc-call-base-url',
        $RealtimeWebRtcCallBaseUrl
        )
    } else {
        $python = Resolve-PythonCommand
        $quotedScript = '"' + $resolvedBridgeScript.Replace('"', '\"') + '"'
        $bridgeRuntimeFile = $python.FilePath
        $arguments = @($python.PrefixArguments) + @(
            '-u',
            $quotedScript,
            '--listen',
            "$ListenAddress`:$selectedPort",
            '--upstream',
            $UpstreamUrl,
            '--responses-ws-upstream',
            $ResponsesWebSocketUpstreamUrl,
            '--codex-config',
            ('"' + $CodexConfig.Replace('"', '\"') + '"'),
            '--bundled-neutral-catalog',
            ('"' + $BridgeOwnedModelCatalogPath.Replace('"', '\"') + '"'),
            '--active-neutral-catalog',
            ('"' + $ActiveNeutralModelCatalogPath.Replace('"', '\"') + '"'),
            '--official-provider-id',
            $OfficialProviderId,
            '--bridge-provider-id',
            $ProviderId,
            '--bridge-provider-name',
            $ProviderName,
            '--bridge-base-url',
            "http://$ListenAddress`:$selectedPort/v1",
            '--realtime-ws-base-url',
            $RealtimeWsBaseUrl,
            '--realtime-webrtc-call-base-url',
            $RealtimeWebRtcCallBaseUrl
        )
    }
    if (-not [string]::IsNullOrWhiteSpace($Model)) {
        $arguments += @('--model-override', $Model)
    }
    if ($PreserveCompHash) {
        $arguments += '--preserve-comp-hash'
    }
    if ($EnablePromptCacheOptimization) {
        $arguments += '--enable-prompt-cache-optimization'
    } elseif ($DisablePromptCacheOptimization) {
        $arguments += '--disable-prompt-cache-optimization'
    }
    if ($EnableSwitchReplayCompaction) {
        $arguments += '--enable-switch-replay-compaction'
    } elseif ($DisableSwitchReplayCompaction) {
        $arguments += '--disable-switch-replay-compaction'
    }
    if ($DisableProviderContinuation) {
        $arguments += '--disable-provider-continuation'
    }
    $arguments += @('--switch-replay-threshold-bytes', [string]$SwitchReplayThresholdBytes)
    $arguments += @('--switch-replay-recent-user-turns', [string]$SwitchReplayRecentUserTurns)

    # Never use the package/update folder as the resident bridge CWD.  Windows
    # keeps a directory busy while a long-lived process has it as its current
    # directory, even though the Python script itself is no longer open.
    New-Item -ItemType Directory -Path $RuntimeWorkingDirectory -Force | Out-Null
    $startParameters = @{
        FilePath = $bridgeRuntimeFile
        ArgumentList = $arguments
        WorkingDirectory = $RuntimeWorkingDirectory
        PassThru = $true
    }
    if ($RunForeground) {
        $startParameters['NoNewWindow'] = $true
    } else {
        $startParameters['RedirectStandardOutput'] = $StdoutLog
        $startParameters['RedirectStandardError'] = $StderrLog
        $startParameters['WindowStyle'] = 'Hidden'
    }
    $process = Start-Process @startParameters

    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        if ($process.HasExited) {
            break
        }
        if (Test-TcpEndpoint -Address $ListenAddress -Port $selectedPort -TimeoutMs 150) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) {
        $errorTail = if (Test-Path -LiteralPath $StderrLog) {
            (Get-Content -LiteralPath $StderrLog -Tail 8 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        } else {
            ''
        }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Bridge failed to start.$([Environment]::NewLine)$errorTail"
    }

    $state = [ordered]@{
        bridge_version = $BridgeManagerVersion
        pid = $process.Id
        port = $selectedPort
        listen_address = $ListenAddress
        upstream_url = $UpstreamUrl
        responses_ws_upstream_url = $ResponsesWebSocketUpstreamUrl
        bridge_script = $resolvedBridgeScript
        model_override = $Model
        preserve_comp_hash = [bool]$PreserveCompHash
        prompt_cache_optimization = $requestedPromptCacheOptimization
        switch_replay_compaction = $requestedSwitchReplayCompaction
        provider_continuation = $requestedProviderContinuation
        switch_replay_threshold_bytes = $SwitchReplayThresholdBytes
        switch_replay_recent_user_turns = $SwitchReplayRecentUserTurns
        catalog_guard = if ($PreserveCompHash) { 'disabled' } else { $CatalogGuardGeneration }
        started_at = (Get-Date).ToString('o')
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8

    Update-CodexConfig -Port $selectedPort | Out-Null
    if (-not (Test-TcpEndpoint -Address $UpstreamUri.Host -Port $UpstreamUri.Port)) {
        Write-Warning "Bridge is running, but CC Switch is not reachable at $UpstreamUrl. Start its route service before sending requests."
    }
    Write-Host "Bridge started: http://$ListenAddress`:$selectedPort"
    Write-Host "HTTP /responses upstream: $UpstreamUrl"
    Write-Host "Responses WebSocket direct fallback: $ResponsesWebSocketUpstreamUrl"
    Write-Host 'Responses transport: Official Responses WS goes direct first (avoids CC Switch 405 probe rows); third-party routes stay HTTP-only through CC Switch.'
    Write-Host 'Token policy: auth-aware restart continuity. Codex may restart when CC Switch must reload the selected ChatGPT account/model UI; keep the Bridge running. Matching Official restart replays are converted to resident-session deltas; returning third-party models use conversation-scoped shadow cursors, durable previous_response_id catch-up, and guarded restart instruction-envelope pinning when supported. No replay pruning is used by default.'
    $cacheMode = if ($requestedPromptCacheOptimization) { 'explicit markers enabled (native implicit cache also active)' } else { 'explicit markers disabled; native implicit cache only' }
    Write-Host "Prompt-cache optimization: $cacheMode"
    $switchReplayMode = if ($requestedSwitchReplayCompaction) { "enabled by opt-in (threshold=$SwitchReplayThresholdBytes bytes; recent user turns=$SwitchReplayRecentUserTurns)" } else { 'disabled by default; full fallback history is preserved' }
    Write-Host "Switch replay compaction: $switchReplayMode"
    Write-Host ("Provider continuation: " + $(if ($requestedProviderContinuation) { "enabled (Official guarded resident WS across Codex restart; third-party durable delta)" } else { "disabled" }))
    if ($PreserveCompHash) {
        Write-Host 'CompHash switch guard: disabled; upstream model comp_hash is preserved.'
    } elseif ([string]::IsNullOrWhiteSpace($Model)) {
        Write-Host 'CompHash switch guard: enabled; provider-scoped catalog guard exposes only the active CC Switch provider in Codex while retaining a private learned catalog for routing/capability metadata; provider files are never modified in place.'
    } else {
        Write-Host "CompHash switch guard: enabled; provider-scoped catalog guard follows provider-switch rewrites and rotates Codex to a current-provider-only hash-neutral catalog. /models and models_cache.json remain fallbacks. Request-model override remains '$Model'."
    }
    Write-Host "Realtime voice sideband WebSocket: $RealtimeWsBaseUrl (bypasses bridge)"
    Write-Host "Realtime voice call creation: $RealtimeWebRtcCallBaseUrl (bypasses bridge)"
    if ($RunForeground) {
        Write-Host 'Foreground mode is active. Press Ctrl+C, close this window, or terminate the VS Code task to stop the bridge.'
        Write-Host 'Reload Codex separately if it has not read the updated config yet.'
        try {
            $process.WaitForExit()
        } finally {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
            $currentState = Read-BridgeState
            if ($null -ne $currentState -and [int]$currentState.pid -eq $process.Id) {
                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
            }
        }
        return
    }
    Write-Host 'Reload the VS Code window or restart Codex so it reads the updated config.'
}

function Repair-BridgeConfig {
    $state = Read-BridgeState
    $process = Get-ManagedBridgeProcess -State $state
    if ([string]::IsNullOrWhiteSpace($Model) -and
        $null -ne $state -and
        $null -ne $state.PSObject.Properties['model_override'] -and
        -not [string]::IsNullOrWhiteSpace([string]$state.model_override)) {
        $Model = [string]$state.model_override
    }
    $port = $BridgePort
    if ($null -ne $process -and
        $null -ne $state.port -and
        (Test-TcpEndpoint -Address $ListenAddress -Port ([int]$state.port))) {
        $port = [int]$state.port
    } elseif (-not (Test-TcpEndpoint -Address $ListenAddress -Port $port)) {
        Write-Warning "No managed bridge is currently listening on port $port. The config will be repaired, but requests will fail until the bridge starts."
    }
    Update-ConfiguredModelCatalogCompHashGuard | Out-Null
    Export-HashNeutralBundledModelCatalog | Out-Null
    Update-ModelsCacheCompHashGuard | Out-Null
    Update-CodexConfig -Port $port | Out-Null
    Write-Host "Repair complete. Codex provider '$ProviderId' points to http://$ListenAddress`:$port/v1"
}

function Show-BridgeStatus {
    $state = Read-BridgeState
    $process = Get-ManagedBridgeProcess -State $state
    $port = if ($null -ne $state -and $null -ne $state.port) { [int]$state.port } else { $BridgePort }
    $bridgeListening = Test-TcpEndpoint -Address $ListenAddress -Port $port
    $upstreamListening = Test-TcpEndpoint -Address $UpstreamUri.Host -Port $UpstreamUri.Port

    [pscustomobject]@{
        BridgeVersion = $BridgeManagerVersion
        ManagedProcess = ($null -ne $process)
        ProcessId = if ($null -ne $process) { $process.ProcessId } else { $null }
        BridgeUrl = "http://$ListenAddress`:$port"
        BridgeListening = $bridgeListening
        UpstreamUrl = $UpstreamUrl
        ResponsesWebSocketUpstreamUrl = $ResponsesWebSocketUpstreamUrl
        ResponsesWebSocketPolicy = 'cc-switch-first-direct-official-fallback'
        ModelOverride = if ($null -ne $state -and
            $null -ne $state.PSObject.Properties['model_override']) {
            [string]$state.model_override
        } else {
            $null
        }
        CatalogConfigGuard = if ($null -ne $state -and $null -ne $state.PSObject.Properties['catalog_guard']) { [string]$state.catalog_guard } else { 'none' }
        CompHashSwitchGuard = if ($null -ne $state -and
            $null -ne $state.PSObject.Properties['preserve_comp_hash'] -and
            [bool]$state.preserve_comp_hash) { 'preserve' } else { 'neutralize-catalog' }
        UpstreamListening = $upstreamListening
        ResponsesTransport = 'websocket-preferred'
        ResponsesContinuation = 'incremental-previous_response_id'
        HttpFallback = 'conservative-full-replay'
        RealtimeVoiceRoute = 'native-chatgpt-openai'
        RealtimeWsBaseUrl = $RealtimeWsBaseUrl
        RealtimeWebRtcCallBaseUrl = $RealtimeWebRtcCallBaseUrl
        CodexConfig = $CodexConfig
        StateFile = $StateFile
    } | Format-List
}

function Show-BridgeDoctor {
    Write-Host 'Codex Cross-Provider Bridge portability check'
    Write-Host "ManagerScript: $($MyInvocation.ScriptName)"
    Write-Host "BridgeScript: $BridgeScript"
    Write-Host "BridgeScriptExists: $(Test-Path -LiteralPath $BridgeScript -PathType Leaf)"
    if ([IO.Path]::GetExtension($BridgeScript) -ieq '.exe') {
        Write-Host 'BridgeRuntime: standalone-exe (Python not required)'
        Write-Host 'Python: not required for this installed release'
    } else {
        try {
            $python = Resolve-PythonCommand
            Write-Host "Python: $($python.FilePath)"
            Write-Host "PythonVersion: $($python.Version)"
        } catch {
            Write-Host "Python: ERROR - $($_.Exception.Message)"
        }
    }
    Write-Host "CodexConfig: $CodexConfig"
    Write-Host "CodexConfigExists: $(Test-Path -LiteralPath $CodexConfig -PathType Leaf)"
    $configMode = if (Test-CodexConfigNeedsBridge) { 'official-or-bridge' } else { 'third-party-or-other' }
    Write-Host "DetectedConfigMode: $configMode"
    Write-Host "PreferredBridgePortAvailable: $(Test-PortAvailable -Port $BridgePort)"
    Write-Host "UpstreamUrl: $UpstreamUrl"
    Write-Host "UpstreamListening: $(Test-TcpEndpoint -Address $UpstreamUri.Host -Port $UpstreamUri.Port)"
    Write-Host "ResponsesWebSocketUpstreamUrl: $ResponsesWebSocketUpstreamUrl"
    Write-Host 'ResponsesWebSocketPolicy: cc-switch-first-direct-official-fallback'
    Write-Host 'ResponsesTransport: websocket-preferred (HTTP fallback remains available)'
    Write-Host 'ResponsesContinuation: trusted previous_response_id + incremental input after bootstrap'
    $doctorCompHashPolicy = if ($PreserveCompHash) {
        'preserve'
    } else {
        'neutralize-catalog'
    }
    Write-Host "CompHashSwitchGuard: $doctorCompHashPolicy"
    Write-Host 'RealtimeVoiceRoute: native-chatgpt-openai (bypasses local bridge and CC Switch)'
    Write-Host "RealtimeWsBaseUrl: $RealtimeWsBaseUrl"
    Write-Host "RealtimeWebRtcCallBaseUrl: $RealtimeWebRtcCallBaseUrl"
    Show-BridgeStatus
}

function Get-ResidualBridgeProcesses {
    # State files can become stale after launcher/manager upgrades or a previous
    # abnormal exit.  Find bridge interpreters by their distinctive script name
    # so `stop` really means no resident bridge remains.
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
        $_.CommandLine -match '(?i)codex_provider_bridge(?:\.py)?'
    })
}

function Get-BridgeRouteSnapshot {
    if (-not (Test-Path -LiteralPath $ActiveNeutralCatalogSidecarPath -PathType Leaf)) {
        return $null
    }
    try {
        $payload = [IO.File]::ReadAllText($ActiveNeutralCatalogSidecarPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($null -eq $payload) { return $null }
        $kind = if ($null -ne $payload.PSObject.Properties['route_kind']) { [string]$payload.route_kind } else { '' }
        $model = if ($null -ne $payload.PSObject.Properties['route_model']) { [string]$payload.route_model } else { '' }
        return [pscustomobject]@{ kind = $kind; model = $model }
    } catch {
        return $null
    }
}

function Prepare-DirectOfficialCustomConfig {
    # Freeze the resident Python catalog/config guard before changing custom.base_url.
    # The latch name is retained for compatibility with already-installed Bridge
    # binaries, but its semantics are now "direct Official handoff", not removal
    # of model_provider=custom.
    $flagDirectory = Split-Path -Parent $NativeDetachFlagPath
    if (-not (Test-Path -LiteralPath $flagDirectory)) {
        New-Item -ItemType Directory -Path $flagDirectory -Force | Out-Null
    }
    $utf8NoBomFlag = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($NativeDetachFlagPath, ((Get-Date).ToString('o') + [Environment]::NewLine), $utf8NoBomFlag)
    Start-Sleep -Milliseconds 350

    try {
        $configDirectory = Split-Path -Parent $CodexConfig
        if (-not (Test-Path -LiteralPath $configDirectory)) {
            New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
        }

        $exists = Test-Path -LiteralPath $CodexConfig -PathType Leaf
        $original = if ($exists) { [IO.File]::ReadAllText($CodexConfig) } else { '' }
        $newline = if ($original.Contains("`r`n")) { "`r`n" } else { "`n" }
        $splitLines = if ($original.Length -eq 0) { @() } else { [regex]::Split($original, '\r?\n') }
        $lines = [System.Collections.Generic.List[string]]::new()
        foreach ($line in $splitLines) { $lines.Add([string]$line) | Out-Null }

        $configuredModel = if ($original.Length -gt 0) { Get-TopLevelTomlString -Text $original -Key 'model' } else { $null }
        $route = Get-BridgeRouteSnapshot
        $officialModel = ''
        if ($null -ne $route -and -not [string]::IsNullOrWhiteSpace([string]$route.model) -and
            [string]$route.model -match '(?i)^(gpt-|o[0-9]|codex)') {
            $officialModel = ([string]$route.model).Trim()
        } elseif (-not [string]::IsNullOrWhiteSpace($configuredModel) -and
                  $configuredModel -match '(?i)^(gpt-|o[0-9]|codex)') {
            $officialModel = $configuredModel.Trim()
        }

        # Keep the provider identity stable. Only its transport target changes.
        Set-TopLevelTomlKey -Lines $lines -Key 'model_provider' -Value (Escape-TomlString $ProviderId)
        Remove-TopLevelTomlKey -Lines $lines -Key 'disable_response_storage'
        Set-TopLevelTomlKey -Lines $lines -Key 'experimental_realtime_ws_base_url' -Value (Escape-TomlString $RealtimeWsBaseUrl)
        Set-TopLevelTomlKey -Lines $lines -Key 'experimental_realtime_webrtc_call_base_url' -Value (Escape-TomlString $RealtimeWebRtcCallBaseUrl)

        # A direct-Official session must not keep a third-party provider-scoped
        # picker. The bundled neutral catalog is the exact Official catalog
        # exported from the local Codex binary, with only comp_hash removed.
        if (Test-Path -LiteralPath $BridgeOwnedModelCatalogPath -PathType Leaf) {
            Set-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json' -Value (Escape-TomlString $BridgeOwnedModelCatalogPath)
        } else {
            Remove-TopLevelTomlKey -Lines $lines -Key 'model_catalog_json'
        }

        if (-not [string]::IsNullOrWhiteSpace($officialModel)) {
            Set-TopLevelTomlKey -Lines $lines -Key 'model' -Value (Escape-TomlString $officialModel)
        } elseif (-not [string]::IsNullOrWhiteSpace($configuredModel) -and
                  $configuredModel -notmatch '(?i)^(gpt-|o[0-9]|codex)') {
            # Do not leave a GLM/DeepSeek/Qwen model selected while custom points
            # directly at the Official backend. Let Codex choose its Official default.
            Remove-TopLevelTomlKey -Lines $lines -Key 'model'
        }

        $escapedProvider = [regex]::Escape($ProviderId)
        $providerPattern = '^\s*\[model_providers\.(?:' + $escapedProvider + '|"' + $escapedProvider + '")\]\s*$'
        $providerHeader = "[model_providers.$ProviderId]"
        Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'name' -Value (Escape-TomlString $ProviderName)
        Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'base_url' -Value (Escape-TomlString $DirectOfficialBaseUrl)
        Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'wire_api' -Value '"responses"'
        Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'requires_openai_auth' -Value 'true'
        Set-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -NewHeader $providerHeader -Key 'supports_websockets' -Value 'true'

        $updated = [string]::Join($newline, $lines.ToArray())
        if ($updated -cne $original) {
            $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
            $backup = if ($exists) { [IO.Path]::GetFullPath("$CodexConfig.bridge-direct-official-backup-$timestamp") } else { $null }
            $temporary = [IO.Path]::GetFullPath((Join-Path $configDirectory ("config.toml.bridge-direct-official-tmp-" + [Guid]::NewGuid().ToString('N'))))
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            try {
                [IO.File]::WriteAllText($temporary, $updated, $utf8NoBom)
                if ($exists) {
                    try {
                        [IO.File]::Replace($temporary, $CodexConfig, $backup, $true)
                    } catch {
                        $replaceError = $_.Exception
                        if (-not (Test-Path -LiteralPath $temporary -PathType Leaf)) { throw $replaceError }
                        Copy-Item -LiteralPath $CodexConfig -Destination $backup -Force
                        Copy-Item -LiteralPath $temporary -Destination $CodexConfig -Force
                        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
                    }
                } else {
                    Move-Item -LiteralPath $temporary -Destination $CodexConfig -Force
                }
            } finally {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            }
            Write-Host "Prepared direct Official custom-provider routing: $CodexConfig"
            if ($null -ne $backup) { Write-Host "Direct-Official backup created: $backup" }
        } else {
            Write-Host 'Codex custom provider already points directly to the Official ChatGPT Codex backend.'
        }

        # Give a resident guard one more chance to race; the latch must prevent it.
        Start-Sleep -Milliseconds 150
        $verifyText = [IO.File]::ReadAllText($CodexConfig)
        $verifyProvider = Get-TopLevelTomlString -Text $verifyText -Key 'model_provider'
        $verifyBaseUrl = Get-ProviderBaseUrl -Text $verifyText -Id $ProviderId
        if ($verifyProvider -ne $ProviderId) {
            throw "Direct Official handoff verification failed: model_provider is '$verifyProvider', expected '$ProviderId'."
        }
        if ([string]::IsNullOrWhiteSpace($verifyBaseUrl) -or
            $verifyBaseUrl.TrimEnd('/') -ne $DirectOfficialBaseUrl.TrimEnd('/')) {
            throw "Direct Official handoff verification failed: custom.base_url is '$verifyBaseUrl'."
        }
        Write-Host "Direct Official handoff verified: model_provider=$ProviderId; base_url=$DirectOfficialBaseUrl"
        return $true
    } catch {
        # If preparation fails, re-enable the still-running resident guard and
        # cancel Exit rather than leaving Codex on a half-written route.
        Remove-Item -LiteralPath $NativeDetachFlagPath -Force -ErrorAction SilentlyContinue
        throw
    }
}

# Compatibility alias for older launchers/scripts. The operation no longer
# removes model_provider=custom; it changes custom.base_url to the Official backend.
function Restore-NativeOfficialConfig {
    return Prepare-DirectOfficialCustomConfig
}

function Detach-Bridge {
    Prepare-DirectOfficialCustomConfig | Out-Null
    Stop-Bridge -NoConfigWarning
    Write-Host 'Bridge stopped safely. Codex keeps model_provider=custom and now targets the Official ChatGPT Codex backend directly.'
}

function Stop-Bridge {
    param([switch]$NoConfigWarning)

    $stopped = New-Object 'System.Collections.Generic.HashSet[int]'
    $state = Read-BridgeState
    $process = Get-ManagedBridgeProcess -State $state
    if ($null -ne $process) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            [void]$stopped.Add([int]$process.ProcessId)
            Write-Host "Stopped managed bridge process $($process.ProcessId)."
        } catch {
            Write-Warning "Could not stop managed bridge PID $($process.ProcessId): $($_.Exception.Message)"
        }
    }

    # Second pass: kill orphan bridge interpreters whose PID is missing/stale in
    # bridge-state.json.  This fixes update-folder locks left by older versions.
    foreach ($orphan in @(Get-ResidualBridgeProcesses)) {
        # `$PID` is a read-only automatic PowerShell variable (case-insensitive).
        # Never assign to `$pid` here: doing so terminates `stop/start` with exit 1
        # exactly when an old bridge must be cleaned up during an upgrade.
        $orphanPid = [int]$orphan.ProcessId
        if ($stopped.Contains($orphanPid)) { continue }
        try {
            Stop-Process -Id $orphanPid -Force -ErrorAction Stop
            [void]$stopped.Add($orphanPid)
            Write-Host "Stopped residual bridge process $orphanPid."
        } catch {
            Write-Warning "Could not stop residual bridge PID ${orphanPid}: $($_.Exception.Message)"
        }
    }

    Start-Sleep -Milliseconds 350
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    # It is safe to release the native-detach latch only after all bridge
    # interpreters are gone; until then the resident guard must remain read-only.
    Remove-Item -LiteralPath $NativeDetachFlagPath -Force -ErrorAction SilentlyContinue
    if ($stopped.Count -eq 0) {
        Write-Host 'No resident bridge process was found.'
    }
    if (-not $NoConfigWarning -and (Test-CodexConfigNeedsBridge)) {
        Write-Warning 'Codex config still points to the local Bridge. Run prepare-direct-official before a deliberate long-term stop, or run start to restore the Bridge.'
    }
}

function Invoke-AutomaticBridge {
    if (Test-CodexConfigNeedsBridge) {
        Write-Host 'Official/bridge Codex configuration detected; ensuring the bridge is running.'
        Start-Bridge
        return
    }

    $state = Read-BridgeState
    $process = Get-ManagedBridgeProcess -State $state
    if ($null -ne $process) {
        Write-Host 'Third-party configuration detected; leaving the already-running bridge resident and idle. Its resident provider-scoped catalog guard will maintain current-provider-only model_catalog_json wiring; provider/model routing remains owned by the current configuration. Use stop to terminate it explicitly.'
    } else {
        Write-Host 'Third-party or non-bridge Codex configuration detected; no bridge will be started.'
        if (Test-Path -LiteralPath $StateFile) {
            Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
        }
    }
}

switch ($Command.ToLowerInvariant()) {
    'auto'   { Invoke-AutomaticBridge }
    'start'  { Start-Bridge }
    'repair' { Repair-BridgeConfig }
    'status' { Show-BridgeStatus }
    'doctor' { Show-BridgeDoctor }
    'stop'           { Stop-Bridge }
    'prepare-direct-official' { Prepare-DirectOfficialCustomConfig | Out-Null }
    'prepare-detach'          { Prepare-DirectOfficialCustomConfig | Out-Null }
    'detach'                  { Detach-Bridge }
}
