---
sketch: 003
name: account-session-assets
question: "会话资产应采用整块工作台还是工程卡片流，才能兼顾扫描信息、批量操作和项目识别？"
winner: "C"
tags: [account, session-assets, layout, grouped-list, responsive]
---

# Sketch 003: Account Session Assets

## Design Question

会话资产应采用整块工作台还是工程卡片流，才能兼顾扫描信息、批量操作和项目识别？

## How to View

```bash
open .planning/sketches/003-account-session-assets/index.html
```

## Variants

- **A: 整块会话工作台** — 合并摘要、搜索、上下文批量操作和带嵌套会话的工作目录列表，信息密度接近 Cockpit。
- **B: 工程卡片流** — 两列项目卡直接露出最近会话，项目识别更强，但会话选择粒度不足。
- **C: 卡片流 + 选择弹窗（已选）** — 保留 B 的工程卡片，点击卡片底部按钮后在弹窗内搜索、全选和逐条选择会话。

## What to Look For

- 30 天摘要是否仍然清楚，但不再像六张互不相关的小卡片。
- 搜索和低频操作是否有主次；未选择时不常驻红色危险按钮。
- 工作目录是否容易扫读；展开后的 conversation 是否仍保持二级结构。
- C 是否同时保留 B 的项目识别感和 A 的会话选择能力。
