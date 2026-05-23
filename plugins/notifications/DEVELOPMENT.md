# Notification Plugin 开发规范

本文档定义 OnlineWorker notification plugin 的最小开发约定。目标是让新通知渠道可以被 App 发现、配置和运行时加载，同时不把 Telegram、微信或其他 App 的发送细节写进共享通知路由。

## 适用范围

- notification 类型插件，`plugin.yaml` 中必须声明 `kind: notification`。
- 当前仓库内置通知插件位于 `plugins/notifications/builtin/`。
- 外部通知插件可以通过 `ONLINEWORKER_NOTIFICATION_OVERLAY` 在运行态挂载。

provider 插件开发规则见 [../providers/DEVELOPMENT.md](../providers/DEVELOPMENT.md)。

## 目录结构

推荐结构如下：

```text
my-notifier/
├── __init__.py
├── plugin.yaml
└── python/
    ├── __init__.py
    └── channel.py
```

约定：

- `plugin.yaml` 是 App 设置页、配置归一化和 Python loader 的稳定入口。
- `python/channel.py` 推荐只实现通知渠道发送逻辑，不反向依赖 provider、Telegram handler 或 UI。
- 外部 overlay 的 Python import root 是 `plugin.yaml` 所在目录的父目录。例如 `/path/notification-plugins/wechat/plugin.yaml` 会把 `/path/notification-plugins` 加入 `sys.path`。

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

settings:
  fields:
    - key: webhook_url
      label: Webhook URL
      type: string
      required: true
      default: ""
      description: WeChat robot webhook used by this notification channel.

entrypoints:
  python_descriptor: wechat.python.channel:create_notification_descriptor
```

字段约定：

- `schema_version`: 当前使用 `1`。
- `id`: 通知渠道公开 ID。必须稳定，必须和 `NotificationPluginDescriptor.name` 一致。
- `kind`: 必须是 `notification`。
- `visibility`: 外部插件建议使用 `private`；内置插件可使用 `public`。
- `order`: App 设置页排序。内置插件使用较小值，外部插件建议从 `100` 起。
- `label` / `description`: UI 展示文案。
- `default_enabled`: 首次归一化配置时是否默认开启。
- `settings.fields`: App 通知页渲染的插件配置字段。当前支持 `string`、`number`、`boolean`、`select`、`secret`；这里暂不做敏感字段特殊存储，`secret` 仅表示 UI 使用 password 输入框。
- `entrypoints.python_descriptor`: Python descriptor 工厂，必须是 `module:function` 格式。

不要在 `plugin.yaml` 中写入真实 token、webhook endpoint 或本地用户路径。需要用户填写的字段通过 `settings.fields` 声明，值由 App 保存到 `config.yaml` 的 `notifications.channels.<id>.config`。

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
        self.webhook_url = webhook_url

    async def send(self, event: NotificationEvent) -> NotificationSendResult:
        text = format_notification_text(event)
        # 调用微信机器人 webhook 发送 text。
        return NotificationSendResult(channel=self.name, success=True)


def create_wechat_channel(**kwargs) -> WeChatNotificationChannel:
    config = kwargs.get("config") if isinstance(kwargs.get("config"), dict) else {}
    return WeChatNotificationChannel(webhook_url=str(config.get("webhook_url") or ""))


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
- channel 必须提供 `send(event)`，可以是 async 方法。
- `send(event)` 成功时返回 `True` 或 `NotificationSendResult(success=True)`。
- 失败时返回 `False`、`NotificationSendResult(success=False, error=...)`，或抛异常；router 会把该渠道视为发送失败。

## 通知事件

共享 runtime 只向通知插件传递 `NotificationEvent`：

```python
NotificationEvent(
    status="needs_action" | "failed" | "completed",
    agent_name="Codex",
    task_name="Phase 6",
    message="需要处理",
    task_id="task-1",
    agent_id="codex-1",
)
```

约定：

- 通知内容保持简短，插件不应主动拼接完整任务上下文。
- 展示文案可直接使用 `format_notification_text(event)`。
- 去重键由核心事件提供：`task_id:agent_id:status`。
- 默认 TTL 为 24 小时；相同 `{task_id, agent_id, status}` 不应重复发送。

## Overlay 开发

运行态挂载：

```bash
ONLINEWORKER_NOTIFICATION_OVERLAY=/path/to/notification-plugins /path/to/python3 main.py
```

注意：

- `ONLINEWORKER_NOTIFICATION_OVERLAY` 可以指向单个 `plugin.yaml`，也可以指向目录；目录会递归扫描 `plugin.yaml`。
- 多个 overlay 路径使用系统路径分隔符连接，macOS 上是 `:`。
- `ONLINEWORKER_NOTIFICATION_OVERLAY` 只读进程环境变量，不从 App `.env` 读取。
- App 会读取 notification manifest，并在一级 `Notifications` 页面展示渠道列表与配置表单。
- 渠道开关保存在 `config.yaml` 的 `notifications.channels.<id>.enabled`。
- 插件配置值保存在 `config.yaml` 的 `notifications.channels.<id>.config`，由 `channel_factory(config=...)` 接收。

## 测试清单

新增或修改 notification plugin 后，至少执行：

```bash
/path/to/python3 -m pytest -q tests/test_notifications.py tests/test_config.py -k notification
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --lib
node --test mac-app/tests/appShell.test.mjs
npm --prefix mac-app run build
```

如果插件改变真实外部发送行为，还需要用该渠道的测试账号或沙箱执行最小 smoke，并确认重复通知不会在 24 小时 TTL 内反复发送。
