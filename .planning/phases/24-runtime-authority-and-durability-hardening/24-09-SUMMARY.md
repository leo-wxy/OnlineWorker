---
phase: 24
plan: 09
status: completed
completed_at: "2026-09-05T10:33:45+08:00"
fast_packaged_verified_at: "2026-09-05T10:39:34+08:00"
---

# 24-09 Summary: 精简重复基础逻辑与失效入口

## 完成内容

- 前端删除无调用的 `RUNNING_STATUSES`、`formatTokenCount`、`createProviderSession`，合并 Task Board 相同结果分支。保留 Rust `create_provider_session` command。
- `bot/interaction_specs.py` 通过别名导入复用 core registry 的 wrapper 能力查询；自定义 provider 测试改为临时注册 provider，覆盖能力与 hook 的真实查找路径。
- `provider_bridge_common.rs` 统一 CLI 首 token、HOME 展开与 PATH 工具；service 直接复用现有 sidecar 环境。保留配置入口双端 trim 与其他入口 trim_start 的差别，迁移环境回归并合并空白值断言。
- `config.rs` 六个 setter 共用 `update_config_document`。读取、normalize、业务修改、序列化、原子写入顺序不变。
- `provider_sessions.rs` 六个请求共用 `request_owner_bridge`。各入口 payload、返回包装、连接超时和 fallback 条件不变，新增请求分帧、写端关闭、失败/缺失 ok、无效 JSON 与 EOF 回归。

生产源码净减 **342 行**；含代码与测试的差异为 **+276 / -553，净减 277 行**，不含 planning 文档。生产源码统计排除 Python tests 和 Rust 尾部 `cfg(test) mod tests`。

## 验证

| 命令 | 结果 |
|---|---|
| `rtk proxy python -m pytest -q tests/test_slash_router.py tests/test_thread_controls.py` | 43 passed |
| `rtk proxy node --test mac-app/tests/taskBoard.test.mjs mac-app/tests/sessionNewComposer.test.mjs mac-app/tests/menubarPopover.test.mjs` | 40 passed |
| `rtk proxy ./mac-app/node_modules/.bin/tsc -p mac-app/tsconfig.json --noEmit` | 通过 |
| `rtk proxy cargo test --manifest-path mac-app/src-tauri/Cargo.toml --lib -- --test-threads=1` | 256 passed，0 failed，无编译警告 |
| `rtk proxy cargo fmt --manifest-path mac-app/src-tauri/Cargo.toml --all -- --check` | 通过 |
| `rtk proxy git diff --check` | 通过 |

首轮 Rust 测试在沙箱中因本地 socket 与进程检查权限失败（231 passed、25 failed）；获得本地测试权限后，同一命令完整通过。该过程未启动、安装或重启打包 App。

独立静态复核未发现本次精简引入的行为回归。涉及进程环境的既有测试继续按仓库已有命令串行执行，不新增测试并发控制框架。

## 快速打包验证（2026-09-05，后续明确授权）

- `rtk proxy bash scripts/verify-packaged-fast.sh` 退出 `0`，耗时 `94s`。
- `VERSION`、package.json、Cargo.toml、tauri.conf.json 一致为 `1.10.0`；Python bot 与 ccusage sidecar、前端和 Rust release 构建完成。
- 产物：`mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.10.0_aarch64.dmg`。
- 已覆盖 `/Applications/OnlineWorker.app` 并重启。补充精确进程检查确认 app 和主 bot 均从安装目录运行，未把账号 worker 或会话 bridge 辅助进程计作主服务。
- 快速安装与启动验证通过；未执行功能 UAT、跨 owner interrupt 验证或完整发布验证链。

## 保留边界

- 本切片完成时 24-07 为 blocked、Phase 24 为 source_partial；随后用户批准将 24-07 延期并归档 Phase 24，见 [24-ARCHIVE.md](24-ARCHIVE.md)。外部 owner API 未重新探测。
- 旧 TUI helper、source claim、EventBus/LKG、stream/service generation、原子写入与备份恢复保持。
- IPC 精简只覆盖会话模块的六个等价入口；usage、Task Board、Dashboard 的独立错误处理没有被强行统一。
- 未新增依赖、修改公开合同或手动修改运行时用户配置；未 commit/push。打包、覆盖安装与重启仅在后续明确授权后执行。
- 快速安装与启动已验证；安装版功能 UAT 未验证。
