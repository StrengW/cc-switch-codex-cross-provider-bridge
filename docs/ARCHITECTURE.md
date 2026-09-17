# Architecture

## Active mode

```text
Codex
  -> custom provider
  -> http://127.0.0.1:15722/v1 (CodexBridge)
       |-- Official models -> https://chatgpt.com/backend-api/codex
       `-- Third-party models -> http://127.0.0.1:15721 (CC Switch)
```

The custom provider identity stays stable. Provider switching is represented by routing/catalog state rather than changing Codex away from `model_provider = "custom"`.

## Third-party proxy supervision

When the active route is third-party, the launcher checks `127.0.0.1:15721` periodically. If CC Switch is closed or its proxy disappears, CodexBridge relaunches CC Switch and waits for the proxy to become ready. This recovery does not change the selected third-party provider/model and does not restart the Bridge.

The user-facing tray action is **Exit Everything...**. It first shows a confirmation warning. If confirmed, it stops the launcher, Bridge, and CC Switch while deliberately leaving `config.toml` and Codex untouched. The lightweight CC Switch trigger watcher remains armed so a later normal CC Switch launch can relaunch CodexBridge automatically. It never performs native-Official handoff and never restarts Codex during explicit exit.

## Resident compatibility lifecycle

The local Bridge remains the stable compatibility layer at `127.0.0.1:15722`. Official traffic can continue with CC Switch closed. If a third-party route is active and `127.0.0.1:15721` disappears, only the CC Switch proxy is restored; Codex is not restarted unless the actual provider/model route changes.

## Continuation state

Official uses guarded resident WebSocket continuation. Third-party routes use conversation-scoped shadow cursors and durable `previous_response_id` continuation where supported. Provider-specific state is not the same thing as sharing one provider's internal prompt cache with another provider.

### Correctness-first shadow safety (v2.12)

Third-party durable continuation is intentionally narrower than Official resident continuation. A third-party shadow cursor is reused only for completion-verified, tool-free conversations whose system/developer instruction envelope remains semantically stable. If the replay contains tool calls/results, an open tool chain, an unverified/empty completion, a branch/prefix mismatch, or instruction drift, CodexBridge sends the complete current portable replay instead of attaching the saved `previous_response_id`.

This trades some token savings for a stronger invariant: **a saved provider cursor must never override the visible Codex task state**. Tool-heavy agent workflows therefore prefer replay correctness over hidden provider-state reuse.

### Thread identity

For current Codex HTTP Responses requests, CodexBridge prefers the `x-client-request-id` header as the logical thread identity and hashes it before using it in an internal shadow-state key. This prevents two unrelated chats with the same first user prompt from sharing one provider cursor. Older clients without the header use the legacy first-user fingerprint fallback.
