# Compatibility

CodexBridge is designed around **capabilities and portable conversation state**, not around hard-coded branches for individual model names. That lets untested Responses-compatible providers attempt the same conservative fallback path, while only providers that have actually been exercised are described as regression-tested.

## Current regression-tested routes

| Route / family | Status | Notes |
| --- | --- | --- |
| OpenAI Official | Regression-tested | Uses the Official resident WebSocket continuation path where safe. |
| GLM | Regression-tested | Third-party route through CC Switch. |
| DeepSeek | Regression-tested | Third-party route through CC Switch; compatibility-firewall/tool-history cases are covered by regression tests. |
| Qwen | Regression-tested | Third-party route through CC Switch. |
| Other CC Switch providers | Best effort | Depends on the upstream's Responses/tool/reasoning/streaming semantics. |

“Regression-tested” means the current project test/workflow combination has been exercised for that route family. It is not a promise that every upstream model/version will always behave identically.

## What actually determines compatibility

A new provider has the best chance of working when it can:

- receive Codex-style Responses requests through CC Switch;
- accept the portable `input` timeline used for full replay;
- represent normal user/assistant messages consistently;
- accept complete tool call/output pairs when tools are used;
- stream or return a normal Responses-compatible result.

Durable `previous_response_id` / `store=true` support is an optimization, **not a requirement**. If the provider rejects durable continuation, CodexBridge can mark that provider state as unsupported for the running process and fall back to a complete portable replay.

## Provider state is isolated

CodexBridge treats the visible Codex conversation as the common source of truth, while provider-owned hidden state stays provider/model-local.

Therefore all cross-provider transitions need a portability boundary, including:

```text
Official -> DeepSeek
DeepSeek -> Official
DeepSeek -> GLM
GLM -> Qwen
```

A response ID, encrypted reasoning state, item ID, or hidden tool state created by Provider A is never assumed to be valid for Provider B.

## Conservative fallback order

For a third-party request, the bridge prefers correctness over token savings:

1. reuse provider-local continuation only when the saved checkpoint is proven safe;
2. otherwise send the complete current portable replay;
3. if the upstream returns a recognized 400/422 cross-provider state incompatibility, activate the compatibility firewall once;
4. remove provider-owned opaque state and dangling tool records without fabricating tool outputs;
5. retry one provider-neutral stateless replay;
6. if that still fails, surface the upstream failure instead of mutating the stored Codex conversation.

## Testing a new provider

When reporting a new provider/model, include:

- provider and model name;
- Codex and CC Switch versions;
- switch sequence, for example `Official -> Provider X -> Official`;
- whether the conversation contains tool calls;
- sanitized logs around the first failure.

Do not include API keys, tokens, authentication headers, or private conversation content.
