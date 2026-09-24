# Changelog

CodexBridge follows semantic public release versions from the repository-root `VERSION` file. Internal component revision labels that may appear in diagnostic logs are implementation markers, not public release versions.

## [Unreleased]

### Fixed

- CodexBridge no longer keeps every backup it has ever made. It saves a timestamped copy of `~/.codex/config.toml` beside the original each time it rewrites that file, and until now nothing removed those copies short of a full uninstall, so ordinary provider switching slowly filled a directory that is not ours — 36 files after eight days on one machine. Each kind of backup now keeps its three most recent copies. They are ordered by the timestamp in the filename rather than by modification time, because a backup inherits that time from the config it was copied from and so does not record when the backup was taken. Nothing else in the directory can be selected: matching requires both the Bridge's own filename infix and an exactly formatted timestamp, so the live `config.toml`, CC Switch's files, and anything you put there yourself are all out of reach.
- The Official route no longer fails when CC Switch is closed. Codex normally reaches the Bridge over a WebSocket, and that path has always gone straight to the ChatGPT backend. The plain HTTP fallback did not: it sent Official traffic to CC Switch's proxy on `127.0.0.1:15721`, so with CC Switch closed the one route documented as not needing it returned a 502 — reported as a "CC Switch upstream error", which pointed whoever read the log at the wrong component. HTTP and WebSocket now share a single routing decision, so both go direct on an Official route, and a failure names the upstream that actually failed. Third-party routing is unchanged: it still goes through CC Switch, and a Codex-internal Official model is still never handed to a third-party proxy.
- Two causes behind that failure are fixed with it. `supports_websockets` could stay pinned at `false` on an Official route after a CC Switch config rewrite or one failed write, which is what made Codex choose the HTTP path in the first place; the guard now re-asserts the keys it owns on every pass instead of only when the model catalog changes. And the guard's config reads had no retry while its writes retried eight times, so a `config.toml` briefly held by CC Switch or Codex aborted an entire pass with `Permission denied` and left route-derived keys stale.
- macOS uninstall no longer leaves Codex pointing at a dead local Bridge. When `~/.codex/config.toml` still routes through the Bridge, the uninstaller hands it to the direct Official route first (arming the manager's detach latch), stops the Bridge, and then restores the earliest clean pre-install backup when one exists. Ownership is decided by the fingerprint the manager itself uses — a loopback route inside its managed port range (15722–15921), or the bundled catalog file — so a config that only points at CC Switch's own port, at a third-party provider, or straight at Official is never rewritten. The script reports which outcome actually happened.
- macOS uninstall now removes every artifact family the Bridge writes next to `config.toml` (`config.toml.bridge-direct-official-backup-*` plus the hidden `.*.bridge-tmp-*` / `.*.bridge-direct-official-tmp-*` leftovers of an interrupted write) and strips the CodexBridge-owned `model_catalog_json` / `experimental_bearer_token` references that would point at deleted files, matching what the Windows uninstaller already did. The macOS uninstall dialog now states this outcome, and the macOS uninstall path gained contract-test coverage.
- The Windows Release ZIP now bundles the official python.org embeddable runtime, so a first run on 64-bit Windows needs no internet access at all. This was the single biggest install failure: python.org is routinely unreachable or extremely slow for users in mainland China, and Windows was the only platform whose Release did not already carry its runtime (the macOS ZIP has bundled one since 0.2.1). The archive ships byte-for-byte as published upstream and is verified against the same pinned SHA-256 before anything is extracted, so a user can reproduce that digest against python.org. The rule about our own binaries is unchanged: the package still contains no executable we built and the release check still fails on any `.exe`. What is now allowed through is an upstream publisher's runtime archive, pinned by version, source, and digest — not a self-extracting installer or a frozen one-file bundle. The download path remains the fallback for ARM64 and 32-bit Windows and for a bundled archive that fails verification.
- Building the Windows Release no longer fails at random. A freshly copied multi-megabyte archive is briefly held open by real-time scanning, and `Compress-Archive` errors out on a locked source instead of waiting, so packaging an 11 MB runtime could abort on an otherwise healthy machine — including in CI, where it would only surface on a tagged release. The packager now polls until every staged file is readable and retries the archive step before giving up.
- `StartCodexBridge.ps1` gained a `-PrepareRuntimeOnly` mode (with `-StateRootOverride`) that resolves the runtime, proves it executes, and exits before touching the launcher, autostart, or the Codex config. CI uses it to assert that the offline path really is offline: if a `downloads` directory appears, the run depended on the network and the build fails.
- The Windows runtime download can no longer hang forever. When a download is needed it had no request timeout: Windows PowerShell then waits indefinitely, so on a network where python.org is filtered the script sat on "Preparing private Python runtime (first run only)..." and never printed an error. Every source now gets a 60-second timeout, and a failed source is reported instead of stalling the install.
- The same download now falls back to the Huawei Cloud and npmmirror mirrors when python.org is unreachable or too slow, which is the common case for users in mainland China. Because a mirror is a third party, every download is verified against a SHA-256 pinned in the script and rejected on mismatch (the bad file is deleted, not installed); all three sources were confirmed to serve byte-identical official builds. A runtime package with no pinned digest is refused outright, so a future Python version bump cannot silently ship unverified. The bundled archive and a downloaded one clear the same check through the same code path.
- When the runtime still cannot be prepared, the failure is now stated in the user's own language (Simplified Chinese, Traditional Chinese, or English, detected the same way the uninstaller detects it) and says what to do next, instead of a single English line telling the user to consult a README that did not cover the case. The per-source failure reasons are written to `%LOCALAPPDATA%\CodexProviderBridge\bootstrap.log` so a report can carry them.
- README and README.en now state plainly that a normal first run needs no internet access, when a download does happen instead, which mirrors it tries, where the log is, and that installing Python 3.10+ yourself is an alternative.

## [0.2.1] - 2026-09-23

### Fixed

- Fixed the root cause behind macOS users seeing "CodexBridge.app is damaged and can't be opened. You should move it to the Trash." An unsigned bundle whose inner executable still carries a signature is judged as damaged by Gatekeeper, and that dialog has no user escape (not even Open Anyway), so the documented right-click/Open-Anyway steps could never work for it. The macOS Release build now ad-hoc signs the app bundle in the unsigned path and proves it with `codesign --verify --deep --strict`; the staged bundle is copied with `ditto` (Apple's recommended bundle copy) instead of `cp -R`, and the archive check re-verifies the signature after unpacking.
- `Start CodexBridge.command` now installs the app bundle with `ditto` and gives the installed copy a local ad-hoc signature whenever it does not already verify (a bundle that verifies, including future Developer ID-signed builds, is left untouched), so an older or damaged download is repaired on the spot instead of failing with "damaged". The failure diagnostics now also report a missing or invalid bundle signature.
- The macOS startup failure dialog now follows the system language (`AppleLocale`): Chinese systems get Chinese dialog and terminal guidance, English systems keep the English texts, and both stay version-aware (Sequoia+ -> System Settings > Privacy & Security > Open Anyway; macOS 14 and earlier -> right-click -> Open). The dialog gained an explicitly consented repair button ("帮我修复" / "Repair") that touches CodexBridge.app only (local re-sign plus removing that app's quarantine flag); without that click nothing is stripped, and system security settings are never changed.
- Fixed the macOS Bridge becoming permanently unstartable after the extracted download folder was deleted. Setup linked the private Python runtime into the extracted ZIP folder, so cleaning up the download broke the runtime and the Bridge could only fall back to an older system Python it refuses to run. `Start CodexBridge.command` now publishes the bundled runtime into the state directory (`Application Support/CodexProviderBridge/runtime/python`) with `ditto` and points the shim there; existing installs migrate on the next script run, and the download folder is disposable afterwards.
- The macOS manager now falls back to that private state-directory runtime when the shim is missing or stale, instead of dropping straight to a system Python.
- The macOS "Could not start the Bridge" dialog is no longer a dead end: it now shows the manager's actual failure reason (`Error: ...` from stderr), records it in `launcher.log`, and offers Retry and Open Bridge Log (a failed restart gets the same treatment).

### Docs

- Rewrote the macOS warning banner and the macOS sections of both READMEs into a short problem/answer format: what the dialog means, which approval step matches your system version, and what to do when it still fails.

## [0.2.0] - 2026-09-23

### Fixed

- Made the macOS Gatekeeper guidance version-aware in `Start CodexBridge.command`. macOS 15 Sequoia removed the Right-click -> Open bypass for unsigned apps, so when the menu bar app is blocked the startup script now detects the running macOS version and shows the matching steps: on Sequoia and later, System Settings -> Privacy & Security -> Open Anyway; on macOS 14 and earlier, the previous right-click -> Open guidance. The script still never strips the quarantine flag, disables Gatekeeper, or escalates.

### Docs

- Moved the macOS unsigned/Gatekeeper warning to the top of both READMEs and made it prominent, since many users are on macOS. Documented that macOS 15 Sequoia removed the Right-click -> Open bypass (use System Settings -> Privacy & Security -> Open Anyway) while macOS 14 and earlier still use Right-click -> Open, and reworded the CC Switch / CodexBridge takeaway for clarity.

## [0.1.8] - 2026-09-23

### Changed

- Narrowed the CC Switch lifecycle rule. CodexBridge still never revives CC Switch on a proxy drop or after the user closes it, and never selects or launches it via system discovery, a remembered path, or a default install path. The single exception: on a real provider-switch edge onto an active third-party route (Windows and macOS launchers), it performs one controlled, bounded, loop-free restart of the already-bound live CC Switch instance so it re-materializes a consistent credential. The bound executable path comes only from the running process (Windows: verified process path; macOS: the live CC Switch app from `NSWorkspace.runningApplications`, relaunched by explicit bundle path) and is never persisted. CodexBridge never writes `auth.json`.

### Fixed

- Stopped a Codex restart storm on Windows. When the route key oscillated (e.g. `official` ↔ `third-party` while CC Switch and the Bridge settled a handoff), every oscillation edge restarted Codex, which could get stuck restarting endlessly. Route-triggered Codex restarts are now rate limited (a minimum interval), and after repeated flaps a circuit breaker pauses all route-triggered restarts — including the CC Switch repair — until the route has stayed stable, then re-arms automatically. macOS mirrors the same flap circuit breaker around its repair restart.
- Fixed CC Switch not restarting on a provider switch, and the infinite CC Switch restart loop it could fall into. Two runtime-proven defects. (1) Wrong edge signal: the switch edge was keyed on the sidecar's `source_path`, but CC Switch writes every provider into one shared `cc-switch-model-catalog.json`, so `source_path` never changed and a third-party → third-party switch produced no edge at all — only Codex reloaded while CC Switch stayed unrepaired, dropping Codex to the login screen. The edge is now keyed on `route_model`, which a new route-snapshot diagnostic confirmed is the field that actually changes per provider (Official `gpt-*` → third-party `glm-*`/`deepseek-*`). (2) Unbounded failure retry: when the bounded CC Switch repair failed (its proxy `:15721` did not come back), the edge was deferred to reconciliation, which re-fired the same edge, re-armed the one-shot latch, and killed/relaunched CC Switch forever. A failed repair is now terminal for that edge — it notifies once, then waits for the next genuine switch — so it can never loop. The repair also force-stops CC Switch directly (a Tauri app that ignores a graceful window close, which only wasted the restart budget), waits for the process tree and `:15721` to release, then relaunches and waits for the proxy to return, logging whether the relaunched process stays alive. (Windows and macOS.)
- Fixed a rate-limited provider switch being silently dropped. When a switch's Codex restart (or CC Switch repair) was suppressed by the restart cooldown or an open flap circuit, the switch edge had already been consumed, so nothing re-applied it: Codex could stay on a stale config and CC Switch stay unrepaired, surfacing later as a login screen. Suppressed switches are now remembered and reconciled once the route settles and the guard clears (Windows and macOS), so sequences like Official (with no Codex restart) followed by several third-party switches always end in the correct repaired/restarted state.
- Fixed a Codex restart-page flicker in editor-hosted Codex (VS Code/Cursor). Such a backend has no GUI window; terminating it left the editor on a "click to restart" page and, because route switches repeat, CodexBridge kept killing the respawning backend, so the page flickered between the restart, restarting and login states. CodexBridge now never terminates an editor-hosted backend during a route switch: on Windows it asks the user to restart Codex in their editor, and on macOS the repair asks the user to reload Codex instead of restarting it. The Exit handoff still cycles the process, so that path is unchanged.
- Removed dead Windows code that claimed to auto-relaunch a standalone Codex GUI. Every current Codex form is a headless `app-server` backend owned by a GUI host (the VS Code/Cursor extension or the ChatGPT desktop app), so `codex.exe` never has a window of its own and its `MainWindowHandle` is always 0. The restart path nevertheless branched on a `hadGui` check and, when true, killed the process and relaunched a remembered GUI executable - but that branch was unreachable (runtime evidence: `Codex GUI relaunched` was logged 0 times while `editor-hosted backend` was logged 26 times), so no Codex was ever auto-restarted this way. The dead branch, its `RememberLaunchTargets`/`codex_gui_exe` state, and the misleading GUI-vs-editor-hosted distinction are gone; the decision now keys only on whether an Exit handoff is in progress (normal switch = remind the user; Exit = cycle the backend and let the host respawn it). Runtime behavior is unchanged because the reminder path was already the only one that ever executed. `docs/ARCHITECTURE.md` gains a **Codex restart behavior** section describing the real contract.
- Made the "restart Codex" reminder impossible to miss (Windows and macOS). An editor-hosted Codex is never terminated, so a provider switch only takes effect after the user reloads Codex -- and the only reminder was a tray balloon, which Windows shows for a few seconds and never keeps in the notification center (runtime evidence: the toast was delivered and cleared about seven seconds later, leaving no trace). Both launchers now raise a modal alert on every switch edge and keep a persistent reminder -- a red badge on the Windows tray icon, a warning icon in the macOS menu bar, plus a tooltip and a bold menu line -- until the Codex process identity actually changes (the user reloaded Codex), after which it is withdrawn automatically. The alert never stacks while one is already waiting, and returns on the next switch if Codex was never reloaded. On Windows the reminder surfaced two launcher defects: (1) the switch handler runs on the thread pool, and the tray menu could not act as the UI dispatcher (its handle is created lazily, and ToolStrip.InvokeRequired then reports FALSE on worker threads), so the modal dialog was created on a pool thread with no UI message pump and no foreground rights and appeared behind the maximized editor; a dedicated dispatcher control is now created on the UI thread and every UI callback goes through it. (2) An ownerless MessageBox is an ordinary top-level window that the Windows foreground lock prevents a background process from activating, so the alert is now a topmost window whose Z order is re-asserted after it is shown and once a second while it waits (without stealing focus). macOS parity extends to the official edge as well: on Windows an official switch already asks for a reload, while on macOS nothing used to run for official routes.
- Windows CC Switch watcher now baselines the current process state at login, so an already-running CC Switch is not mistaken for a new launch that opens the full tray Launcher.
- The Windows source quick-start updater now waits for old installed and bootstrap Launcher roles to exit before copying and relaunching the updated runtime.
- Fixed provider-switch detection silently dying on Windows. CC Switch now persists a Codex config template that already points at the bridge, so switching providers rewrites `config.toml` with `model_provider` and `base_url` unchanged and only swaps the selected model plus the catalog reference. The bridge guard watched for the old transient (an explicit CC-Switch-pointing provider block) and therefore stopped noticing real switches: the route sidecar froze, CodexBridge never restarted CC Switch, and no restart reminder appeared. The guard now re-infers the upstream route whenever the selected model is not offered by the current route's published model catalog, because a real in-picker change always stays inside that catalog. Runtime evidence: 40ms sampling of live switches showed every rewrite reconciled about 300ms later while the route sidecar stayed frozen. macOS uses the same bridge source and is fixed by the same change.

## [0.1.7] - 2026-09-21

### Lifecycle

- Windows login now starts only the CC Switch watcher; legacy full-Launcher `--autostart` registrations migrate automatically.
- Third-party proxy supervision is observation-only: CodexBridge no longer launches, restarts, or kills CC Switch automatically.
- `Exit CodexBridge` now performs bounded Bridge/CC Switch shutdown, Official direct handoff verification, and retains the watcher for the next user-launched CC Switch.
- macOS login now keeps only the watcher LaunchAgent; the watcher opens the full app on a CC Switch start edge and never starts or restarts CC Switch.

### Packaging

- Release metadata, Windows Installed Apps `DisplayVersion`, and platform packages now align on public version `0.1.7`.

## [0.1.6] - 2026-09-20

### Fixed

- The Windows update check now enables TLS 1.2 before contacting GitHub. The launcher is compiled without an `app.config`, so the runtime treated it as a .NET 4.0 application whose default `ServicePointManager.SecurityProtocol` was `Ssl3, Tls` only; GitHub requires TLS 1.2, so "Check for Updates..." failed with `SecureChannelFailure` ("could not create SSL/TLS secure channel").
- Added a regression contract that fails if the TLS 1.2 opt-in is removed or moved after the request is created.
- Update check outcomes (available, already up to date, failed) are now written to `launcher.log` so failures can be diagnosed without a debug build.
- Added a fallback update check through the public `releases/latest` redirect when the GitHub REST API is blocked or rate-limited; the redirect path does not consume the unauthenticated API quota.
- The manual "could not check for updates" message now states that a proxy or firewall blocking `api.github.com` is the usual cause.

## [0.1.5] - 2026-09-20

### Fixed

- CC Switch detection no longer uses window titles. A browser, editor, or chat window whose title contained "CC Switch" could previously be matched, killed, and remembered as the CC Switch executable, which restarted the wrong application and left the real CC Switch stopped.
- The remembered CC Switch executable path is now validated before it is used or stored. Non-CC-Switch paths are discarded and re-discovered instead of being relaunched.
- Added portable CC Switch install discovery for fixed drives (for example `D:\CCSwitch\cc-switch.exe`) and Start Menu shortcut target resolution as a relaunch fallback.
- Added regression contracts covering title-free detection, path validation, and shortcut fallback.

## [0.1.4] - 2026-09-20

### Added

- Added daily background checks for the latest GitHub Release on Windows and macOS.
- Added localized update prompts with a direct link to the Release page; updates are never downloaded or installed automatically.
- Added Windows tray/menu/balloon localization based on the system UI culture, including simplified and traditional Chinese.
- Added macOS menu bar and prompt language fallback based on the system language and preferred languages.

### Packaging

- Included the Windows launcher localization and update-check source files in the source-bootstrap Release ZIP.

## [0.1.3] - 2026-09-19

### Added

- Added a native AppKit macOS Menu Bar launcher with status, route, restart, log, full-exit, uninstall, and launcher-at-login controls.
- Added an independent macOS launcher LaunchAgent while preserving the existing watcher LaunchAgent and portable Python Bridge runtime.
- Added architecture-matched arm64 and x86_64 macOS app bundle construction, archive verification, optional Developer ID signing, and unsigned release labeling.
- Added macOS launcher portability contracts and preserved the existing Start CodexBridge.command bootstrap path.

## [0.1.2] - 2026-09-19

### Fixed

- Strengthened third-party tool-history compatibility repair with pair completeness plus adjacency/order validation.
- Restricted strict tool-adjacency repair to the existing HTTP 400/422 compatibility retry path.
- Added conversation- and route-scoped capability learning so successful strict repair can be reused without affecting unrelated Codex conversations.
- Added capability invalidation when a learned strict preflight is rejected upstream.
- Added regression coverage for non-adjacent tool pairs, output-before-call ordering, preflight reuse, and conversation/route isolation.

## [0.1.1] - 2026-09-18

### Changed

- Aligned README, architecture, compatibility, security, contribution, and release documentation with the current runtime design.
- Added a single public product-version source in `VERSION` and aligned the Windows Installed Apps `DisplayVersion` metadata with it.
- Added release/version consistency checks so a tag must match `v<contents of VERSION>`.
- Added Windows CI coverage for pushes to `main` so the README CI badge reflects current main-branch validation.
- Included version/release documentation in platform release packages.
- Added a project overview that explains the design in interview-ready language.

### Runtime behavior

- **No provider conversion, continuation, compatibility-firewall, routing, watcher, or lifecycle logic is changed in this release-alignment work.**

## [0.1.0] - 2026-09-18

- First public Beta release.
- Windows source-bootstrap Release ZIP with no prebuilt executable.
- macOS Apple Silicon and Intel portable Release ZIPs, published as clearly labeled unsigned artifacts when Apple signing/notarization credentials are unavailable.
- Cross-provider Codex conversation continuity for the tested OpenAI Official, GLM, DeepSeek, and Qwen workflows.
