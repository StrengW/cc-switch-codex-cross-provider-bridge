# Changelog

CodexBridge follows semantic public release versions from the repository-root `VERSION` file. Internal component revision labels that may appear in diagnostic logs are implementation markers, not public release versions.

## [Unreleased]

### Changed

- Narrowed the CC Switch lifecycle rule. CodexBridge still never revives CC Switch on a proxy drop or after the user closes it, and never selects or launches it via system discovery, a remembered path, or a default install path. The single exception: on a real provider-switch edge onto an active third-party route (Windows and macOS launchers), it performs one controlled, bounded, loop-free restart of the already-bound live CC Switch instance so it re-materializes a consistent credential. The bound executable path comes only from the running process (Windows: verified process path; macOS: the live CC Switch app from `NSWorkspace.runningApplications`, relaunched by explicit bundle path) and is never persisted. CodexBridge never writes `auth.json`.

### Fixed

- Stopped a Codex restart storm on Windows. When the route key oscillated (e.g. `official` ↔ `third-party` while CC Switch and the Bridge settled a handoff), every oscillation edge restarted Codex, which could get stuck restarting endlessly. Route-triggered Codex restarts are now rate limited (a minimum interval), and after repeated flaps a circuit breaker pauses all route-triggered restarts — including the CC Switch repair — until the route has stayed stable, then re-arms automatically. macOS mirrors the same flap circuit breaker around its repair restart.
- Fixed CC Switch not restarting on a provider switch, and the infinite CC Switch restart loop it could fall into. Two runtime-proven defects. (1) Wrong edge signal: the switch edge was keyed on the sidecar's `source_path`, but CC Switch writes every provider into one shared `cc-switch-model-catalog.json`, so `source_path` never changed and a third-party → third-party switch produced no edge at all — only Codex reloaded while CC Switch stayed unrepaired, dropping Codex to the login screen. The edge is now keyed on `route_model`, which a new route-snapshot diagnostic confirmed is the field that actually changes per provider (Official `gpt-*` → third-party `glm-*`/`deepseek-*`). (2) Unbounded failure retry: when the bounded CC Switch repair failed (its proxy `:15721` did not come back), the edge was deferred to reconciliation, which re-fired the same edge, re-armed the one-shot latch, and killed/relaunched CC Switch forever. A failed repair is now terminal for that edge — it notifies once, then waits for the next genuine switch — so it can never loop. The repair also force-stops CC Switch directly (a Tauri app that ignores a graceful window close, which only wasted the restart budget), waits for the process tree and `:15721` to release, then relaunches and waits for the proxy to return, logging whether the relaunched process stays alive. (Windows and macOS.)
- Fixed a rate-limited provider switch being silently dropped. When a switch's Codex restart (or CC Switch repair) was suppressed by the restart cooldown or an open flap circuit, the switch edge had already been consumed, so nothing re-applied it: Codex could stay on a stale config and CC Switch stay unrepaired, surfacing later as a login screen. Suppressed switches are now remembered and reconciled once the route settles and the guard clears (Windows and macOS), so sequences like Official (with no Codex restart) followed by several third-party switches always end in the correct repaired/restarted state.
- Fixed a Codex restart-page flicker in editor-hosted Codex (VS Code/Cursor). Such a backend has no GUI window; terminating it left the editor on a "click to restart" page and, because route switches repeat, CodexBridge kept killing the respawning backend, so the page flickered between the restart, restarting and login states. CodexBridge now never terminates an editor-hosted backend during a route switch: on Windows it asks the user to restart Codex in their editor, and on macOS the repair asks the user to reload Codex instead of restarting it. The Exit handoff still cycles the process, so that path is unchanged.
- Windows CC Switch watcher now baselines the current process state at login, so an already-running CC Switch is not mistaken for a new launch that opens the full tray Launcher.
- The Windows source quick-start updater now waits for old installed and bootstrap Launcher roles to exit before copying and relaunching the updated runtime.

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
