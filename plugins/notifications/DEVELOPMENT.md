# Notification Plugin 开发规范

本文档定义 OnlineWorker notification plugin 的开发约定。目标是让新的通知渠道可以被 App 发现、配置和运行时加载，同时避免把 Telegram、微信或其他 App 的发送细节写进共享业务逻辑。

## 设计边界

- notification plugin 只负责“把一条简短通知发到某个外部渠道”。
- 业务代码只产生 `NotificationEvent`，不关心 TG、微信、Webhook 或其他 App 的细节。
- `NotificationRouter` 负责去重、选择已启用渠道、聚合失败结果。
- 每个插件自己负责目标 App 的认证、请求格式、错误解析和最小发送逻辑。
- 当前仓库内置通知插件位于 `plugins/notifications/builtin/`。
- 外部通知插件通过 `ONLINEWORKER_NOTIFICATION_OVERLAY` 在运行态挂载。

provider 插件开发规则见 [../providers/DEVELOPMENT.md](../providers/DEVELOPMENT.md)。

## 目录结构

推荐结构如下：

```text
my-notifier/
├── __init__.py
├── plugin.yaml
├── guides/
│   ├── setup.zh-CN.html
│   └── setup.en-US.html
└── python/
    ├── __init__.py
    └── channel.py
```

约定：

- `plugin.yaml` 是 App 设置页、配置归一化和 Python loader 的稳定入口。
- `python/channel.py` 推荐只实现通知渠道发送逻辑，不反向依赖 provider、Telegram handler、App UI 或具体业务模块。
- 外部 overlay 的 Python import root 是 `plugin.yaml` 所在目录的父目录。例如 `/path/notification-plugins/wechat/plugin.yaml` 会把 `/path/notification-plugins` 加入 `sys.path`，此时 entrypoint 可写成 `wechat.python.channel:create_notification_descriptor`。

## Manifest 规范

最小示例：

```yaml
schema_version: 1
id: wechat
kind: notification
visibility: private
order: 100
label: WeChat
description: Send concise task notifications to WeChat.
default_enabled: false
icon:
  path: icon.svg

settings:
  fields:
    - key: webhook_url
      label: Webhook URL
      type: string
      required: true
      default: ""
      description: WeChat robot webhook used by this notification channel.

setup_guide:
  type: html
  assets:
    zh: guides/setup.zh-CN.html
    en: guides/setup.en-US.html

entrypoints:
  python_descriptor: wechat.python.channel:create_notification_descriptor
```

字段约定：

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | 是 | 当前使用 `1`。 |
| `id` | 是 | 通知渠道公开 ID。必须稳定，必须和 `NotificationPluginDescriptor.name` 一致。 |
| `kind` | 是 | 必须是 `notification`。 |
| `visibility` | 否 | 外部插件建议使用 `private`；内置插件可使用 `public`。 |
| `order` | 否 | App 通知页排序。内置插件使用较小值，外部插件建议从 `100` 起。 |
| `label` | 是 | UI 展示名称。 |
| `description` | 否 | UI 展示描述。 |
| `default_enabled` | 否 | 首次归一化配置时是否默认开启。 |
| `icon.path` | 否 | 相对 `plugin.yaml` 的图标路径。当前 UI 会把 SVG 转成 data URL 展示。 |
| `settings.fields` | 否 | App 通知页渲染的插件配置字段。 |
| `setup_guide` | 否 | App 通知页展示的插件内置配置引导。当前支持静态 HTML。 |
| `entrypoints.python_descriptor` | 是 | Python descriptor 工厂，必须是 `module:function` 格式。 |

不要在 `plugin.yaml` 中写入真实 token、webhook endpoint、本地用户路径或账号数据。需要用户填写的字段通过 `settings.fields` 声明，值由 App 保存到 `config.yaml` 的 `notifications.channels.<id>.config`。

## 配置字段

`settings.fields` 当前支持这些类型：

| type | UI 形态 | 说明 |
|------|---------|------|
| `string` | 文本输入 | 普通字符串配置。 |
| `number` | 数字输入 | UI 会按数字输入，但插件仍应自行校验。 |
| `boolean` | 开关 | 字段级布尔配置，不等同于渠道启用开关。 |
| `select` | 下拉选择 | 需要提供 `options`。 |
| `secret` | 密码输入 | 仅影响 UI 展示；当前不做独立密文存储。 |

字段示例：

```yaml
settings:
  fields:
    - key: bot_token
      label: Bot Token
      type: secret
      required: true
      description: Bot token used only for notification delivery.
    - key: recipient_user_id
      label: Recipient User ID
      type: string
      required: true
      default: ""
      description: User id that receives notification messages.
    - key: mode
      label: Mode
      type: select
      default: concise
      options:
        - value: concise
          label: Concise
        - value: verbose
          label: Verbose
```

保存位置：

```yaml
notifications:
  channels:
    wechat:
      enabled: true
      config:
        webhook_url: "..."
```

约定：

- 渠道开关保存在 `notifications.channels.<id>.enabled`。
- 插件字段值保存在 `notifications.channels.<id>.config`。
- App 不从 `.env` 读取 notification plugin 配置字段。
- 插件必须把所有配置都视为不可信输入，在 `channel_factory` 或发送前自行校验。

## 配置引导

插件可以声明一个内置配置引导，帮助用户理解当前通知 App 的配置流程。引导只用于展示，不参与保存、验证或发送逻辑。

示例：

```yaml
setup_guide:
  type: html
  assets:
    zh: guides/setup.zh-CN.html
    en: guides/setup.en-US.html
```

约定：

- `type` 当前只支持 `html`。
- `assets` 的 key 使用语言标识。内置 UI 当前会优先读取当前语言对应的内容，再回退到另一个语言或第一个可用资源。
- asset 路径必须是相对 `plugin.yaml` 的路径，不能使用绝对路径、`..`、`file://` 或远程 URL。
- HTML 应是静态说明文档。不要写入 `<script>`、`iframe`、表单、内联事件或远程 JS/CSS。
- App 会用 sandbox iframe 展示 HTML，插件 HTML 不能调用 Tauri API，也不能读取或修改主应用状态。

## Python Descriptor 规范

`entrypoints.python_descriptor` 指向的函数必须返回 `core.notifications.registry.NotificationPluginDescriptor`。

示例：

```python
from core.notifications.events import NotificationEvent, format_notification_text
from core.notifications.registry import NotificationPluginDescriptor
from core.notifications.router import NotificationSendResult


class WeChatNotificationChannel:
    name = "wechat"

    def __init__(self, *, webhook_url: str):
        self.webhook_url = str(webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("webhook_url is required")

    async def send(self, event: NotificationEvent) -> NotificationSendResult:
        text = format_notification_text(event)
        # 调用目标 App / webhook 发送 text。
        # 真实实现需要捕获请求异常并返回 error，避免影响主业务流程。
        return NotificationSendResult(channel=self.name, success=True)


def create_wechat_channel(**kwargs) -> WeChatNotificationChannel:
    config = kwargs.get("config") if isinstance(kwargs.get("config"), dict) else {}
    return WeChatNotificationChannel(
        webhook_url=config.get("webhook_url"),
    )


def create_notification_descriptor() -> NotificationPluginDescriptor:
    return NotificationPluginDescriptor(
        name="wechat",
        label="WeChat",
        default_enabled=False,
        channel_factory=create_wechat_channel,
    )
```

最低要求：

- `NotificationPluginDescriptor.name` 必须等于 `plugin.yaml` 的 `id`。
- `channel_factory` 创建的 channel 必须有稳定的 `name`。
- channel 必须提供 `send(event)`，可以是 async 方法，也可以返回 awaitable。
- `send(event)` 成功时返回 `True` 或 `NotificationSendResult(success=True)`。
- 失败时返回 `False`、`NotificationSendResult(success=False, error=...)`，或抛异常；router 会把该渠道视为发送失败。
- 插件发送失败不能让主业务中断。需要把错误放进 `NotificationSendResult.error`，方便日志诊断。

## 通知事件

共享 runtime 只向通知插件传递 `NotificationEvent`：

```python
NotificationEvent(
    status="needs_action" | "failed" | "completed",
    agent_name="Codex",
    task_name="Phase 6",
    message="任务已完成",
    task_id="turn-123",
    agent_id="codex",
)
```

字段语义：

| 字段 | 说明 |
|------|------|
| `status` | 通知状态。当前只支持 `needs_action`、`failed`、`completed`。 |
| `agent_name` | 用户可读的 Agent 名称，例如 `Codex`、`Claude`。 |
| `task_name` | 用户可读的任务名称。通常来自 thread preview 或 workspace 名称。 |
| `message` | 简短通知内容。不要放完整回复、长日志或大段上下文。 |
| `task_id` | 当前任务/turn 的稳定 ID。不同 turn 应使用不同 ID。 |
| `agent_id` | 稳定 Agent ID，例如 `codex`、`claude`。 |

默认展示文案：

```python
from core.notifications.events import format_notification_text

text = format_notification_text(event)
```

输出格式：

```text
完成 · Codex · Phase 6
任务已完成
```

## 去重规则

核心去重键：

```text
task_id:agent_id:status
```

默认去重窗口是 **5 分钟**。也就是说：

- 同一个 task / agent / status 在 5 分钟内重复到达，只发送一次。
- 不同 `task_id` 的会话或 turn 完成通知都会发送。
- 同一个 `task_id` 的 `needs_action`、`failed`、`completed` 属于不同 status，可以分别发送。
- 这个规则只用于防止 stream 重放、重复回调和短时间重复事件，不用于长期屏蔽会话完成通知。

如果测试需要关闭或调整去重窗口，可以直接构造 router：

```python
router = NotificationRouter(channels=[channel], ttl_seconds=0)
router = NotificationRouter(channels=[channel], ttl_seconds=60)
```

## 运行态加载

运行态挂载：

```bash
ONLINEWORKER_NOTIFICATION_OVERLAY=/path/to/notification-plugins /path/to/python3 main.py
```

注意：

- `ONLINEWORKER_NOTIFICATION_OVERLAY` 可以指向单个 `plugin.yaml`，也可以指向目录；目录会递归扫描 `plugin.yaml`。
- 多个 overlay 路径使用系统路径分隔符连接，macOS 上是 `:`。
- `ONLINEWORKER_NOTIFICATION_OVERLAY` 只读进程环境变量，不从 App `.env` 读取。
- App 会读取 notification manifest，并在一级 `Notifications` 页面展示渠道列表与配置表单。
- Python 运行时会通过同一个 manifest entrypoint 加载 channel factory。

## App UI 约定

通知配置入口在一级 `Notifications / 通知` 页面。

UI 行为：

- 左侧列表展示支持的通知渠道。
- 已启用渠道会在左侧高亮状态。
- 右侧展示当前渠道的配置字段。
- 渠道启用开关只保留在右侧详情区。
- 配置字段由 `settings.fields` 自动渲染。
- App 保存配置后，如果 bot service 正在运行，会触发 service restart 让 Python sidecar 读取新配置。

多语言：

- 内置插件的字段 label / description 可以在 App i18n 中覆盖。
- 外部插件默认使用 manifest 中的 `label` / `description`。

## Telegram 插件注意事项

内置 Telegram notification plugin 使用独立 Bot 发送私聊通知，需要配置：

- `bot_token`
- `recipient_user_id`

Telegram Bot API 有平台限制：

- bot 不能主动给从未和它开始过会话的用户发私聊。
- 用户必须先打开这个 bot，点 `/start` 或发送任意消息。
- 如果没做这一步，发送会失败，常见错误是 `Forbidden: bot can't initiate conversation with a user`。

这个限制不是 OnlineWorker 配置问题，也不是 router 未触发；属于 Telegram 平台规则。

## 测试清单

新增或修改 notification plugin 后，至少执行：

```bash
rtk pytest -q tests/test_notifications.py tests/test_config.py -k notification
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --lib
node --test mac-app/tests/appShell.test.mjs
npm --prefix mac-app run build
```

也可以使用并发快验证：

```bash
scripts/verify-fast.sh
```

如果插件改变真实外部发送行为，还需要用该渠道的测试账号或沙箱执行最小 smoke：

```python
from core.notifications import NotificationEvent, build_notification_router

event = NotificationEvent(
    status="completed",
    agent_name="Codex",
    task_name="notification smoke",
    message="test",
    task_id="smoke-unique-id",
    agent_id="codex",
)
result = await router.notify(event)
```

验收标准：

- manifest 能被 App 读取并展示。
- 配置保存后能进入 `config.yaml` 的 `notifications.channels.<id>.config`。
- `build_notification_router(config).list_channels()` 能看到启用渠道。
- 成功发送返回 `sent=True`。
- 失败发送能在 `NotificationResult.errors` 或日志中看到渠道错误。
- 5 分钟内重复的同一 `{task_id, agent_id, status}` 不重复发送。
