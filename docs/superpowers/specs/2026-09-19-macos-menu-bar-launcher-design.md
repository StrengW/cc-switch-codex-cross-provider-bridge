# macOS Menu Bar Launcher 设计规格

## 目标

为 CodexBridge 增加原生 macOS Menu Bar Launcher，同时保留现有 watcher、manager 和 Python Bridge 的后台职责，不修改跨 Provider 协议核心逻辑。

## 架构

新增一个使用 AppKit 的轻量 `CodexBridge.app`。它只负责 `NSStatusItem`、菜单、确认框、状态展示和生命周期控制；后台服务继续由现有 `codex_bridge_manager.sh`、`codex_bridge_watcher.sh`、`launchctl` 和 Python Bridge 负责。

`Start CodexBridge.command` 仍是兼容入口，负责 runtime/bootstrap、watcher LaunchAgent 和 launcher LaunchAgent 的安装，然后启动 `.app`。watcher 使用 `com.strengw.codexbridge.watcher`，菜单栏 UI 使用独立的 `com.strengw.codexbridge.launcher`，两者互不替代。

## 组件与边界

- `src/launcher-macos/CodexBridgeLauncher.swift`：AppKit UI、进程调用封装、状态模型和菜单 action。
- `src/launcher-macos/Info.plist.in`：bundle 元数据；版本由仓库 `VERSION` 注入，`LSUIElement=true`。
- `Start CodexBridge.command`：安装/更新 `.app`、安装 launcher LaunchAgent、启动 app；保留现有 runtime 和 watcher 流程。
- `scripts/unix/codex_bridge_uninstall.sh`：确认后的 macOS 清理入口，清理两个 LaunchAgent、app、runtime、日志和配置备份，不删除 Codex 聊天记录。
- `.github/workflows/build-macos-release.yml`：按 runner 架构编译 `.app`、打包、验证和签名。
- `tests/test_macos_portability_contract.py`：静态检查源码、bundle、archive、权限、路径和签名覆盖范围。

不修改 `src/bridge/codex_provider_bridge.py`，也不重写 provider compatibility、history、400/422、tool-history repair 或 route detection。

## 菜单与生命周期

菜单包含状态、路由、Ensure Bridge Running、Restart Bridge、Restart Codex、Restart CC Switch、三个日志入口、日志目录、Launch at Login、Exit Everything 和 Uninstall。provider/model 只有在可靠读取到时显示，否则隐藏。

普通退出只退出菜单栏 UI，不停止后台服务。Exit Everything 必须使用默认否定按钮的确认框，并说明会停止后台服务且可能需要重新启动 Codex。Uninstall 使用独立确认框，调用脚本并退出 UI。

Launch at Login 只控制 `com.strengw.codexbridge.launcher` 的 `RunAtLoad`；watcher 的 `RunAtLoad` 始终保持独立。所有 action 的错误显示为状态/对话框，不允许未处理异常导致 app 退出。

## 本地化与路径

中文系统（`zh`）显示简体中文菜单和确认框；其他语言显示英文。进程调用使用参数数组，不拼接 shell 命令；路径统一来自 `HOME/Library/Application Support/CodexProviderBridge` 或 bundle 目录，支持空格、中文路径，禁止硬编码 `/Users/xxx`。

## 构建与签名

CI 在 `macos-15` 构建 arm64，在 `macos-15-intel` 构建 x86_64；使用 runner 自带 `swiftc` 手工创建标准 `.app` bundle。archive 中必须包含 executable `.app`、现有 Start/watcher/LaunchAgent 相关文件和 portable Python runtime。

有 Apple 凭据时，对 app 内所有 Mach-O（包括 launcher executable）及 `.app` 签名，再沿用现有 notarization；没有凭据时继续生成明确的 `-unsigned.zip`，不改变当前 unsigned 发布路径。

## 验证

契约测试验证：launcher source、固定 bundle identifier、`LSUIElement`、VERSION 注入、两个架构 workflow、archive 中 `.app` 和 executable bit、Start/watcher/LaunchAgent 保留、无本机绝对路径、签名循环覆盖 app、unsigned 分支可用。Windows 本机只执行 Python 静态/契约测试和 `git diff --check`；真实 AppKit GUI 由 GitHub macOS runners 验证。
