# Provider Plugin 开发规范

本文档定义 OnlineWorker provider plugin 的最小开发约定。目标是让新 provider 能被 App 发现、展示、配置、运行和测试，同时不把 provider-specific 逻辑泄漏到共享 UI 或共享 runtime。

## 适用范围

- provider 类型插件，`plugin.yaml` 中必须声明 `kind: provider`。
- 当前仓库内置 provider 位于 `plugins/providers/builtin/`。
- 外部 provider 可以通过 `ONLINEWORKER_PROVIDER_OVERLAY` 在运行态挂载，也可以通过 `ONLINEWORKER_PLUGIN_SOURCE_DIRS` 在打包时注入。

非 provider 类型插件暂不在本文档范围内。

## 目录结构

推荐结构如下：

```text
my-provider/
├── __init__.py
├── plugin.yaml
├── icon.svg
└── python/
    ├── __init__.py
    ├── provider.py
    ├── runtime.py
    └── storage_runtime.py
```

约定：

- `plugin.yaml` 是 App、配置归一化、命令目录和运行态 loader 的稳定入口。
- `icon.svg` 是可选但推荐的本地资源，Dashboard 会通过 `plugin.yaml` 的 `icon.path` 读取。
- `python/provider.py` 推荐只组装 `ProviderDescriptor`，具体读写逻辑放进 `runtime.py`、`storage_runtime.py` 等模块。
- 外部 overlay 的 Python import root 是 `plugin.yaml` 所在目录的父目录。例如 `/path/provider-plugins/my-provider/plugin.yaml` 会把 `/path/provider-plugins` 加入 `sys.path`。

## Manifest 规范

最小示例：

```yaml
schema_version: 1
id: my-provider
kind: provider
visibility: private
order: 100
runtime_id: my-provider
label: My Provider
description: My Provider CLI sessions
default_visible: false
icon:
  path: icon.svg
  source: https://example.com/my-provider-icon

provider:
  visible: false
  managed: true
  autostart: false
  runtime_id: my-provider
  bin: my-provider
  owner_transport: stdio
  live_transport: stdio
  control_mode: app
  transport:
    type: stdio
  capabilities:
    sessions: true
    send: true
    approvals: false
    questions: false
    photos: false
    files: false
    commands: true
    command_wrappers: []
    control_modes:
      - app
  process:
    cleanup_matchers: []
  commands:
    - name: status
      scope: thread
      description: 查看 provider 会话状态

entrypoints:
  python_descriptor: my_provider.python.provider:create_provider_descriptor
```

字段约定：

- `schema_version`: 当前使用 `1`。
- `id`: provider 的公开 ID。必须稳定，必须和 `ProviderDescriptor.name` 一致。
- `kind`: 必须是 `provider`。
- `visibility`: `public` 表示仓库内置公开默认 provider；外部 provider 默认使用 `private`。
- `order`: App 展示和默认配置排序。内置 provider 使用较小值，外部 provider 建议从 `100` 起。
- `runtime_id`: 运行态 ID。多数 provider 与 `id` 一致。
- `label` / `description`: UI 展示文案。
- `default_visible`: 默认是否出现在可见 provider 列表。
- `icon.path`: 相对 `plugin.yaml` 所在目录的本地图标文件。
- `icon.source`: 图标来源说明，便于后续审计和替换。
- `provider.visible`: 当前 provider 是否显示。
- `provider.managed`: 是否由 OnlineWorker 管理运行时。
- `provider.autostart`: 服务启动时是否自动启动该 provider runtime。只有 `managed: true` 时才有意义。
- `provider.bin`: CLI 可执行文件名或路径。
- `provider.owner_transport`: App/服务与 provider owner runtime 的控制通道，当前支持 `stdio`、`ws`、`http`。
- `provider.live_transport`: session live 通道，当前可用值包括 `owner_bridge`、`shared_ws`、`stdio`、`ws`、`http`。
- `provider.control_mode`: 控制模式，通常为 `app`；Codex 还支持 `tui`、`hybrid`。
- `provider.transport.type`: 与 `owner_transport` 保持一致，兼容旧字段读取。
- `provider.transport.app_server_port` / `app_server_url`: 仅在 `ws` / `http` 类 transport 需要。
- `provider.capabilities`: App 用于决定功能入口和发送能力。
- `provider.process.cleanup_matchers`: 只填写该 provider 自己启动的子进程匹配规则，不能匹配通用 CLI、终端、编辑器或用户进程。
- `provider.commands`: 下游 CLI command catalog。`scope` 支持 `global`、`workspace`、`thread`，默认是 `thread`。
- `entrypoints.python_descriptor`: Python descriptor 工厂，必须是 `module:function` 格式。

Manifest 是共享边界。不要在 `plugin.yaml` 中写入本地用户路径、私有 token、临时端口、调试日志路径或仓库外实现细节。

## 图标规范

- 推荐使用本地 `icon.svg`，并通过 `icon.path` 引用。
- SVG 应尽量小，包含明确 `viewBox`，不要依赖远程 CSS、字体或脚本。
- 如果图标来自第三方，必须填写 `icon.source`。
- App 后端会在运行时把本地图标转为 `data:image/svg+xml;base64,...` 传给 Dashboard；生成的 data URL 不会写回 `config.yaml`。
- 如果没有 `icon`，Dashboard 会使用通用 fallback 图标。

## Python Descriptor 规范

`entrypoints.python_descriptor` 指向的函数必须返回 `core.providers.contracts.ProviderDescriptor`。

示例：

```python
from core.providers.contracts import (
    ProviderDescriptor,
    ProviderFactsHooks,
    ProviderManifestCapabilities,
    ProviderMetadata,
    ProviderTransportMetadata,
)


def create_provider_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        name="my-provider",
        metadata=ProviderMetadata(
            id="my-provider",
            runtime_id="my-provider",
            label="My Provider",
            description="My Provider CLI sessions",
            visible=False,
            managed=True,
            autostart=False,
            bin="my-provider",
            transport=ProviderTransportMetadata(
                owner="stdio",
                live="stdio",
                type="stdio",
            ),
            capabilities=ProviderManifestCapabilities(
                sessions=True,
                send=True,
                commands=True,
            ),
        ),
        facts=ProviderFactsHooks(
            scan_workspaces=lambda *, sessions_dir=None: [],
            list_threads=lambda workspace_path, limit=20: [],
            read_thread_history=lambda thread_id, *, limit=10, sessions_dir=None: [],
            query_active_thread_ids=lambda workspace_path: set(),
        ),
    )
```

最低要求：

- `ProviderDescriptor.name` 必须等于 `plugin.yaml` 的 `id`。
- `metadata.id` 必须等于 provider ID。
- `facts` hooks 必须存在，即使 provider 暂时没有 session 数据，也要返回空集合。
- 如果 `capabilities.send: true`，需要提供可用的 `message_hooks`。
- 如果 `managed: true` 且需要 OnlineWorker 启停 provider runtime，需要提供 `runtime_hooks.start` / `runtime_hooks.shutdown` 或沿用已有默认 runtime。
- Python metadata 和 `plugin.yaml` 中的公开字段应保持一致，避免 App 展示和 bot/runtime 行为不一致。

## 能力声明

`provider.capabilities` 是 UI 和 runtime 的功能契约：

- `sessions`: 是否支持 workspace/thread 浏览。
- `send`: 是否支持从 App 或 Telegram 发送消息。
- `approvals`: 是否支持审批类交互。
- `questions`: 是否支持问题回复类交互。
- `photos`: 是否支持图片附件。
- `files`: 是否支持文件附件。
- `commands`: 是否暴露下游命令。
- `command_wrappers`: thread 级 command wrapper，例如 `model`、`review`。
- `control_modes`: 支持的控制模式。

不要为了显示入口而把未实现能力标成 `true`。能力声明应以 provider 的实际 hook 和 runtime 行为为准。

## Overlay 开发

运行态挂载：

```bash
ONLINEWORKER_PROVIDER_OVERLAY=/path/to/provider-plugins /path/to/python3 main.py
```

也可以把同名 key 写入：

```text
~/Library/Application Support/OnlineWorker/.env
```

构建时注入：

```bash
ONLINEWORKER_PLUGIN_SOURCE_DIRS=/path/to/provider-plugins/my-provider bash scripts/build.sh
```

注意：

- `ONLINEWORKER_PROVIDER_OVERLAY` 可以指向单个 `plugin.yaml`，也可以指向一个目录；目录会递归扫描 `plugin.yaml`。
- 多个 overlay 路径使用系统路径分隔符连接，macOS 上是 `:`。
- 构建注入会复制目录到 `mac-app/src-tauri/provider-plugins/`，不要依赖源目录里的未提交临时文件。

## 测试清单

新增或修改 provider 后，至少执行：

```bash
/path/to/python3 -m pytest -q tests/test_config.py tests/test_provider_facts.py tests/test_provider_session_bridge.py
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --lib
cargo test --manifest-path mac-app/src-tauri/Cargo.toml command_catalog --lib
node --test mac-app/tests/*.test.mjs
npm --prefix mac-app run build
```

如果改动影响打包、sidecar、provider runtime 或 Dashboard 展示，还需要执行 packaged-app 验证链，至少包括：

- `bash scripts/build.sh`
- 记录 DMG hash
- 挂载 DMG 并确认 `OnlineWorker.app` 版本
- 覆盖 `/Applications/OnlineWorker.app`
- 重启并确认新 `onlineworker-app` / `onlineworker-bot` 进程来自 `/Applications/OnlineWorker.app`
- 跑目标 provider 的最小 smoke
- 检查本次 smoke 对应日志没有 traceback 或 provider routing error

## 兼容性要求

- 新 provider 不应要求修改共享 React 页面里的 provider-specific 分支。
- 新 provider 不应在共享 Rust command 中写死 provider ID；优先从 manifest 和 `ProviderDescriptor` 读取。
- 新 provider 不应删除或移动用户历史、会话、日志、数据库或凭据。
- cleanup 只能作用于该 provider 自己创建并且可明确识别的进程。
- public 默认 provider 只应放进 `plugins/providers/builtin/`；外部 provider 通过 overlay 交付。
- 所有文档、manifest 和源码使用 UTF-8。

## 常见问题

### App 能看到 provider，但 bot/runtime 不可用

通常是 `plugin.yaml` 可被 Rust 侧读取，但 `entrypoints.python_descriptor` 无法被 Python import，或 `ProviderDescriptor.name` 与 manifest `id` 不一致。先检查 overlay 根目录和 Python 包路径。

### Dashboard 没有显示图标

确认 `plugin.yaml` 中存在：

```yaml
icon:
  path: icon.svg
```

并确认 `icon.svg` 与 `plugin.yaml` 在同一目录，或者 `path` 正确指向相对路径。

### Commands 页没有下游命令

确认 `provider.commands` 列表存在，并且当前 provider 是可见 provider。命令名不能为空，`scope` 不填时按 `thread` 处理。

### 打包后 overlay 丢失

运行态 overlay 依赖 `ONLINEWORKER_PROVIDER_OVERLAY`。如果要随 DMG 一起分发，需要在打包前设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`。
