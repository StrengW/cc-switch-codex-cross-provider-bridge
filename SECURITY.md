# Security Policy

CodexBridge is a local compatibility layer that can handle Codex routing, provider credentials passed through upstream tools, and diagnostic logs. Please treat authentication data and logs as sensitive.

## Reporting a vulnerability

Please **do not** publish access tokens, API keys, authentication headers, full private logs, or other secrets in a public GitHub Issue.

For a security-sensitive report, prefer GitHub's private vulnerability reporting feature when it is available for this repository. If private reporting is unavailable, open a public Issue containing only a minimal, redacted description and ask for a private contact path before sharing sensitive reproduction material.

A useful report includes:

- public CodexBridge version from `VERSION` (or the Git tag) and, when possible, the commit;
- operating system and architecture;
- Codex and CC Switch versions;
- affected provider / route;
- minimal reproduction steps;
- sanitized logs with secrets and personal paths removed.

## Local network boundary

The Bridge is designed to listen on loopback (`127.0.0.1`) for its normal local workflow. Do not expose the Bridge or the CC Switch local proxy directly to the public internet.

## Diagnostic logs and automatic redaction

CodexBridge tries to avoid recording chat bodies and provider credentials, and it automatically redacts persistent logs before they are written. The launcher (`launcher.log`, manager stdout/stderr, and exception details) and the bridge (`bridge-stdout.log`, `bridge-stderr.log`) pass diagnostic text through a shared sanitizer that masks:

- `Authorization` / `Proxy-Authorization` headers and `Bearer` / `Basic` credentials;
- key/value and JSON secrets such as `api_key`, `access_token`, `refresh_token`, `session_token`, `id_token`, `secret`, `password`, and `token`;
- `sk-*` API keys, JWT-shaped strings, and `Cookie` / `Set-Cookie` values;
- credentials embedded in URLs (`user:pass@`) and sensitive query parameters (`token`, `key`, `api_key`, `code`, `secret`, `signature`);
- personal paths (`/Users/<name>/` -> `/Users/<user>/`, `C:\Users\<name>\` -> `C:\Users\<user>\`) and email addresses.

Non-secret diagnostic fields are preserved on purpose: timestamps, route, provider/model, HTTP status codes, retry/fallback markers, counters, fingerprints, and port state.

Even with automatic redaction, **treat raw on-disk logs as sensitive**: redaction is best-effort and cannot guarantee that every secret is caught. When you open a public Issue, prefer pasting only the minimal redacted snippet you actually need and remove anything you are unsure about. A packaged, pre-sanitized one-click diagnostic export is planned but not shipped yet; until then, collect the relevant log window manually.

## Windows distribution policy

The normal-user Windows Release asset is `CodexBridge-Windows.zip`. It intentionally contains **no prebuilt `.exe`**. `Start CodexBridge.cmd` prepares the user-local runtime and builds the small tray Launcher locally on the user's machine.

The previous unsigned custom self-extracting Setup EXE / PyInstaller one-file distribution is not part of the normal Release workflow after it triggered a Microsoft Defender ML/heuristic detection during pre-release testing. Users should not disable Defender, turn off real-time protection, or add broad antivirus exclusions to run CodexBridge.

## macOS distribution policy

macOS Release packages are built for Apple Silicon and Intel. When Apple Developer signing/notarization credentials are not configured, the published assets are explicitly named with the `-unsigned` suffix.

An unsigned macOS build may require Finder **Right-click -> Open** on first launch. Users should not disable Gatekeeper globally to run CodexBridge.

If signed/notarized builds are produced later, the release workflow requires hardened-runtime signing and an Apple notarization result of `Accepted` before publishing them as signed assets.

## Release integrity

Release SHA-256 files are provided for integrity verification. A checksum proves that the downloaded bytes match the published artifact; it is not a malware-safety certificate.

Public tags are expected to match the repository `VERSION` file, and CI builds platform artifacts from the tagged source. See [`docs/VERSIONING.md`](docs/VERSIONING.md).

## Scope

Security reports are especially useful for issues involving credential exposure, unintended network exposure, unsafe local-file writes, privilege escalation, supply-chain or release-artifact integrity, unsafe persistence, or routing that sends requests to an unexpected upstream.

CodexBridge is currently Beta and is not an officially supported OpenAI or CC Switch component.
