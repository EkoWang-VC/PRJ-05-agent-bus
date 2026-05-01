---
tags:
  - vibe-coding/workflow
  - agent-bus
  - capabilities
created: 2026-05-02
updated: 2026-05-02
status: draft
---

# AGENT-BUS Capability Matrix

> 本文档回答两个问题：`registry.json` 里每个 capability 到底代表什么，以及当前各 agent 的运行边界在哪里。

## 一、字段解释

### 1. `capabilities`

- 面向人读的能力标签
- 用来表达“适合做什么”
- 不是权限系统，也不是严格 SLA

当前已使用的 capability 含义：

- `planning`
  - 适合做任务拆解、主流程路由、推进建议
- `verification`
  - 适合做验证、复核、验收前检查
- `routing`
  - 适合担当主路由节点，把结果再发往其他 agent
- `coding`
  - 适合实现代码、修测试、局部重构
- `review`
  - 适合代码审查、风险扫描、修改建议
- `analysis`
  - 适合非代码分析、结构化判断、策略评估
- `research`
  - 适合调研、材料汇总、比较分析
- `writing`
  - 适合输出 Markdown 报告、研判文本、交付文档
- `deep-reasoning`
  - 适合复杂中文推理、策略讨论、结论组织
- `generic-markdown-output`
  - 适配 `worker_common.py` 的通用 response 逻辑
- `structured-decision-output`
  - 适配 `gemini_worker.py` 的特化决策输出逻辑
- `deepseek-env-injection`
  - 依赖专门的子进程环境注入链路，而不是默认 CLI 环境

### 2. `response_profile`

当前只有两类：

- `generic`
  - 走 `worker_common.py` 的通用 response 结构
  - 适用于 `claude / claude-ds / codex`
- `decision-structured`
  - 走 `gemini_worker.py` 的专用决策分类逻辑
  - 适用于需要按 P1-P6 等规则提取结论的任务

### 3. 运行特征字段

- `supports_watch`
  - 支持 `--watch`
- `supports_invoke_cli`
  - 支持真实 CLI 调用
- `supports_preflight`
  - 支持最小探活请求
- `default_timeout_seconds`
  - 默认 CLI 超时
- `default_lease_ttl_seconds`
  - 默认 lease TTL

## 二、当前矩阵

| agent | worker | profile | watch | invoke-cli | preflight | 适合任务 |
|---|---|---|---|---|---|---|
| `claude` | `scripts/claude_worker.py` | `generic` | yes | yes | yes | 主路由、主审查、综合判断 |
| `claude-ds` | `scripts/claude_ds_worker.py` | `generic` | yes | yes | yes | 中文研究、策略审查、DeepSeek 链路 |
| `codex` | `scripts/codex_worker.py` | `generic` | yes | yes | yes | 编码、修复、代码 review |
| `gemini` | `scripts/gemini_worker.py` | `decision-structured` | yes | yes | yes | 调研、评估、结构化决策 |
| `qwencode` | none | `none` | no | no | no | 预留，当前不可用 |

## 三、适用边界

### `claude`

强项：

- 主流程协调
- 通用 Markdown 输出
- 主状态推进建议

边界：

- 当前没有专用结构化决策提取逻辑
- 更适合“看结论 + 看完整性”，不适合特定格式归类任务

### `claude-ds`

强项：

- 中文语境下的研究和策略审查
- 独立路由
- DeepSeek 兼容环境封装

边界：

- 非交互能力仍受底层 `claude` CLI 行为影响
- 不是完全独立的 runtime

### `codex`

强项：

- 代码修改
- 测试修复
- 自动化实现

边界：

- 当前 response 仍按通用 Markdown 逻辑判断
- 没有单独的代码级 schema

### `gemini`

强项：

- 内容评估
- 结构化决策提取
- P1-P6 一类规则型结论归类

边界：

- 逻辑比通用 worker 更特化
- 不适合拿来做完全自由格式的主审查链路

### `qwencode`

当前状态：

- 仅保留 registry 占位
- 没有对应 worker
- 不应参与 bus 调度

## 四、当前建议分工

- `claude`
  - 主任务协调、总审查、总判断
- `claude-ds`
  - 中文策略分析、研究补充、DeepSeek 风格链路
- `codex`
  - 实现与修复
- `gemini`
  - 并行调研、规则归类、结构化内容评估

## 五、为什么要把 registry 补到这一层

因为仅靠：

- `agent_id`
- `capabilities`
- `domains`

还不够支撑运行期判断。实际协作里还需要知道：

- 有没有 worker
- 能不能 watch
- 能不能 invoke-cli
- response 是通用型还是特化型

所以当前 `registry.json` 的定位已经从“静态名片”升级成“轻量运行清单”。
