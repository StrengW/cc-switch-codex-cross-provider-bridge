<div align="center">

# CodexBridge

**Switch providers, not conversations.**  
Move between **OpenAI Official**, **DeepSeek**, **GLM**, and **Qwen** in Codex while keeping the same conversation usable whenever possible.

[Download](../../releases) · [简体中文](README.md) · [How it works](docs/ARCHITECTURE.md)

[![Windows CI](../../actions/workflows/build-windows-release.yml/badge.svg)](../../actions/workflows/build-windows-release.yml)
[![macOS CI](../../actions/workflows/build-macos-release.yml/badge.svg)](../../actions/workflows/build-macos-release.yml)
[![Releases](https://img.shields.io/badge/Releases-download-blue)](../../releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-Beta-orange.svg)](#compatibility)

</div>

> CodexBridge is an **unofficial CC Switch companion**. It is not an official OpenAI or CC Switch component.

## 30-second overview

If you use **Codex + CC Switch**, you may have seen this: a conversation is still visible after switching providers, but the next message fails; tool/reasoning history is rejected by the new provider; or switching back to Official still carries stale third-party state.

CodexBridge sits between Codex and those providers:

```text
OpenAI Official
      ↓
DeepSeek
      ↓
GLM
      ↓
Qwen
      ↓
OpenAI Official

✅ Keep using the same Codex conversation whenever possible
```

It is not a model aggregator and does not replace CC Switch. Its job is **session continuity across account-authenticated Official access and API-provider access**.

## Quick start

### Easiest path: download a ZIP

If you just want to use it, you do not need to clone the repository or install Python manually.

**Option A: repository ZIP**

```text
Code → Download ZIP → extract
```

Then double-click:

```text
Windows → Start CodexBridge.cmd
macOS   → Start CodexBridge.command
```

**Option B: Windows 10/11: use the Release ZIP**

Download from [Releases](../../releases):

```text
CodexBridge-Windows.zip
```

Extract it, then double-click:

```text
Start CodexBridge.cmd
```

First run prepares a user-local runtime and finishes setup automatically. **No administrator privileges and no manual Python installation are required.**

> The Windows Release **does not distribute a prebuilt `CodexBridge-Setup.exe`**. Do not disable Defender, disable real-time protection, or broadly whitelist the install directory just to run CodexBridge.

### macOS

macOS is currently **Beta**. Apple Silicon and Intel builds are both CI-validated. Unsigned builds may trigger Gatekeeper on first launch; if needed, use Finder **Right-click → Open** once on `Start CodexBridge.command`.

Planned signed release asset names are:

```text
CodexBridge-macOS-AppleSilicon.zip
CodexBridge-macOS-Intel.zip
```

## What it does

- **Keeps one conversation usable** across Official ↔ DeepSeek / GLM / Qwen switches whenever possible.
- **Handles tool/reasoning incompatibilities** with a safe fallback instead of immediately breaking the conversation.
- **Automates switching work** such as routing, provider-scoped model lists, and required Codex / CC Switch restarts.
- **Does not rewrite saved chat history** in `.codex/sessions`, Codex SQLite history, or `.codex/auth.json`.
- **Runs in the background after setup**, so normal use does not require manual `config.toml` edits or starting the Bridge by hand.

### Before / After

| Scenario | Without CodexBridge | With CodexBridge |
| --- | --- | --- |
| Official → DeepSeek | Existing conversation may fail | Compatibility fallback |
| DeepSeek → GLM | Tool/reasoning state may conflict | Conservative conversion |
| Back to Official | Third-party state may leak through | Returns to Official routing |
| Daily use | Manual edits / restarts may be needed | Mostly automatic |

If CodexBridge solves a workflow you rely on, a **⭐ Star** helps other people with the same problem discover it.

## Compatibility

| Route / platform | Status |
| --- | --- |
| Windows 10/11 x64 | ✅ Primary path |
| macOS Apple Silicon / Intel | 🧪 Beta / CI-validated |
| OpenAI Official | ✅ Regression-tested |
| GLM | ✅ Regression-tested |
| DeepSeek | ✅ Regression-tested |
| Qwen | ✅ Regression-tested |
| MiniMax / Claude / Gemini etc. | 🟡 Best effort; depends on whether CC Switch / the upstream exposes the Responses semantics Codex needs |
| Linux / WSL | 🧪 Developer path |

> “Regression-tested” means the current tested combination passed. It is not a promise that every future Codex, CC Switch, or provider version will behave identically.

## How it works

```mermaid
flowchart LR
    C[Codex] --> B[CodexBridge\n127.0.0.1:15722]
    B -->|Official| O[ChatGPT Codex backend]
    B -->|Third-party| S[CC Switch\n127.0.0.1:15721]
    S --> P[DeepSeek / GLM / Qwen / ...]
```

CodexBridge keeps a stable `custom` provider identity and handles cross-provider IDs, tool state, reasoning state, and continuation compatibility in the request path.

For the full state model, resident continuation, shadow state, and compatibility firewall design, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## FAQ

<details>
<summary><strong>Does CodexBridge modify or delete my Codex history?</strong></summary>

It does not directly rewrite `.codex/sessions`, Codex SQLite history, or `.codex/auth.json`. It does update user-level Codex routing configuration and keeps backups when needed.

</details>

<details>
<summary><strong>Does CC Switch have to stay open?</strong></summary>

Official routing does not depend on CC Switch. Third-party routing uses CC Switch's local proxy; if that proxy disappears while a third-party route is active, the Launcher attempts to restore it.

</details>

<details>
<summary><strong>Do normal users need Python?</strong></summary>

No manual Python installation is required. First run prepares a user-local runtime automatically.

</details>

<details>
<summary><strong>Why not promise that every provider will always work?</strong></summary>

Providers differ in Responses, tool calls, reasoning, streaming, and continuation behavior. The goal is: continue when compatible, fall back safely when possible, and fail clearly without contaminating the saved conversation when the upstream still cannot support the request.

</details>

## Troubleshooting

Windows logs are under:

```text
%LOCALAPPDATA%\CodexProviderBridge\launcher.log
%LOCALAPPDATA%\CodexProviderBridge\bridge-stdout.log
%LOCALAPPDATA%\CodexProviderBridge\bridge-stderr.log
```

When opening an Issue, include your Codex version, CC Switch version, provider/model, switch sequence (for example `Official → DeepSeek → Official`), and the relevant log window. Remove personal information before posting logs.

## Security and privacy

- The Bridge binds to `127.0.0.1` by default; do not expose it to the public internet.
- Do not post tokens, API keys, or unredacted logs in public Issues.
- The Windows Release ZIP does not require disabling Defender or adding broad antivirus exclusions.
- SHA-256 verifies download integrity; it is not a security certification.
- Report security-sensitive issues according to [SECURITY.md](SECURITY.md).

## Development and contributing

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)

Bug reports, compatibility tests, and PRs are welcome.

## Acknowledgements

- [CC Switch](https://github.com/farion1231/cc-switch) provides provider management and local routing.
- The OpenAI Codex / Responses ecosystem provides the client/session model this project integrates with.

CodexBridge is not officially affiliated with OpenAI, CC Switch, or their maintainers.

## License

[MIT](LICENSE)

---

<div align="center">

**If CodexBridge helps your workflow, consider giving the project a ⭐ Star.**

</div>
