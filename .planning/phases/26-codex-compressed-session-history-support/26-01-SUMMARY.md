---
phase: 26
plan: 01
status: complete
requirements: [HIST-01, HIST-02, HIST-03]
---

# 26-01: Codex 压缩会话历史读取

## Delivered

- 生产适配仅修改 Codex 插件的 `storage_runtime.py` 和 `tui_realtime_mirror.py` 启动历史补齐入口；`core/`、hook、app-server 和实时消息发送链路没有变更。
- 启动历史保留 `phase`、`timestamp` 和 `displayMode`，最终回复使用 Markdown、进度消息使用纯文本；完整历史合并后展示字段保持完整。
- 历史读取显式启用 `.jsonl.zst` 查找，普通 JSONL 优先；现有文件增量消费者继续使用原有默认查找行为。
- 历史、元数据和终态读取复用流式文本解压及既有解析器，保留角色、phase、时间戳和去重。
- 批量列表继续使用既有 SQLite 元数据与普通 JSONL 索引，压缩历史按会话读取。
- 解压/读取异常通过既有 owner bridge 查询失败通道报告，失败不会用空历史覆盖总线已有消息。
- `requirements.txt` 声明 `zstandard==0.25.0`；未添加外部解压 CLI 或临时历史落盘。

## Verification

以下命令均从项目根目录运行：

```bash
PYTHONPATH="$PWD" rtk pytest tests/test_storage.py tests/test_storage_extended.py plugins/providers/builtin/codex/tests/test_compressed_history.py -q
# 45 passed

PYTHONPATH="$PWD" rtk pytest plugins/providers/builtin/codex/tests/test_compressed_history.py tests/test_codex_tui_realtime_mirror.py tests/test_codex_external_ingress.py -q
# 38 passed, 3 failed; compressed-history cases all pass

git diff --check
# passed
git diff --name-only -- core
# empty
```

相关实时失败均已将存储模块替换为 Git HEAD 版本后单独复现：

- `test_primary_hook_arms_one_active_kqueue_watch_for_commentary`：基线实际 payload 已包含 `item_id: None`，测试期待值未包含该字段。
- `test_desktop_rollout_completion_enters_bus_without_topic`：基线等待通知事件超时。
- `test_new_desktop_rollout_file_is_discovered_without_session_polling`：基线等待 rollout 事件超时。

只读原始场景验证：使用 sidecar 的 Python 运行时，历史读取与现有 owner bridge / MessageEventBus 会话快照均得到 50 条消息。个人会话标识和内容未写入本记录。

## Installed Verification

2026-10-08 用户明确授权后，从组合仓库根目录执行 `bash verify-packaged-fast.sh`：退出码 0，耗时 107 秒。生成 `OnlineWorker_1.11.0_aarch64.dmg`，覆盖并重启 `/Applications/OnlineWorker.app`，App 和主 Bot 进程均从安装目录运行。

安装版 `session_event_stream` 对原压缩会话返回 `replace_snapshot`，包含 50 条消息（用户 18、助手 32），`error` 为 null；`provider_plugin_load_failures` 返回空列表。这同时验证了 sidecar 自带解压能力和既有消息总线初始快照路径。

同日补齐启动历史展示字段后，定向 Python 回归通过 24 项，前端消息模型与 Markdown 渲染回归通过 16 项；额外渲染检查确认粗体、行内代码和列表生成正确 HTML。`git diff --check` 通过。

第二次从组合仓库根目录执行 `bash verify-packaged-fast.sh`：退出码 0，耗时 106 秒。安装版启动补齐的 6 条消息展示字段完整，完整历史初始快照为 50 条（Markdown 助手消息 16、纯文本进度消息 18）。此前未高亮的两条最终回复均带 Markdown 标记，安装版页面已确认粗体、行内代码和列表正常展示；插件加载失败列表为空。没有发送测试聊天消息。

## Boundaries

上述既有实时回归失败保持基线记录，不作为已修复项。本阶段已验证压缩历史读取、消息总线快照、启动历史展示字段及对应最终回复的安装版渲染；未扩大到无关功能验收或修改 TG 发送链路。
