# macOS 菜单栏启动器实现计划

**目标：** 在不修改 Bridge 核心协议的前提下，为 macOS 增加原生 AppKit 菜单栏 `.app`、独立 launcher LaunchAgent、启动/卸载生命周期，以及 arm64/x86_64 release 构建验证。

**架构：** Swift AppKit 只提供菜单栏 UI、状态读取和生命周期控制；现有 manager、watcher、LaunchAgent 与 Python Bridge 继续承担后台工作。`Start CodexBridge.command` 安装两个独立 LaunchAgent 和 app bundle，CI 在两个 macOS runner 上用 `swiftc` 构建、签名和归档。

**技术栈：** Swift + AppKit + Foundation、Bash、GitHub Actions、Python unittest/pytest。

## 任务 1：先建立失败的 launcher 契约测试

**文件：** `tests/test_macos_portability_contract.py`

1. 增加对 Swift 源码、`Info.plist.in`、AppKit/status item API、固定 bundle id、`LSUIElement`、`VERSION` 替换、launcher LaunchAgent、卸载脚本、两个架构、archive、可执行权限、签名和 unsigned 分支的断言。
2. 运行 `uv --cache-dir .uv-cache run --python .venv\\Scripts\\python.exe -m pytest tests/test_macos_portability_contract.py -v`，确认新增断言因功能不存在而失败。
3. 仅提交测试变更，提交信息为 `test: define macOS menu bar launcher contract`。

## 任务 2：实现 AppKit launcher、bundle 模板和卸载脚本

**文件：**

- `src/launcher-macos/CodexBridgeLauncher.swift`
- `src/launcher-macos/Info.plist.in`
- `scripts/unix/codex_bridge_uninstall.sh`

1. 将所有 `Process` 调用集中到参数数组形式的命令封装；状态读取失败返回 `Unknown`，不让异常退出菜单栏应用。
2. 实现 `NSStatusItem`、`NSMenu`、状态/路由/模型、日志入口、重启动作、中英文切换、确认框和 `LSUIElement` accessory 生命周期。
3. 使用独立的 `com.strengw.codexbridge.launcher` LaunchAgent 控制 UI 开机启动；watcher LaunchAgent 保持独立。
4. 卸载脚本停止两个 LaunchAgent 和 Bridge，删除 app/runtime/log/state，保留 Codex 聊天记录，并正确处理中文和空格路径。

## 任务 3：接入启动脚本、manager action 和 watcher action

**文件：**

- `Start CodexBridge.command`
- `scripts/unix/codex_bridge_manager.sh`
- `scripts/unix/codex_bridge_watcher.sh`

1. 保留现有 portable Python 和 watcher bootstrap；release 包存在预构建 app 时直接安装，源码启动且有 `swiftc` 时按 `VERSION` 构建。
2. 生成 launcher LaunchAgent，使用 marker 表示菜单栏 UI 的开机启动开关，并用 `/usr/bin/open` 启动 app。
3. 为 manager 增加 `restart`、`restart-codex`、`restart-cc-switch` 最小 CLI action；Codex/CC Switch 的具体重启逻辑仍由 watcher 已有函数执行，Swift 不复制后台逻辑。
4. 在 macOS 状态根统一使用 `~/Library/Application Support/CodexProviderBridge`；Linux/WSL 保持原 XDG 状态根。

## 任务 4：扩展 macOS workflow

**文件：** `.github/workflows/build-macos-release.yml`

1. 在 `macos-15` 使用 arm64 target，在 `macos-15-intel` 使用 x86_64 target，以 `swiftc` 构建 `CodexBridge.app`。
2. 从 `VERSION` 注入 `CFBundleShortVersionString`/`CFBundleVersion`，检查 bundle id、`LSUIElement`、Mach-O 架构和 executable bit。
3. 将 app、Start、watcher、卸载脚本、portable Python 一起归档，并解压验证 app executable、Info.plist 和现有运行文件。
4. 有凭据时签名 runtime 和 app 内 Mach-O，再签名 `.app` 并保持 notarization；无凭据时继续生成 `-unsigned.zip`。

## 任务 5：版本、文档与发布前验证

**文件：** `VERSION`、`CHANGELOG.md`、中英文 README、Windows 两处 `ProductVersion`、`tests/test_macos_portability_contract.py`。

1. 菜单栏功能作为公开 `0.1.3` 发布，所有公开版本源和 Windows Installed Apps 元数据保持一致。
2. 运行全量 Python 测试、Windows release package smoke test、`git diff --check`，并确认 `src/bridge/codex_provider_bridge.py` 没有差异。
3. Windows 主机不能执行 AppKit；Swift 编译、macOS bundle、bash 语法和真实 GUI 由 GitHub macOS runner 验证后再创建 `v0.1.3` release。
