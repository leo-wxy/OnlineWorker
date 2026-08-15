# Phase 22: Dark Mode Support - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-15
**Phase:** 22-Dark Mode Support
**Areas discussed:** 主题切换规则与入口、暗色视觉基调、覆盖与系统联动

---

## 主题切换规则与入口

### 主题模式

| Option | Description | Selected |
|--------|-------------|----------|
| 仅跟随 macOS | 不提供手动覆盖 | |
| System / Light / Dark | 三档选择并持久化 | ✓ |
| Light / Dark 开关 | 两档手动切换 | |

**User's choice:** `System / Light / Dark`。用户最初误选第一项，随后明确纠正为第二项。
**Notes:** 首次启动默认 `System`，运行期间实时跟随 macOS。

### 选择器位置

| Option | Description | Selected |
|--------|-------------|----------|
| 侧栏语言选择器旁 | 复用现有侧栏，不新增页面 | ✓ |
| Settings → OnlineWorker | 放入设置页 | |
| macOS 应用菜单 | 只从原生菜单切换 | |

**User's choice:** 放在侧栏语言选择器旁。
**Notes:** 侧栏收起时隐藏主题选择器，需要切换时先展开侧栏。

---

## 暗色视觉基调

| Option | Description | Selected |
|--------|-------------|----------|
| 深蓝灰玻璃 | 深蓝灰半透明表面、克制语义色、柔和层次 | ✓ |
| 近黑 OLED | 接近纯黑、对比更强 | |
| 平面石墨 | 减少透明与阴影、偏平面 | |

**User's choice:** 第一张深蓝灰玻璃效果图。
**Notes:** 用户认为该方案“整体色调更和谐”。随后确认：

- menubar 展开面板同步相同视觉语言，保留现有内容与动作。
- 浅色模式也使用同一套层级、圆角、边框和语义色。
- 第一版浅色效果图改变了当前格式，用户指出偏差；修正版锁定为保留当前布局，只调整颜色、材质和主题控件。

---

## 覆盖与系统联动

### 覆盖范围

| Option | Description | Selected |
|--------|-------------|----------|
| 全覆盖 | 所有现有页面、表单、弹窗、交互状态及 menubar | ✓ |
| 常用页面 + menubar | 仅高频入口 | |
| Dashboard + menubar | 最小页面范围 | |

**User's choice:** 全覆盖。
**Notes:** 不改变现有业务行为和布局。

### 系统主题变化

| Option | Description | Selected |
|--------|-------------|----------|
| 立即同步 | 主窗口与 menubar 运行时同步 | ✓ |
| 下次打开窗口时同步 | 延迟到窗口重开 | |
| 重启应用后同步 | 延迟到进程重启 | |

**User's choice:** 立即同步。
**Notes:** `System` 模式是默认值。

### 首帧处理

| Option | Description | Selected |
|--------|-------------|----------|
| 首帧前应用 | 避免亮色闪屏 | ✓ |
| 页面加载后切换 | 允许短暂错色 | |
| 不专门处理 | 无防闪保证 | |

**User's choice:** 首帧前应用。
**Notes:** 持久化偏好和系统模式都需要覆盖。

### 手动切换过渡

| Option | Description | Selected |
|--------|-------------|----------|
| 立即切换 | 不加全局动画 | |
| 约 150ms 颜色淡变 | 只过渡颜色、背景、边框与阴影 | ✓ |
| 整窗淡入淡出 | 整个窗口动画 | |

**User's choice:** 约 `150ms` 的颜色淡变。
**Notes:** 不做整窗动画，并保留减少动态效果兼容性。

---

## the agent's Discretion

- 精确主题 token 数值和持久化键名。
- 在 Tauri 既有主题 API 与浏览器主题监听之间选择最小可靠实现。
- 测试文件拆分方式，但需覆盖持久化、系统跟随、首帧和 menubar 同步。

## Deferred Ideas

None.
