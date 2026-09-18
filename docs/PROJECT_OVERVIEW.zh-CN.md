# CodexBridge 项目讲解（通俗版 / 面试版）

这份文档用于快速理解项目设计，也可以直接作为面试时组织回答的参考。

## 30 秒怎么说

> CodexBridge 解决的是 Codex 在 OpenAI Official 和 CC Switch 第三方 Provider 之间切换后，旧会话虽然还在，但因为不同 Provider 的 response id、reasoning、tool state 等私有状态不兼容，导致旧会话不能继续的问题。我的做法是让 Codex 始终只看到一个稳定的 `custom` provider 和本地 Bridge，再由 Bridge 决定请求走 Official 还是 CC Switch。可见的 Codex 对话历史作为共同事实，Provider 私有状态彼此隔离；能安全续接就用 continuation + delta，不能证明安全就退回完整 portable replay，遇到典型跨 Provider 400/422 再触发一次兼容性清洗重试。

## 2 分钟怎么说

### 1. 问题是什么

Codex 会把一条会话里的 Responses 状态继续带到后续请求中。OpenAI Official、DeepSeek、GLM、Qwen 等上游虽然都可能提供类似 Responses 的接口，但它们并不共享同一套服务端状态。

例如一条历史里可能包含：

```text
previous_response_id
provider item id
encrypted reasoning state
tool call / tool output state
model-specific metadata
```

这些内容由上一个 Provider 创建，切到另一个 Provider 后不能直接假设仍然有效。

### 2. 为什么统一成 custom

我不让 Codex 在“官方 provider / 第三方 provider”之间反复改身份，而是始终保持：

```text
Codex
  -> model_provider = custom
  -> 127.0.0.1:15722 (CodexBridge)
```

这样 Codex 面前的入口稳定，真正的路由变化被收敛到 Bridge 内部：

```text
Official      -> ChatGPT Codex backend
Third-party   -> CC Switch :15721 -> 实际第三方 Provider
```

这样做的价值是把“Provider 切换”和“Codex 会话身份”解耦。

### 3. 对话历史和 Provider 状态怎么处理

核心原则可以用一句话概括：

> **Codex history 是共享事实，Provider hidden state 不共享。**

也就是说，用户看到的 user/assistant/tool 历史属于当前 Codex 对话；而某个 Provider 生成的 response id、encrypted state、reasoning/item state 只属于那个 Provider。

所以不仅 Official <-> 第三方要转换，第三方 <-> 第三方也必须经过同一个 portability boundary。

### 4. Official 怎么续接

Official 路径优先保留一个受保护的 resident Responses WebSocket。Codex 因切换/鉴权刷新而重启后，可能重新发来完整历史。Bridge 会先用这份历史验证它是否确实属于之前那个 Official 会话。

如果匹配安全，就把“完整 replay”转换成：

```text
previous_response_id + Official 尚未见过的 delta
```

如果匹配不可靠，就退回完整 replay，而不是为了省 token 强行续接。

### 5. 第三方怎么续接

第三方是 provider/model/conversation scoped 的 shadow state。只有保存的 checkpoint 足够可靠时，才会复用 `previous_response_id`。

例如以下情况会主动放弃 shadow cursor：

- tool-bearing history；
- tool chain 没闭合；
- completion 没有验证；
- instruction 发生变化；
- timeline prefix 对不上。

这时直接发送完整 portable replay。

### 6. portable replay 是什么

portable replay 不是“删掉聊天历史”，而是把不能跨 Provider 携带的私有状态剥离掉，保留当前任务真正需要的可移植历史。

典型处理包括：

- 去掉 provider item id；
- 去掉 stale `previous_response_id`；
- 去掉 opaque `encrypted_content`；
- 不把 Provider A 的隐藏 reasoning/item state 当成 Provider B 的状态；
- 对 tool history 只保留完整 call/output 对，孤立的一边会被丢弃；
- **绝不伪造 tool output**。

### 7. compatibility firewall 是什么

正常路径不会无条件改写所有请求。只有目标 Provider 明确返回了与跨 Provider structured state 有关的 400/422，例如：

```text
invalid input id
encrypted content could not be verified
previous_response_id rejected
no tool output found for tool call
```

Bridge 才会执行一次更保守的 stateless portable retry。

认证失败、余额/限流、模型不存在、普通 500 等错误不会被误判成“历史格式问题”。

### 8. 为什么这个设计比“写几个模型 if/else”更通用

兼容逻辑不是：

```text
if DeepSeek: ...
if GLM: ...
if Qwen: ...
```

而是围绕能力和状态安全做判断：

```text
能安全 continuation -> cursor + delta
不能 -> portable full replay
durable store 不支持 -> 记为 stateless
结构化历史被明确拒绝 -> compatibility firewall retry
仍失败 -> 把真实上游错误返回
```

所以 GLM / DeepSeek / Qwen 是“已经回归验证的 Provider”，不是“代码只支持这三个 Provider”。其他 Provider 可以 best effort 走同一套通用路径，但没有测试过就不能承诺 100% 支持。

## 生命周期怎么解释

Windows Launcher 常驻托盘，负责观察 Provider 路由和必要的进程恢复。

- Official 路径不依赖 CC Switch 一直打开；
- 第三方路径需要 `127.0.0.1:15721` 的 CC Switch 代理；
- 第三方代理消失时，Launcher 尝试恢复 CC Switch；
- 真正的 Provider/model 路由变化时才执行对应的刷新/重启策略；
- `Exit Everything...` 是显式关闭，不等于卸载；
- 卸载会恢复安装前 Codex 配置（能找到快照时），但不会删除聊天记录。

## 为什么要发布 GitHub Release

Release 不是为了“防止用户点错 cmd/command”，而是把某个已经测试过的 commit 变成一个可重复获取、可验证、可回滚的产品版本。

### 对用户

Repository Source ZIP 是“某个源码快照”，里面有源码、测试、工作流和多平台文件；Release 则可以直接给不同平台明确的入口：

```text
Windows -> CodexBridge-Windows.zip
Apple Silicon -> CodexBridge-macOS-AppleSilicon-unsigned.zip
Intel Mac -> CodexBridge-macOS-Intel-unsigned.zip
```

用户不用理解仓库结构，也不用自己判断架构。

### 对工程

Release 提供：

- 固定 tag，对应确定 commit；
- 平台产物；
- SHA-256 完整性校验；
- CI 构建记录；
- Changelog；
- 出问题时可以明确说“v0.1.1 有问题，回退 v0.1.0”，而不是讨论某个不确定的 main 状态。

### 面试一句话

> 我把它做成 Release，是因为开源项目从“代码能跑”到“别人能稳定使用”还差一层 release engineering：要把版本、commit、CI、平台包、校验值和变更记录绑定起来，才能做到可复现、可验证和可回滚。

## 高频面试追问

### Q：为什么不直接改 Codex 的历史文件？

因为 `.codex/sessions` / SQLite 历史是用户的本地事实源，直接改历史风险很高。Bridge 尽量只在请求边界做兼容转换，让保存的原始会话保持不被污染。

### Q：为什么不总是发完整历史，最简单？

完整 replay 是最安全的 fallback，但长会话会增加 token、延迟和上游解析压力。所以安全时复用 provider-local continuation；不能证明安全时才退回 full replay。

### Q：为什么第三方之间也要转换？

因为“都是第三方”不代表共享服务端状态。DeepSeek 的 response id / reasoning state 对 GLM 没有天然意义，反过来也一样。

### Q：如果新 Provider 没测试过怎么办？

通用 compatibility path 会先尝试正常 Responses 请求，并根据是否支持 durable continuation 自动降级；如果完整 portable replay 也被它拒绝，就明确失败。README 因此把未验证 Provider 标为 Best effort，而不是虚假宣称全部支持。

### Q：你项目最重要的设计取舍是什么？

> correctness first。宁可在不确定时多 replay 一些历史，也不让一个旧 Provider 的隐藏状态覆盖用户当前可见任务状态。

## 面试时不要过度宣称

建议说：

> “目前我实际回归了 Official、GLM、DeepSeek、Qwen；其他 Responses-compatible Provider 走通用 best-effort 路径。”

不要说：

> “所有模型都 100% 支持。”
