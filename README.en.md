<div align="center">

# CodexBridge

**Keep one Codex conversation usable while moving between ChatGPT/Codex account-authenticated Official access and API providers.**

CodexBridge is not a model aggregator. It is a Codex **cross-auth, cross-provider, cross-backend session-continuity compatibility layer** for the boundary between account-authenticated Official Codex and API-key providers.

[简体中文](README.md) · [Architecture](docs/ARCHITECTURE.md)

[![Windows CI](../../actions/workflows/build-windows-release.yml/badge.svg)](../../actions/workflows/build-windows-release.yml)
[![macOS CI](../../actions/workflows/build-macos-release.yml/badge.svg)](../../actions/workflows/build-macos-release.yml)
[![Releases](https://img.shields.io/badge/Releases-download-blue)](../../releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-Beta-orange.svg)](#project-status)

</div>

> [!IMPORTANT]
> CodexBridge is an **unofficial CC Switch companion**. It is not an official OpenAI or CC Switch component. The project is still Beta, and upstream Codex / CC Switch / API changes may require new compatibility work.

## What problem does it actually solve?

Many multi-model gateways already expose Qwen, DeepSeek, GLM, and other models behind **one API key / one fixed endpoint**. That is fundamentally an **API ↔ API** problem: Codex still talks to one API provider while the gateway switches models internally, so conversation continuity is usually much easier to preserve.

CodexBridge targets a different boundary:

```text
ChatGPT / Codex account-authenticated access
                 ↕
             CodexBridge
                 ↕
Third-party / OpenAI API-key providers
```

The core problem is therefore not “model switching.” It is:

> **Keeping the same Codex conversation as continuous as possible while switching between ChatGPT/Codex account-authenticated access and API-provider access.**

That crosses **authentication systems, providers, and backends**. Account-authenticated Official Codex and API-key providers do not naturally share the same server-side continuation state, and CodexBridge operates at that boundary.

> [!NOTE]
> If all of your models already sit behind one compatible API gateway and you can switch models inside that gateway without breaking the same Codex conversation, you may not need CodexBridge.

## Why is a session-compatibility layer still needed?

CC Switch is good at switching providers. But **a successful provider switch does not automatically mean the same Codex conversation can continue cleanly**.

A Codex context contains more than visible chat text. It may also carry `previous_response_id`, provider-owned item IDs, reasoning items, encrypted content, model names, and server-side continuation state. Those values can be valid on the provider that created them and fail when the same local conversation is replayed through another provider.

Typical symptoms include:

- an old conversation disappears after switching providers;
- the conversation is visible but the next message fails;
- `Expected an ID that begins with 'msg'`;
- `Encrypted content could not be verified/decrypted`;
- `Invalid input[…].content: array too long`;
- returning to Official still sends an old third-party model name;
- every switch replays the whole conversation and fresh input/token usage spikes.

CodexBridge does not replace CC Switch and is not another model aggregator. It adds the missing **Codex session-continuity layer between account-authenticated subscription access and API-provider access**.

## Installation (normal users only need this)

### Windows 10/11: use the installer

For normal Windows users, the recommended path is the GitHub Release asset **`CodexBridge-Setup.exe`**:

1. Open the project's **Releases** page.
2. Download `CodexBridge-Setup.exe`.
3. Double-click it.
4. After setup completes, use CC Switch / Codex normally.

The installer puts CodexBridge under the current user's application-data directory, registers the background watcher and standard uninstall entry, and starts CodexBridge. **No administrator rights and no manual Python installation are required.**

Each release also includes `CodexBridge-Setup.exe.sha256` for verification. The current open-source build is unsigned, so Windows SmartScreen may warn. Verify that the file came from this project's Release and compare its SHA-256 before running it.

### macOS: use the Release package

For macOS, prefer the matching asset from the project **Releases** page:

- Apple Silicon (M1/M2/M3/M4…): `CodexBridge-macOS-AppleSilicon.zip`
- Intel: `CodexBridge-macOS-Intel.zip`

Extract the archive and double-click **`Start CodexBridge.command`**. The first run prepares the user-local runtime and registers the LaunchAgent automatically. Each Release also includes the matching `.sha256` checksum file.

If you do not use GitHub Releases, **Code → Download ZIP** is still supported; extract the repository ZIP and double-click **`Start CodexBridge.command`**.

> [!IMPORTANT]
> macOS Gatekeeper can warn about scripts downloaded from a browser. If a normal double-click is blocked, Finder **right-click → Open** `Start CodexBridge.command` once.

### Windows repository ZIP is still supported

If you do not use GitHub Releases, choose **Code → Download ZIP**, extract it, and double-click **`Start CodexBridge.cmd`**. On the first run it automatically performs the required user-local setup/initialization and starts CodexBridge.

### Actual user path

```text
Windows:
GitHub Release → CodexBridge-Setup.exe → install → use CC Switch / Codex normally
or: Code → Download ZIP → Start CodexBridge.cmd → automatic install/start

macOS:
Download ZIP → Start CodexBridge.command → automatic first-run setup → normal use
```

GitHub Actions builds and smoke-tests `CodexBridge-Setup.exe` on a Windows runner, and Releases publish both the installer and its SHA-256 checksum.

## What happens after installation?

In normal use, you should not need to run PowerShell, edit `config.toml`, manually start the Bridge, or babysit CC Switch restarts.

| Scenario | CodexBridge behavior |
| --- | --- |
| Switch to OpenAI Official | Bridge routes directly to the ChatGPT Codex backend and keeps reusable Official resident state |
| Switch to GLM / DeepSeek / Qwen | Bridge routes through CC Switch on `127.0.0.1:15721` and maintains provider-specific continuation state |
| CC Switch is closed while a third-party route is active | Launcher detects that `:15721` disappeared and relaunches CC Switch instead of silently falling back to Official |
| Codex auth/model state must be refreshed after a switch | Launcher performs the required Codex / CC Switch restart automatically |
| Active provider changes | Codex model picker exposes only the active provider's models |
| Tray `Exit Everything...` | Shows a confirmation warning first; if confirmed, stops Launcher, Bridge, and CC Switch while leaving the lightweight CC Switch trigger watcher armed; does not rewrite `config.toml`, switch to native Official, or restart Codex |
| CC Switch is closed on Official | No action; Official keeps working through the resident Bridge |
| CC Switch is closed on a third-party route | Restores only the `:15721` proxy; provider/model stay unchanged and Codex is not restarted merely for proxy recovery |

## Core capabilities

### 🔁 Cross-provider conversation continuity

CodexBridge keeps a stable:

```toml
model_provider = "custom"
```

Provider switching is represented by Bridge routing and provider-scoped catalogs instead of moving a Codex conversation between unrelated provider buckets.

### 🧠 Provider-specific continuation state

Different providers cannot read each other's internal prompt/KV cache. CodexBridge does not pretend that cache is portable. Instead, it maintains separate continuation state:

> **Correctness-first:** for complex Codex agent/tool workflows, correctness wins over token savings. Since v2.12, third-party durable delta is used only for completion-verified, tool-free, instruction-stable conversations; everything else falls back to a full portable replay.

- **Official**: guarded resident WebSocket continuation;
- **Third-party**: shadow cursors are isolated by Codex's `x-client-request-id` thread identity (hashed) when available, falling back to a conversation fingerprint only on older clients. Durable `previous_response_id` is used only in safe cases; tool-bearing agent tasks do **not** reuse a shadow cursor by default;
- on return to a provider, CodexBridge prefers sending only the conversation delta that provider has not seen when the safety guards pass.

This can reduce full-history replay, but it **cannot force a provider's billing system to report a prompt-cache hit**.

### 🧩 Provider-scoped model picker

When GLM is active, the picker shows GLM-route models. When you return to Official, it shows Official models. CodexBridge may keep learned metadata internally, but it no longer mixes all known providers into the visible model list.

### 🛡️ No history-file rewriting

CodexBridge does not need to directly rewrite:

- `.codex/sessions`;
- Codex SQLite history databases;
- `.codex/auth.json`.

Compatibility handling happens in the routing/continuation layer instead of permanently mutating saved conversation history.

### 🖥️ Install once, then let the launcher manage the lifecycle

The Windows Launcher handles:

- Bridge lifecycle;
- CC Switch proxy supervision;
- provider-switch detection;
- required Codex / CC Switch restarts;
- provider-scoped model catalogs;
- Windows/CC Switch wake-up behavior;
- logs and diagnostics.

### 🗑️ Standard uninstall (Windows)

After installation, choose **Uninstall CodexBridge...** from the tray, uninstall **CodexBridge** from Windows **Settings → Apps → Installed apps**, or run `Uninstall CodexBridge.cmd` from the repository root.

Uninstall stops Bridge / CC Switch, removes Windows startup and the CC Switch watcher, restores the pre-install Codex configuration, and removes the program, runtime, and logs under `%LOCALAPPDATA%\CodexProviderBridge`. Codex chat history is not deleted.

## Architecture

```mermaid
flowchart TD
    C[Codex CLI / IDE] --> P[custom provider]
    P --> B[CodexBridge<br/>127.0.0.1:15722]

    B -->|Official model| O[ChatGPT Codex backend]
    B -->|Third-party model| S[CC Switch<br/>127.0.0.1:15721]
    S --> G[GLM / DeepSeek / Qwen / ...]

    B -. Official resident state .-> OS[(Official state)]
    B -. Provider shadow cursor .-> TS[(Third-party state)]
```

While CodexBridge is active:

```text
Codex
  ↓
model_provider = custom
  ↓
127.0.0.1:15722  CodexBridge
  ├─ Official → ChatGPT Codex backend
  └─ Third-party → 127.0.0.1:15721 → CC Switch → Provider
```

On `Exit Everything...`, CodexBridge stops the tray launcher, Bridge, and CC Switch without rewriting `config.toml` or restarting Codex. The lightweight CC Switch trigger watcher remains armed so opening CC Switch later can relaunch CodexBridge automatically.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the routing/state model.

## Token usage and prompt cache

> [!NOTE]
> **OpenAI's internal prompt cache cannot be read by GLM / DeepSeek / Qwen, and vice versa.**

What CodexBridge can control is whether it needs to resend the full conversation and whether it can reuse a provider's own continuation cursor. It cannot translate one provider's hidden KV/cache state into another provider's format.

Therefore:

- the first visit to a new provider can still require substantial context;
- returning to a provider with reusable state can send only unseen delta;
- actual fresh/cached-token accounting still depends on that provider's backend;
- if a third-party endpoint does not support durable `previous_response_id`, CodexBridge safely falls back to a compatible replay.

## Compatibility

The normal-user target is **Windows 10/11 + macOS Intel + macOS Apple Silicon**. Windows uses `CodexBridge-Setup.exe` from Releases as the recommended install path; macOS uses the architecture-matched Apple Silicon / Intel Release ZIP as the recommended path, with the repository source ZIP retained as a fallback.

| Route / platform | Status | Notes |
| --- | --- | --- |
| Windows 10/11 x64 | ✅ Primary | `CodexBridge-Setup.exe` from Releases; repository `.cmd` remains a fallback/developer path |
| Windows ARM64 | 🟡 Compatibility path | Repository bootstrap can select the ARM64 embeddable Python package; the formal Setup path still needs additional real-device regression |
| macOS Apple Silicon | ✅ Release path | Apple Silicon ZIP from Releases; `.command` + user-local runtime + LaunchAgent watcher |
| macOS Intel | ✅ Release path | Intel ZIP from Releases; same launcher and watcher lifecycle as Apple Silicon |
| OpenAI Official | ✅ Primary tested path | Bridge connects directly to the ChatGPT Codex backend |
| GLM | ✅ Primary tested path | Routed through CC Switch Responses path |
| DeepSeek | 🟡 Used during development | Depends on current CC Switch protocol mapping |
| Qwen / MiniMax | 🟡 Compatibility target | Depends on CC Switch support for the selected provider/protocol |
| Claude / Gemini etc. | 🟡 Conditional | CodexBridge is not a protocol converter |
| Linux / WSL | 🧪 Developer path | Bash manager remains available, but is not the current normal-user one-click path |

> [!NOTE]
> “Any computer” here means no fixed username, drive letter, or install directory within the supported platforms. Normal Windows users download the Release installer; normal macOS users download the architecture-matched Release ZIP. Neither path requires opening Actions or manually installing Python. Enterprise policy, antivirus, SmartScreen/Gatekeeper, network restrictions, broken CC Switch/Codex installs, or future upstream changes can still block execution.

> [!WARNING]
> CodexBridge is **not** a generic Anthropic / Gemini / Chat Completions ↔ Responses protocol converter. Protocol adaptation remains the responsibility of CC Switch or another upstream compatibility layer.

## Project status

Current status: **Beta**.

The project currently focuses on:

- same-conversation Official ↔ third-party switching;
- Official resident continuation across Codex restarts;
- conversation-scoped third-party shadow state;
- provider-scoped model catalogs;
- automatic CC Switch proxy recovery;
- stable `model_provider = custom` identity;
- explicit full shutdown without rewriting Codex routing or restarting Codex;
- `CodexBridge-Setup.exe` one-click Windows installation and Release builds.

Areas that still need continuous regression testing include new Codex/CC Switch versions, additional providers, Realtime/Voice, complex tool items, new reasoning item shapes, and provider-specific durable-continuation behavior.

## FAQ

<details>
<summary><strong>Why keep <code>model_provider = "custom"</code> all the time?</strong></summary>

It gives Codex a stable provider identity. Official / GLM / DeepSeek switching is represented inside the Bridge through routing and model catalogs, reducing history visibility and continuation problems caused by moving the same local conversation between provider buckets.

</details>

<details>
<summary><strong>Do I need to keep the CC Switch window open on third-party routes?</strong></summary>

You do not need to babysit the window. A third-party route still depends on CC Switch's local proxy at `127.0.0.1:15721`. If the proxy disappears because CC Switch is fully closed, the Launcher attempts to restore CC Switch while the third-party route remains active.

</details>

<details>
<summary><strong>Can Official still work after I hide the tray?</strong></summary>

CodexBridge now remains the resident compatibility layer with `model_provider = "custom"` and `custom.base_url = http://127.0.0.1:15722/v1`. Hiding the tray does not hand the session back to native Official and does not stop the Bridge.

</details>

<details>
<summary><strong>Does CodexBridge modify or delete my Codex conversation history?</strong></summary>

It does not directly rewrite `.codex/sessions`, Codex SQLite history, or `.codex/auth.json`. It does modify user-level Codex routing configuration and the manager keeps configuration backups when applying changes.

</details>

<details>
<summary><strong>Why can the first GLM call still be expensive?</strong></summary>

GLM does not inherit OpenAI's internal cache. The optimization target is the return visit: after GLM has established its own continuation state, CodexBridge tries to send only the delta GLM has not seen.

</details>

<details>
<summary><strong>Do normal users need Python?</strong></summary>

The Windows installer does not require users to install Python manually; Release builds bundle the standalone Bridge runtime. The repository-ZIP fallback path still prepares a user-local Python runtime automatically when needed.

</details>

## Logs and troubleshooting

Runtime logs live under:

```text
Windows:
%LOCALAPPDATA%\CodexProviderBridge\launcher.log
%LOCALAPPDATA%\CodexProviderBridge\bridge-stdout.log
%LOCALAPPDATA%\CodexProviderBridge\bridge-stderr.log

macOS:
~/Library/Application Support/CodexProviderBridge/start.log
~/Library/Application Support/CodexProviderBridge/macos-watcher.log
~/.local/state/CodexProviderBridge/bridge-stdout.log
~/.local/state/CodexProviderBridge/bridge-stderr.log
```

When opening an Issue, please include:

- Codex version;
- CC Switch version;
- provider/model;
- the switch sequence, e.g. `Official → GLM → Official`;
- the relevant time range from the three logs above;
- whether Codex or CC Switch restarted during the failure.

Remove personal paths, account names, or anything else you do not want to publish before attaching logs.

### `stream disconnected before completion`

Inspect `bridge-stderr.log` and determine whether the failure is on:

```text
Codex → :15722 Bridge
```

or:

```text
Bridge → :15721 CC Switch → Provider
```

### `10061 connection refused`

If the error points to `127.0.0.1:15722`, Codex still points at the Bridge but the resident Bridge is not listening. Run `Start CodexBridge` again to restore the resident service; if this still happens, attach the Launcher log.

## Source layout / development

Normal Windows users should use `CodexBridge-Setup.exe` from Releases, while normal macOS users should use the architecture-matched Release ZIP. The repository source ZIP remains a fallback. The source layout below is mainly for contributors:

```text
src/
  bridge/       Python bridge core
  launcher/     Windows tray launcher / watcher
  setup/        one-click installer
scripts/
  build/        Windows release build scripts
  windows/      PowerShell manager
  unix/         Bash manager
assets/         icons / packaging assets
docs/           architecture notes
.github/        CI / Release workflow
```

GitHub Actions run Windows/macOS regression and packaging jobs. Normal users only need the matching platform asset from Releases and do not need to open Actions.

See `scripts/build/` for local development builds.

> Maintainer note for Windows: macOS `.command` / `.sh` files must keep their executable bit in Git. Run `scripts/maintainer/PrepareGitHubFromWindows.ps1` once if needed; `.gitattributes` also keeps shell files on LF line endings.

## Security and privacy

- Keep the Bridge bound to `127.0.0.1`; do not expose it on `0.0.0.0` or the public internet.
- Do not publish full logs without reviewing personal paths and provider-related information.
- The project does not migrate history by rewriting saved session files.
- This is an unofficial compatibility layer; keep normal backups of important Codex configuration and project data.
- Report security-sensitive issues according to [SECURITY.md](SECURITY.md); do not paste tokens, API keys, or unredacted logs into public Issues.

## Roadmap

- [x] Continue one conversation across Official ↔ third-party routes
- [x] Official resident continuation
- [x] Conversation-scoped third-party shadow state
- [x] Provider-scoped model picker
- [x] CC Switch proxy supervisor
- [x] Repository-ZIP double-click quick start (Windows + macOS)
- [x] Windows user-local runtime / tray watcher
- [x] macOS user-local runtime / LaunchAgent watcher
- [x] GitHub Actions cross-platform CI
- [ ] Broader provider / Codex-version regression matrix
- [x] Standard Windows uninstall entry (tray / Installed apps / uninstall script)
- [x] Formal Windows `CodexBridge-Setup.exe` Release installer
- [ ] macOS `.dmg` / `.pkg` and a cleaner cross-platform install / update lifecycle
- [ ] Portable handoff / lazy replay for reducing first-visit context cost
- [ ] Upstream CC Switch lifecycle hook / companion integration

## Contributing

Bug reports, compatibility tests, and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide.

For larger changes, open an Issue first and include:

1. the real workflow you are trying to fix;
2. current behavior;
3. expected behavior;
4. Codex / CC Switch / provider versions;
5. whether the change affects existing continuation state or routing.

The main design principle is: **do not damage an existing conversation; prefer a safe fallback when continuation cannot be proven safe.**

## Acknowledgements

- [CC Switch](https://github.com/farion1231/cc-switch) provides provider management and local routing;
- the OpenAI Codex / Responses ecosystem provides the client/session model this project integrates with.

CodexBridge is not officially affiliated with OpenAI, CC Switch, or their maintainers.

## License

[MIT](LICENSE)

---

<div align="center">

If CodexBridge solves a workflow you rely on, a **⭐ Star** helps other people with the same problem discover it.

</div>
