# Architecture

CodexBridge is a local compatibility layer for keeping one Codex conversation usable while the upstream route changes between OpenAI Official and CC Switch-backed third-party providers.

## 1. Stable Codex-facing identity

```text
Codex
  -> model_provider = "custom"
  -> http://127.0.0.1:15722/v1 (CodexBridge)
       |-- Official route ----> ChatGPT Codex backend
       `-- Third-party route -> http://127.0.0.1:15721 (CC Switch)
                                -> selected provider/model
```

Codex keeps one stable custom-provider identity. Provider switching is represented by CodexBridge route/catalog state rather than repeatedly changing Codex between unrelated provider identities.

The bridge is therefore the stable boundary where provider-specific state can be isolated and translated conservatively.

## 2. Source of truth: visible conversation vs provider-owned state

The central invariant is:

> **The visible Codex conversation is shared task state; provider-owned hidden state is not shared across providers.**

Portable conversation state includes the visible user/assistant timeline and complete portable tool call/output pairs. Provider-owned state can include response/item IDs, encrypted reasoning payloads, hidden continuation state, hosted-tool state, or other adapter-specific metadata.

A state handle created by Provider A is never assumed to be meaningful to Provider B. This rule applies to every provider boundary, including third-party-to-third-party switches such as DeepSeek -> GLM.

## 3. Routing and model catalogs

The bridge keeps provider routing separate from the model name that Codex currently carries in a request.

- Official user-facing/internal models are routed to the Official backend.
- Third-party models are routed through the CC Switch proxy on `127.0.0.1:15721`.
- Stale model names immediately after a route change can be rebound to the selected route where the existing guarded model-rewrite rules allow it.
- Provider-scoped model catalog snapshots keep the Codex picker from exposing stale models from another route.

Model-catalog compatibility metadata such as `comp_hash` is neutralized only where the existing bridge guard requires it; missing hashes are treated as unknown compatibility, not fabricated compatibility.

## 4. Official continuation

Official uses guarded resident Responses WebSocket continuation.

A completed Official conversation can remain attached to its original upstream WebSocket while the Codex client or CC Switch is restarted. A new Codex connection begins on an isolated bootstrap Official socket. It is migrated to an older resident socket only after the incoming full replay proves that it belongs to that resident conversation.

When that proof succeeds, the bridge can convert a restart-generated full replay into:

```text
trusted previous_response_id + provider-unseen delta
```

If the resident socket has expired, the replay does not match, or the upstream rejects the live continuation state, correctness falls back to the complete current replay.

Official `store=false` semantics are preserved; cross-restart reuse relies on the live resident session and stable prompt-cache bucketing rather than pretending a stored Official response exists when it does not.

## 5. Third-party provider-local continuation

Third-party HTTP routes can use conversation-scoped shadow checkpoints when the upstream supports durable response state.

The durable state key is scoped by provider namespace/model and, when available, a privacy-preserving hash of Codex's logical `x-client-request-id`. Older clients fall back to a first-user conversation fingerprint.

A third-party checkpoint is reused only when the bridge can prove that it is safe. In particular, provider-local continuation is rejected when the current/saved state contains conditions such as:

- tool-bearing history;
- an open or unverifiable tool chain;
- an unverified/empty completion;
- a timeline prefix mismatch;
- instruction layout/content drift.

When any guard fails, the bridge sends the complete current portable replay instead of attaching a stale hidden cursor.

If an upstream explicitly rejects `store` / durable continuation, the bridge records that capability as unsupported for the current process and continues with stateless replay instead of repeatedly retrying the same unsupported optimization.

## 6. Portable replay boundary

Cross-provider replay removes state that cannot safely cross provider boundaries while preserving the visible task history.

The portable path can remove or neutralize:

- provider item IDs;
- stale/cross-provider `previous_response_id`;
- opaque `encrypted_content`;
- provider-owned reasoning/compaction/item-reference state when required by the guarded path;
- optional provider/cache hints after an explicit compatibility rejection.

For tool history, complete portable call/output pairs are retained. Dangling calls or outputs can be omitted on the compatibility retry path, but CodexBridge **never fabricates a tool result**.

A portable full replay uses `store=false` so the next provider is not required to resolve server-side state created by the previous provider.

## 7. Compatibility firewall

The compatibility firewall is a **post-rejection fallback**, not unconditional request rewriting.

For HTTP Responses requests, a single provider-neutral stateless retry is allowed only after a 400/422 error matches a conservative cross-provider portability signature, for example an explicit rejection involving:

- invalid provider item IDs;
- unverifiable encrypted content;
- stale `previous_response_id`;
- structured reasoning/item-reference state;
- missing tool call/output counterparts.

Authentication failures, quota/rate-limit failures, model availability failures, and generic upstream errors are not treated as portability errors simply because they use a 400/422 status.

The fallback order is intentionally narrow:

```text
normal request
  -> cache-syntax fallback when explicitly rejected
  -> stale saved previous_response_id fallback when explicitly rejected
  -> durable-store fallback when explicitly rejected
  -> compatibility-firewall portable retry for recognized state errors
  -> otherwise return the real upstream failure
```

This prevents a compatibility mechanism from masking unrelated provider problems.

## 8. Third-party proxy supervision and lifecycle

The local Bridge remains the stable compatibility layer at `127.0.0.1:15722`.

When a third-party route is active, the Launcher observes the CC Switch proxy on `127.0.0.1:15721`. If the proxy disappears, it reports that CC Switch must be opened; it never revives CC Switch on a proxy drop or after the user closes it, and never selects or launches it via system discovery, a remembered path, or a default install path. Codex is restarted only under the already-tested route/model refresh policy, not merely because the proxy was temporarily unavailable.

The single exception is the provable Provider/auth switch repair flow (Windows C# launcher and macOS menu bar launcher). When a third-party route is active, the pinned custom provider has `requires_openai_auth = true`, and `~/.codex/auth.json` carries no live ChatGPT credential, a Codex restart would land on the login screen. On a real provider-switch edge (a route-key change, never a proxy drop), the Launcher binds the currently-running, path-verified CC Switch instance and restarts that same instance once - bounded, one-shot per switch key, and loop-free (the watcher will not relaunch an already-running Launcher, and the supervisor is muted during the expected `:15721` drop) - then asks the user to restart Codex (see **Codex restart behavior** below). The bound executable path comes only from the live process (Windows: the verified process path; macOS: the live CC Switch app from `NSWorkspace.runningApplications`, relaunched by its explicit bundle path); it is never discovered, persisted, or taken from a default location. If no live instance can be bound or the bounded restart fails, the Launcher skips the Codex restart reminder and asks the user to reopen CC Switch instead. CodexBridge never writes `auth.json`; CC Switch re-materializes the credential on its own restart.

Official traffic can continue while CC Switch is closed.

### Codex restart behavior

Every current Codex form is a headless `app-server` backend owned by a GUI host - the VS Code/Cursor extension, or the ChatGPT desktop app. `codex.exe` never owns a top-level window of its own (its `MainWindowHandle` is always 0), which shapes when CodexBridge will and will not cycle the process:

- **Normal route/provider switch (automatic):** CodexBridge **never terminates** the backend. Killing a host-owned backend leaves the host on a "click to restart" page and, because route switches repeat, would keep killing the respawning backend and make that page flicker between the restart, restarting and login states. Instead the host owns its lifecycle: CodexBridge raises a modal alert plus a persistent reminder (Windows tray red badge; macOS menu-bar warning icon, tooltip, and bold menu line) and asks the user to restart Codex so it reloads the new route/credential. The reminder is withdrawn automatically once the Codex process identity actually changes (the user reloaded).
- **Exit CodexBridge handoff (automatic):** the one path that really does cycle the backend - CodexBridge kills it and waits for the host to respawn it against the direct-Official config.
- **Manual "Restart Codex" (macOS tray menu):** an explicit user action that terminates the backend and lets the host recreate it on the next interaction.

There is no "standalone Codex GUI that CodexBridge relaunches". Because `codex.exe` has no window of its own, an earlier auto-relaunch path (remember the GUI executable, kill it, then relaunch that executable) could never fire and has been removed as dead code; the restart decision now keys only on whether an Exit handoff is in progress.

### Exit CodexBridge

The tray action **Exit CodexBridge...**:

- asks for confirmation;
- on Official routes, verifies the direct-Official handoff and restarts Codex before stopping the local Bridge;
- stops the full Launcher, Bridge, and CC Switch functional components;
- leaves the lightweight CC Switch trigger watcher armed so a later normal CC Switch launch can relaunch CodexBridge.

It is not an uninstall operation.

### Uninstall

The Windows uninstaller removes CodexBridge-owned application/runtime/log/startup/watcher state and restores the pre-install Codex configuration when a usable snapshot is available. If a complete snapshot is unavailable, it prepares a safe direct-Official fallback. Saved Codex chat/session history is not deleted.

## 9. Correctness-first design invariants

1. **Never let a stale provider cursor override the visible Codex task state.**
2. **Never reuse provider-private state across a provider/model boundary without proof.**
3. **Never fabricate tool outputs to make a replay look complete.**
4. **Prefer complete portable replay over an unproven continuation optimization.**
5. **Do not rewrite unrelated upstream failures as portability failures.**
6. **Do not directly rewrite saved Codex chat/session history as part of normal compatibility handling.**

These invariants are why CodexBridge can optimize continuation when safe while still retaining a conservative stateless fallback for new or partially compatible providers.

## 10. Compatibility scope

See [`COMPATIBILITY.md`](COMPATIBILITY.md) for regression-tested route families, best-effort providers, and the capability assumptions required for an untested provider to work.

See [`VERSIONING.md`](VERSIONING.md) for the distinction between the public product version and internal component revision markers.
