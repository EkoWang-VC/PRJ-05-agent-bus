---
tags:
  - vibe-coding/workflow
  - agent-bus
created: 2026-05-01
updated: 2026-05-01
status: review-candidate
---

# AGENT-BUS

> `AGENT-BUS` 是 `Vibe Coding` 域内的跨终端 Agent 通信层独立项目，用于把 `TASK-QUEUE` 下的 Agent 交接从文档级推进到脚本级。

当前仓库定位：

- 独立项目代码仓
- 与 `70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/` 下的流程文档联动
- 当前版本 `v0.1.0`
- 当前阶段：`待 Claude 首轮审查`

工作流侧入口：

- 任务卡：
  `70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/Task-Specs/TASK-20260501-PRJ05-01-AGENT-BUS独立项目审查.md`
- Claude handoff：
  `70-Vibe Coding (Vibe Coding)/99-Agents (Agents)/Codex/logs/2026-05-01-PRJ05-AGENT-BUS-CLAUDE-HANDOFF.md`
- 系统总队列：
  `99-系统(System)/WORKFLOW/TASK-QUEUE.md`

当前状态：

- 已完成目录与 schema 草案
- 已完成最小脚本原型：
  - `scripts/create_request.py`
  - `scripts/check_response.py`
- 已完成离线 worker 原型：
  - `scripts/gemini_worker.py`
- 已完成最小轮询模式（Gemini）
- 已接入可选 Gemini CLI 调用（`--invoke-cli`）
- 已接入 preflight 探活（`--preflight`）
- 已接入队列汇总器：
  - `scripts/queue_sync.py`
- 已形成多 Agent 原型：
  - `scripts/claude_worker.py`
  - `scripts/claude_ds_worker.py`
  - `scripts/codex_worker.py`
  - `scripts/gemini_worker.py`

## 目录说明

- `registry.json`
  Agent 注册表
- `scripts/create_request.py`
  从任务卡生成 bus request
- `scripts/check_response.py`
  从 response 生成队列推进建议摘要
- `scripts/gemini_worker.py`
  离线处理 Gemini request，并根据已有产出文件自动生成 response；支持 `--watch`、`--invoke-cli`、`--preflight`
- `scripts/claude_worker.py`
  Claude 的通用 CLI worker 原型
- `scripts/claude_ds_worker.py`
  Claude-DS 的独立 CLI worker 原型；默认直接调用 `claude`，并仅在 Claude 子进程级注入 DeepSeek 兼容环境，单独占用 `claude-ds` 路由、lease 和 response
- `scripts/codex_worker.py`
  Codex 的通用 CLI worker 原型
- `scripts/worker_common.py`
  Claude / Claude-DS / Codex 共用的多 Agent worker 核心
- `scripts/queue_sync.py`
  读取 `responses/`，生成面向 `TASK-QUEUE` 的推进建议报告
- `examples/request.example.json`
  请求样例
- `examples/response.example.json`
  响应样例
- `requests/`
  预留：待处理请求
- `responses/`
  预留：已完成响应
- `leases/`
  预留：锁、租约、心跳

## 多 Agent 说明

- `claude`
  通用 Claude 执行器，适合主审查、主路由、综合判断
- `claude-ds`
  独立的 Claude-DS 执行器，语义上代表“单独启动的 Claude + DeepSeek 风格分析链路”
  - 默认通过 `claude` CLI + DeepSeek 环境注入启动
  - worker 会主动清理代理环境，并仅在 Claude 子进程的 `env` 中将 `DEEPSEEK_API_KEY` 映射为当前 Claude CLI 可识别的 `ANTHROPIC_API_KEY`
  - 可用 `--cli-bin` 指向未来的专用二进制或封装脚本
  - 可用 `--claude-agent-name` 绑定已有 Claude custom agent
- `gemini`
  研究 / 内容 / 并行评估
- `codex`
  编码 / 审查 / 自动化实现

## 对外关系

- 高层任务入口：`../TASK-QUEUE.md`
- 架构说明：`docs/architecture.md`
- 工作流集成：`docs/workflow-integration.md`

## 当前建议用法

当前仍是原型仓，但已经进入项目化管理和可审查状态。

### 最小原型命令

```bash
# 在 agent-bus 仓库根目录运行
python3 scripts/create_request.py \
  "/absolute/path/to/Task-Specs/CONTENT-20260504-02.md"

python3 scripts/check_response.py \
  "responses/REQ-20260501-001-CONTENT-20260504-02.json"

python3 scripts/gemini_worker.py \
  "requests/REQ-TEST-20260501-CONTENT-20260504-02.json" \
  --output-root "."

python3 scripts/gemini_worker.py \
  --watch --once --poll-seconds 1 --output-root "."

python3 scripts/gemini_worker.py \
  "requests/REQ-TEST-20260501-CONTENT-20260504-02.json" \
  --output-root "." --invoke-cli --preflight --model "gemini-3.1-pro-preview" --timeout-seconds 45

python3 scripts/queue_sync.py

python3 scripts/claude_worker.py \
  --watch --once --poll-seconds 1 --output-root "."

python3 scripts/claude_ds_worker.py \
  --watch --once --poll-seconds 1 --output-root "."

python3 scripts/codex_worker.py \
  --watch --once --poll-seconds 1 --output-root "."
```
