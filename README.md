<div align="center">

# CodexBridge

**在 ChatGPT/Codex 账号订阅态与 API Provider 之间切换时，尽可能保持同一条 Codex 会话连续。**

CodexBridge 不是模型聚合器，而是面向 Codex 的 **跨认证体系、跨 Provider、跨 Backend 会话连续性兼容层**。它补上的是账号登录的 Official Codex 与 API Key Provider 之间的会话衔接。

[English](README.en.md) · [架构说明](docs/ARCHITECTURE.md)

[![Windows CI](../../actions/workflows/build-windows-release.yml/badge.svg)](../../actions/workflows/build-windows-release.yml)
[![macOS CI](../../actions/workflows/build-macos-release.yml/badge.svg)](../../actions/workflows/build-macos-release.yml)
[![Releases](https://img.shields.io/badge/Releases-download-blue)](../../releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-Beta-orange.svg)](#项目状态)

</div>

> [!IMPORTANT]
> CodexBridge 是 **CC Switch 的非官方 companion**，不是 OpenAI 或 CC Switch 的官方组件。项目仍处于 Beta；Codex、CC Switch 或上游 API 的变化都可能需要重新适配。

## 它解决的到底是什么痛点？

很多多模型平台已经能用 **一个 API Key / 一个固定 Endpoint** 聚合 Qwen、DeepSeek、GLM 等模型。在这种架构里，本质上仍然是 **API ↔ API**：Codex 面对的是同一个 API Provider，平台内部再切模型，因此通常更容易保持对话连续。

CodexBridge 解决的是另一条边界：

```text
ChatGPT / Codex 账号订阅登录
            ↕
        CodexBridge
            ↕
第三方 / OpenAI API Key Provider
```

也就是说，项目真正的核心不是“模型切换”，而是：

> **让 ChatGPT/Codex 账号订阅态 ↔ API Provider 态之间切换时，同一条 Codex 会话仍尽可能连续。**

这同时跨越了 **认证体系、Provider 和 Backend**。账号登录的 Official Codex 与 API Key Provider 并不天然共享同一套服务端会话状态，CodexBridge 就工作在这条边界上。

> [!NOTE]
> 如果你的所有模型本来就已经放在同一个兼容的 API 聚合网关后面，而且在那个网关内部切模型时同一条 Codex 对话已经可以直接继续，那么你可能并不需要 CodexBridge。

## 为什么仍然需要会话兼容层？

CC Switch 很擅长切换 Provider，但 **“Provider 切换成功”并不等于“同一条 Codex 会话可以无缝继续”**。

Codex 的上下文不只有聊天文本，还可能携带 `previous_response_id`、item ID、reasoning、加密内容、模型名以及 Provider 私有的服务端状态。它们在原 Provider 上合法，跨 Provider 重放时却可能失效。

常见结果包括：

- 切换后旧会话消失，或能看到但无法继续发送；
- `Expected an ID that begins with 'msg'`；
- `Encrypted content could not be verified/decrypted`；
- `Invalid input[…].content: array too long`；
- 切回官方后仍携带旧三方模型名；
- 每次切换都重放整段上下文，fresh input/token 突然暴涨。

CodexBridge 的目标不是替代 CC Switch，也不是再做一个模型聚合平台，而是补上 **订阅账号态 ↔ API Provider 态之间的 Codex 会话连续性这一层**。

## 安装（普通用户只看这里）

### Windows 10/11：推荐安装包

普通 Windows 用户推荐直接使用 GitHub Release 里的 **`CodexBridge-Setup.exe`**：

1. 打开项目的 **Releases**；
2. 下载 `CodexBridge-Setup.exe`；
3. 双击运行；
4. 安装完成后正常使用 CC Switch / Codex 即可。

安装包会自动把 CodexBridge 安装到当前用户目录、注册后台 watcher 和标准卸载入口，并启动 CodexBridge。**不需要管理员权限，也不需要手动安装 Python。**

同时会提供 `CodexBridge-Setup.exe.sha256`，用于校验下载文件。由于目前是未签名的开源构建，Windows SmartScreen 可能给出提示；确认文件来自本项目 Release 并核对 SHA-256 后再运行。

### macOS：推荐使用 Release 包

macOS 用户优先从项目 **Releases** 下载与机器架构对应的包：

- Apple Silicon（M1/M2/M3/M4…）：`CodexBridge-macOS-AppleSilicon.zip`
- Intel：`CodexBridge-macOS-Intel.zip`

下载后解压，双击 **`Start CodexBridge.command`**。首次运行会自动准备用户级运行环境并注册 LaunchAgent。Release 同时提供对应的 `.sha256` 校验文件。

如果你不会用 Releases，也可以在仓库点击 **Code → Download ZIP**，解压后双击 **`Start CodexBridge.command`**。

> [!IMPORTANT]
> macOS 可能因为 Gatekeeper 对从浏览器下载的脚本给出安全提示。若双击被阻止，请在 Finder 中对 `Start CodexBridge.command` **右键 → 打开** 一次。

### Windows 源码 ZIP 仍然保留

如果你不会用 Releases，直接在仓库点击 **Code → Download ZIP**，解压后双击 **`Start CodexBridge.cmd`** 即可。首次运行会自动完成所需的用户级安装/初始化并启动 CodexBridge。

### 用户实际操作路径

```text
Windows:
GitHub Release → CodexBridge-Setup.exe → 双击安装 → 正常使用 CC Switch / Codex
或：Code → Download ZIP → Start CodexBridge.cmd → 自动安装/启动

macOS:
GitHub Release → Apple Silicon / Intel 对应 ZIP → Start CodexBridge.command → 正常使用
或：Code → Download ZIP → Start CodexBridge.command → 首次自动初始化
```

GitHub Actions 会分别在 Windows 与 macOS runner 上构建并回归测试发布物；Release 会发布 Windows `CodexBridge-Setup.exe`、macOS Apple Silicon / Intel ZIP 以及对应的 SHA-256 校验文件。

## 装完以后会发生什么？

正常情况下，你不再需要手动运行 PowerShell、修改 `config.toml`、启动 Bridge 或重启 CC Switch。

| 场景 | CodexBridge 的行为 |
| --- | --- |
| 切到 OpenAI Official | Bridge 直接连接 ChatGPT Codex backend，并保留可复用的 Official resident state |
| 切到 GLM / DeepSeek / Qwen 等三方 | Bridge 通过 CC Switch `127.0.0.1:15721` 转发，并维护该 Provider 的独立 continuation state |
| 三方模式下 CC Switch 被关闭 | Launcher 检测到 `:15721` 消失后自动拉起 CC Switch，不擅自切回 Official |
| Provider 切换后 Codex 需要刷新认证/模型 | Launcher 自动执行必要的 Codex / CC Switch 重启 |
| 当前 Provider 改变 | Codex picker 只暴露当前 Provider 的模型，不再混显示其他 Provider 模型 |
| 从托盘选择 `Exit Everything...` | 先弹出警告确认；确认后停止 Launcher、Bridge 与 CC Switch，但保留轻量 CC Switch 触发监视器；不修改 `config.toml`、不切换 native Official、也不重启 Codex |
| Official 状态下关闭 CC Switch | 不做任何处理；Official 继续经常驻 Bridge 正常聊天 |
| 三方状态下关闭 CC Switch | 只自动恢复 `:15721` 代理；Provider/model 不变，也不会仅因代理恢复而重启 Codex |

## 核心能力

### 🔁 跨 Provider 会话连续性

CodexBridge 保持稳定的：

```toml
model_provider = "custom"
```

Provider 切换由 Bridge 内部路由和 provider-scoped catalog 表示，而不是让 Codex 会话在不同 provider bucket 之间来回漂移。

### 🧠 Provider 独立续接状态

不同模型服务商的内部 cache/KV state **不能互相读取**。CodexBridge 不伪装成“共享缓存”，而是为不同 Provider 分别维护状态：

> **Correctness-first:** 对复杂 Codex Agent / tool-call 工作流，正确性优先于省 token。v2.12 起，第三方只在“纯消息 + completion 已验证 + instructions 稳定”的场景使用 durable delta；其余情况自动 full replay。

- **Official**：guarded resident WebSocket continuation；
- **第三方**：优先使用 Codex `x-client-request-id` 对应的真实 thread identity（哈希后）隔离 shadow cursor；仅旧版 Codex 缺少该 header 时才回退到 conversation fingerprint。durable `previous_response_id` 只用于安全场景；**tool-bearing 长任务默认不复用 shadow cursor**，检测到工具调用、未闭合 tool chain、未验证完成态或 instruction 漂移时会完整 portable replay，优先保证任务状态不串线。
- 返回同一个 Provider 时，优先只发送该 Provider 尚未看到的 conversation delta。

这可以减少“切回来又完整重放”的成本，但 **不能保证服务商账单中的 cached tokens 一定命中**。

### 🧩 Provider-scoped 模型列表

切到 GLM 时只显示 GLM 路线的模型；切回 Official 后只显示 Official 模型。Bridge 内部仍保留已学习的 catalog 元数据，但不把所有 Provider 混在 Codex picker 里。

### 🛡️ 不改写你的历史文件

CodexBridge 不需要直接修改：

- `.codex/sessions`；
- Codex SQLite 历史数据库；
- `.codex/auth.json`。

跨 Provider 兼容处理发生在请求转发/续接层，而不是通过永久篡改历史文件实现。

### 🖥️ 一次安装，后台自动接管

Windows Launcher 负责：

- Bridge 生命周期；
- CC Switch proxy supervision；
- Provider 切换检测；
- 必要的 Codex / CC Switch restart；
- provider-scoped model catalog；
- 开机/CC Switch 唤醒；
- 日志与诊断入口。

### 🗑️ 标准卸载（Windows）

安装后可从托盘选择 **Uninstall CodexBridge...**，也可以在 Windows **设置 → 应用 → 已安装的应用** 中卸载 CodexBridge，或运行仓库根目录的 `Uninstall CodexBridge.cmd`。

卸载会停止 Bridge / CC Switch，移除开机启动和 CC Switch watcher，恢复安装前的 Codex 配置，并删除 `%LOCALAPPDATA%\CodexProviderBridge` 下的程序、runtime 与日志。Codex 聊天记录不会删除。

## 架构

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

Bridge 活跃时：

```text
Codex
  ↓
model_provider = custom
  ↓
127.0.0.1:15722  CodexBridge
  ├─ Official → ChatGPT Codex backend
  └─ Third-party → 127.0.0.1:15721 → CC Switch → Provider
```

CodexBridge 现在作为常驻兼容层保持 `model_provider = "custom"` 与 `custom.base_url = http://127.0.0.1:15722/v1`。普通用户隐藏托盘不会把会话交回原生 Official，也不会停止 Bridge。

更完整的状态机和路由说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 关于 Token / Prompt Cache

> [!NOTE]
> **OpenAI 的内部 prompt cache 不能直接给 GLM / DeepSeek / Qwen 使用，反过来也一样。**

CodexBridge 能控制的是“是否再次发送整段历史”和“是否复用该 Provider 自己的 continuation cursor”，不能把一个模型服务商内部计算好的 KV/cache 翻译给另一个服务商。

因此：

- 第一次进入一个新 Provider，仍可能需要较大的上下文；
- 返回已经建立状态的 Provider 时，Bridge 会尽量只发送新增 delta；
- 实际账单中的 fresh/cached token 仍取决于对应 Provider 的服务端实现；
- 如果某第三方不支持可持久化的 `previous_response_id`，Bridge 会安全回退到兼容 replay。

## 支持范围

当前普通用户目标是 **Windows 10/11 + macOS Intel + macOS Apple Silicon**。Windows 以 Release 中的 `CodexBridge-Setup.exe` 为推荐安装路径；macOS 以 Release 中与架构对应的 Apple Silicon / Intel ZIP 为推荐路径，仓库源码 ZIP 保留为备用方式。

| 路线 / 平台 | 状态 | 说明 |
| --- | --- | --- |
| Windows 10/11 x64 | ✅ 主路径 | Release 中的 `CodexBridge-Setup.exe`；源码 ZIP 的 `.cmd` 仍作为备用/开发路径 |
| Windows ARM64 | 🟡 兼容路径 | 源码 ZIP bootstrap 可选择 ARM64 Python embeddable 包；正式 Setup 仍建议单独真机回归 |
| macOS Apple Silicon | ✅ Release 路径 | Release 中的 Apple Silicon ZIP；`.command` + 用户级 runtime + LaunchAgent watcher |
| macOS Intel | ✅ Release 路径 | Release 中的 Intel ZIP；与 Apple Silicon 相同的启动与 watcher 逻辑 |
| OpenAI Official | ✅ 主要测试路径 | Bridge 直接连接 ChatGPT Codex backend |
| GLM | ✅ 主要测试路径 | 经 CC Switch Responses 路由 |
| DeepSeek | 🟡 已用于开发测试 | 取决于 CC Switch 当前协议映射 |
| Qwen / MiniMax | 🟡 兼容目标 | 取决于 CC Switch 对对应 Provider/协议的支持 |
| Claude / Gemini 等 | 🟡 条件支持 | CodexBridge 不是协议转换器；需要 CC Switch 能处理该上游协议 |
| Linux / WSL | 🧪 开发路径 | Bash manager 仍保留，但当前不作为普通用户一键路径 |

> [!NOTE]
> “任何电脑”在这里指：支持范围内，不依赖固定用户名、盘符或安装目录。Windows 普通用户只需要下载 Release 安装包；macOS 普通用户优先下载 Release 中与架构对应的 ZIP。两者都不需要进入 Actions 或手动配置 Python。企业组策略、杀毒软件、SmartScreen/Gatekeeper、网络限制、损坏的 CC Switch/Codex 安装或未来上游 API 变化仍可能阻止运行。

> [!WARNING]
> CodexBridge **不是 Anthropic / Gemini / Chat Completions ↔ Responses 的通用协议转换器**。协议适配仍由 CC Switch 或上游兼容层负责。

## 项目状态

当前为 **Beta**。

已经重点覆盖：

- Official ↔ third-party 的同会话切换；
- Codex restart 后 Official resident continuation；
- conversation-scoped third-party shadow state；
- provider-scoped model catalog；
- CC Switch proxy 自动恢复；
- `model_provider = custom` 的稳定身份；
- 常驻 Bridge 生命周期与关闭 CC Switch 后的代理恢复；
- Windows `CodexBridge-Setup.exe` 一键安装与 Release 构建。

仍需要持续回归的区域包括上游版本升级、新 Provider、Realtime/Voice、复杂 tool item、新 reasoning item shape，以及不同第三方对 durable continuation 的实现差异。

## 常见问题

<details>
<summary><strong>为什么一定要保留 <code>model_provider = "custom"</code>？</strong></summary>

它提供稳定的 Codex provider identity。真正的 Official / GLM / DeepSeek 等切换由 Bridge 内部路由和模型 catalog 完成，从而减少因为 provider bucket 改变导致的历史可见性/续接问题。

</details>

<details>
<summary><strong>切到三方以后，CC Switch 窗口必须一直开着吗？</strong></summary>

不需要一直盯着窗口。但三方链路依赖 CC Switch 的本地代理 `127.0.0.1:15721`。如果该代理因为 CC Switch 被完全退出而消失，Launcher 会在三方路由仍然活跃时自动尝试恢复 CC Switch。

</details>

<details>
<summary><strong>隐藏托盘以后还能继续用 Official 吗？</strong></summary>

可以。普通关闭 CC Switch 时，Official 不受影响；第三方路由会由 CodexBridge 自动恢复 CC Switch 代理。若从 CodexBridge 托盘选择 `Exit Everything...`，会先弹出警告；确认后 Launcher、Bridge 与 CC Switch 会停止，但轻量 CC Switch 触发监视器会继续等待。不会修改 `config.toml` 或重启 Codex；之后用户只需正常打开 CC Switch，CodexBridge 会自动重新启动，无需再次点击启动 CMD。

</details>

<details>
<summary><strong>它会修改或删除我的 Codex 历史吗？</strong></summary>

不会主动改写 `.codex/sessions`、Codex SQLite 历史或 `.codex/auth.json`。项目会修改用户级 Codex 配置来建立稳定路由，并在 manager 修改配置时保留备份。

</details>

<details>
<summary><strong>为什么第一次切到 GLM 仍然可能很贵？</strong></summary>

因为 GLM 第一次并没有 OpenAI 后端的内部缓存。CodexBridge 的优化重点是：在 GLM 已建立自己的 continuation state 后，再次返回 GLM 时尽可能只补发它没有看到的增量。

</details>

<details>
<summary><strong>普通用户需要 Python 吗？</strong></summary>

Windows 安装包不需要用户手动安装 Python；Release 构建会把 standalone Bridge runtime 一起打包。源码 ZIP 的备用启动路径仍会在需要时自动准备用户级 Python runtime。

</details>

## 日志与排障

运行日志默认位于：

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

如果提交 Issue，请尽量附上：

- Codex 版本；
- CC Switch 版本；
- 当前 Provider / 模型；
- 发生问题前后的切换顺序，例如 `Official → GLM → Official`；
- 上面三份日志中相关时间段；
- 是否发生过 Codex / CC Switch restart。

请先删除日志中你不希望公开的路径、账号名或其他个人信息。

### `stream disconnected before completion`

先看：

```text
bridge-stderr.log
```

重点区分问题发生在：

```text
Codex → :15722 Bridge
```

还是：

```text
Bridge → :15721 CC Switch → Provider
```

### `10061 connection refused`

如果报错指向 `127.0.0.1:15722`，说明 Codex 仍指向 Bridge，但常驻 Bridge 当前没有监听。重新运行 `Start CodexBridge` 会恢复常驻服务；如果仍出现该错误，请附上 Launcher log。

## 从源码运行 / 开发

Windows 普通用户优先使用 Release 中的 `CodexBridge-Setup.exe`；macOS 普通用户优先使用 Release 中与架构对应的 ZIP。仓库源码 ZIP 仍保留为备用路径。下面的源码结构主要面向维护者：

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

GitHub Actions 在 Windows / macOS runner 上执行回归和打包测试。普通用户只需从 Release 下载对应平台的发布物，不需要进入 Actions。

本地开发构建入口见 `scripts/build/`。

> Windows 维护者提示：如果从 Windows 提交代码，macOS 的 `.command` / `.sh` 必须在 Git 中保留 executable bit。可运行 `scripts/maintainer/PrepareGitHubFromWindows.ps1` 一次；`.gitattributes` 会同时固定 shell 文件为 LF 换行。

## 安全与隐私

- Bridge 默认只监听 `127.0.0.1`，不要把它暴露到 `0.0.0.0` 或公网；
- 不要把包含个人路径、Provider 配置或其他敏感信息的完整日志直接公开；
- 项目不会通过“修改 session 文件”来迁移历史；
- 这是非官方兼容层，请在重要工作流中自行保留 Codex 配置与项目数据备份。
- 安全问题请优先按 [SECURITY.md](SECURITY.md) 的方式报告，不要在公开 Issue 中粘贴 token、API key 或未脱敏日志。

## Roadmap

- [x] Official ↔ third-party 同会话继续
- [x] Official resident continuation
- [x] Third-party conversation-scoped shadow state
- [x] Provider-scoped model picker
- [x] CC Switch proxy supervisor
- [x] 仓库 ZIP 直接双击启动（Windows + macOS）
- [x] Windows 用户级 runtime / tray watcher
- [x] macOS 用户级 runtime / LaunchAgent watcher
- [x] GitHub Actions 跨平台 CI
- [ ] 更完整的多 Provider / 多 Codex 版本回归矩阵
- [x] Windows 标准卸载入口（托盘 / 已安装的应用 / 卸载脚本）
- [x] Windows `CodexBridge-Setup.exe` 正式安装包 / Release 资产
- [ ] macOS `.dmg` / `.pkg` 与更完整的跨平台安装/更新体验
- [ ] Portable handoff / lazy replay，降低首次进入新 Provider 的完整上下文成本
- [ ] 上游 CC Switch lifecycle hook / companion integration

## Contributing

Bug report、兼容性测试和 PR 都欢迎。完整贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。

如果是较大的功能改动，建议先开 Issue 描述：

1. 你想解决的真实工作流；
2. 当前行为；
3. 期望行为；
4. Codex / CC Switch / Provider 版本；
5. 是否会影响现有 continuation state 或路由。

这样更容易保持 Bridge 的核心原则：**不破坏已有会话，失败时优先安全回退。**

## 致谢

- [CC Switch](https://github.com/farion1231/cc-switch) 提供多 Provider 管理与本地路由能力；
- OpenAI Codex / Responses 生态提供本项目适配的客户端与会话模型。

CodexBridge 与 OpenAI、CC Switch 项目及其作者均无官方隶属关系。

## License

[MIT](LICENSE)

---

<div align="center">

如果 CodexBridge 确实解决了你的跨 Provider 工作流，**给项目一个 ⭐ Star** 会帮助更多遇到同样问题的人找到它。

</div>
