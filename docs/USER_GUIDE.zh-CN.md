# CodexBridge 使用说明（详细版）

README 讲的是怎么装、怎么启动。这份文档承接 README 里只给结论的部分：CodexBridge 和 CC Switch 各管什么，它在什么情况下会去动 CC Switch，切换后掉到登录页是怎么回事，首次运行时那份 Python 运行时从哪来，以及退出、卸载和后台组件到底差在哪里。

会话续接的实现原理不在这里，见 [PROJECT_OVERVIEW.zh-CN.md](PROJECT_OVERVIEW.zh-CN.md)；架构与不变量见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## CodexBridge 和 CC Switch 各管什么

CC Switch 决定用哪个 Provider，Provider 的添加、删除和切换都由它负责。CodexBridge 决定切换之后，原来那条 Codex 会话还能不能继续发下去。它不管理 Provider，也不负责路由本身。

用第三方 Provider 时，请求的实际链路是：

```text
Codex → CodexBridge (127.0.0.1:15722) → CC Switch 本地代理 (127.0.0.1:15721) → DeepSeek / GLM / Qwen
```

CodexBridge 会把 Codex 的 `base_url` 固定在本地 Bridge，避免切换后它被改成某个 Provider 的直连地址而绕过 CC Switch 代理。但 Bridge 自己不联网聚合模型，第三方请求仍然要交给 CC Switch 的代理端口。

所以：

- **用第三方 Provider 时，CC Switch 必须一直开着。** 关掉它，`127.0.0.1:15721` 就没人监听，消息发不出去。重新打开 CC Switch 即可恢复，不需要重启 CodexBridge，也不需要重启 Codex。
- **只有 OpenAI Official 路由不依赖 CC Switch**，可以在它关闭时继续使用。
- 是否需要 CC Switch，只取决于当前这条请求要不要走它。一条以前经过第三方的旧会话，切回 Official 之后不需要为了它先开 CC Switch。

## CodexBridge 什么时候会去动 CC Switch

默认情况是不动。CodexBridge 不会因为代理掉线而重启 CC Switch，不会因为你主动关闭而把它拉起来，也不会通过系统发现、记住的路径或默认安装路径去找它并启动。第三方路由不可用时，它只提示你打开 CC Switch。

唯一的例外是 Provider/auth 切换修复流程，Windows 与 macOS 行为一致。它需要同时满足三个条件才会触发：

1. 当前是第三方路由；
2. 被钉住的 `custom` provider 带着 `requires_openai_auth = true`；
3. `~/.codex/auth.json` 里没有可用的 ChatGPT 凭据。

这三个条件同时成立时，重启 Codex 必然会掉到登录页（原因见下一节）。此时 CodexBridge 会在一次真实的 Provider 切换边沿上，绑定当前正在运行、且路径已核验的那一个 CC Switch 实例，对它执行一次受控重启，然后提示你重启 Codex。

这个重启是有边界的一次性动作：每个切换键只触发一次，不会循环，watcher 也不会去重启一个已经在运行的 Launcher，代理端口在预期内的短暂消失期间监督逻辑是静默的。绑定的可执行文件路径只来自当前活着的进程（Windows 取已核验的进程路径，macOS 从 `NSWorkspace.runningApplications` 取实际运行的 CC Switch，按它自己的 bundle path 重启），不会被记住、不会落盘、也不会取自默认安装位置。

如果绑不到活着的实例，或者这次有界重启失败了，CodexBridge 就不再提示重启 Codex，改为请你重新打开 CC Switch。

CodexBridge 按设计不写 `auth.json`。凭据是 CC Switch 在它自己重启时重新落盘的。

## 为什么切换后 Codex 会掉到登录页

先说结论：现在这件事由 CodexBridge 在切换修复流程里自动处理，你不需要手动操作，也不需要重新登录。手动等价顺序是先重启 CC Switch，再重启 Codex。只有"只重启 Codex、不重启 CC Switch"才会掉到登录页。

原因是两边对凭据的处理方式不同：

CC Switch 自己托管 Codex 的 ChatGPT OAuth。切到第三方 Provider 时，它不会把 ChatGPT tokens 继续保留为 `auth.json` 里的可用凭据，而是改走 API-key 或托管存根模式。

CodexBridge 为了让同一条会话跨 Provider 可用，会把当前 provider 钉成 `custom`，并恒定设置 `requires_openai_auth = true`，也就是要求 Codex 使用 ChatGPT 凭据。

于是第三方模式下出现了"配置要求 ChatGPT 凭据、但磁盘上没有"的状态。正在运行的 Codex 靠内存里的旧 token 掩盖了这个不一致；一旦重启，它重新读磁盘凭据，读不到，就掉到登录页。重启 CC Switch 或切回 Official 都会把凭据恢复成一致状态。

这是已知的行为，不是会话续接坏了。

**万一还是掉到登录页**（例如自动修复没能完成），三个办法任选：在登录页点一次"通过 ChatGPT 登录"；或重新打开 CC Switch 让它恢复一致状态；或切回 Official。恢复之后 CodexBridge 会继续把路由钉在本地 Bridge，会话不受影响。

## 首次运行的 Python 运行时

不需要你手动安装 Python，也不需要管理员权限。首次运行会准备一份只属于当前用户的运行时，Windows 放在 `%LOCALAPPDATA%\CodexProviderBridge\runtime`，macOS 放在 `~/Library/Application Support/CodexProviderBridge/runtime`，不写系统目录。

**Windows 首次运行不需要联网。** Release ZIP 里已经内置官方 Python 3.12 运行时（约 11 MB，amd64）。`Start CodexBridge.cmd` 先校验它的 SHA-256，通过之后解压到用户目录。macOS 的 Release ZIP 同样内置了运行时。

只有两种情况会改为联网下载：ARM64 或 32 位 Windows，以及内置包校验没通过。下载会依次尝试 python.org、华为云和 npmmirror，每个来源都要通过同一份固定的 SHA-256 校验；校验不通过的文件会被删掉而不是安装。没有固定校验值的运行时包会被直接拒绝，所以将来升级 Python 版本也不可能悄悄带上未经验证的包。

如果三个来源都失败，脚本会用你的系统语言（简体中文、繁体中文或英文）说明原因和下一步该做什么，每个来源的具体失败原因写在 `%LOCALAPPDATA%\CodexProviderBridge\bootstrap.log`，报障时可以直接附上。这时你可以检查网络或代理后重试，也可以自己安装 Python 3.10 或更高版本，脚本会自动改用它。

需要说明的是，SHA-256 校验保证的是下载内容完整、与上游发布的一致，它不是安全认证。托盘程序仍在本机编译，Release 包里不含任何由我们自行构建的可执行文件。

## macOS 首次打开被拦截

Release 没有做 Apple Developer 签名和公证，所以文件名带 `-unsigned`，首次打开可能被 macOS 拦下。放行步骤按系统版本不同，写在 README 开头的提示框里，一次就够。这里说明万一放行之后仍然打不开该怎么办。

包内的 `CodexBridge.app` 已带完整的本地（ad-hoc）签名，所以正常下载的新包不会再出现"已损坏，移到废纸篓"的提示，走常规放行就够了。万一仍然遇到，重新双击 `Start CodexBridge.command`，在弹窗里点"帮我修复"。这个修复只做两件事：对该 App 本地重新签名、清除它自己的隔离标记。它不改系统安全设置，也不动其他应用。

不要点"移到废纸篓"，也不要关闭 Gatekeeper。前者会直接删掉你刚下载的应用，后者会降低整台机器的安全性，而这个问题不需要你付这两个代价。

启动成功后，CodexBridge 以原生 Menu Bar 应用显示在菜单栏，不占用 Dock 图标。

macOS 目前是 Beta，走 CI 验证。作者没有对每一种 macOS 版本、芯片和 Codex 版本的组合做过实机回归，报障时请注明这三项。

## 退出、卸载和后台组件的区别

**关闭 UI 不等于停止 Bridge。** 普通关闭窗口之后后台 Bridge 仍在运行，这是设计如此。只有明确点 `退出 CodexBridge...` 才会停止完整的 Launcher、Bridge 和 CC Switch 功能组件。

退出时会先做一次确认。如果当前是 Official 路由，它会先完成直连 Official 的交接并验证，再停止本地 Bridge；如果是第三方路由，直接停止 Bridge。轻量 watcher 会保留，之后你正常打开 CC Switch 时 CodexBridge 会自动启动。

**退出不是卸载。** 卸载会关闭 Bridge 和 CC Switch，停止并删除 watcher 注册，删除 CodexBridge 的本地程序、运行时和日志，并优先恢复安装前的 Codex 配置；找不到完整的安装前快照时，回退到直接 Official 路由。卸载不会删除你的 Codex 聊天记录。

**登录时常驻的是一个无界面 watcher。** Windows 登录只启动这个轻量组件；如果 CC Switch 那时已经在运行，这一刻不会被当作新的打开事件。之后只有 CC Switch 从未运行变为运行时，才会启动完整的 CodexBridge。这个行为不可切换。

因此任务管理器里可能同时看到两个 `CodexBridgeLauncher.exe`：带 `--watch-ccswitch` 的是无界面 watcher，带 `--installed` 或 `--ccswitch-trigger` 的是托盘 Launcher。它们不是两个完整 Bridge，完整 Launcher 由单实例互斥保证最多只有一个。

## CodexBridge 会改我哪些文件

它会修改用户级的 Codex 路由配置（`~/.codex/config.toml`），改写前在旁边留一份带时间戳的备份，每种备份各保留最近的三份。

它不会直接改写 `.codex/sessions`、Codex 的 SQLite 历史或 `.codex/auth.json`。

## 报障

需要附上的版本信息、Windows 日志路径和脱敏要求见 README 的「排障」与「安全与隐私」两节。运行时准备失败时，每个下载来源的具体失败原因单独写在 `%LOCALAPPDATA%\CodexProviderBridge\bootstrap.log`，这是最值得附上的一份。
