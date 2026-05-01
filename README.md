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
  读取 `requests/` + `responses/`，生成面向 `TASK-QUEUE` 的推进建议报告，并标记孤儿 request / 幽灵 response
- `examples/request.example.json`
  请求样例
- `examples/response.example.json`
  响应样例
- `requests/`
  预留：待处理请求
- `responses/`
  预留：已完成响应
- `leases/`
  锁、租约、pid 文件；worker 默认写入 JSON lease/pid 元数据

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
- 能力矩阵：`docs/capabilities.md`
- 运维手册：`docs/operations.md`

## 当前建议用法

当前仍是原型仓，但已经进入项目化管理和可审查状态。

### Lease 与 Watch 约定

- lease 文件路径：
  `leases/<request_id>.<agent>.lock`
- lease 文件内容：
  JSON，至少包含
  - `request_id`
  - `handled_by`
  - `pid`
  - `created_at`
  - `expires_at`
  - `lease_ttl_seconds`
- 默认 `lease_ttl_seconds = 60`
- 若旧 lease 已过期，worker 会自动回收后重新认领 request
- watch 模式默认写入 pid 文件：
  - `leases/claude.pid`
  - `leases/claude-ds.pid`
  - `leases/codex.pid`
  - `leases/gemini.pid`
- watch 模式支持 `SIGINT` / `SIGTERM` 优雅退出，当前轮扫描结束后会主动清理 pid 文件

### 最小原型命令

```bash
# 在 agent-bus 仓库根目录运行
make test

make smoke

make smoke-cli AGENT=claude REQUEST=requests/REQ-XXX.json

make smoke-cli-example AGENT=claude

python3 scripts/create_request.py \
  "/absolute/path/to/Task-Specs/CONTENT-20260504-02.md"

python3 scripts/check_response.py \
  "responses/REQ-20260501-001-CONTENT-20260504-02.json"

python3 scripts/gemini_worker.py \
  "requests/REQ-TEST-20260501-CONTENT-20260504-02.json" \
  --output-root "."

python3 scripts/gemini_worker.py \
  --watch --once --poll-seconds 1 --output-root "." --lease-ttl-seconds 60

python3 scripts/gemini_worker.py \
  "requests/REQ-TEST-20260501-CONTENT-20260504-02.json" \
  --output-root "." --invoke-cli --preflight --model "gemini-3.1-pro-preview" --timeout-seconds 45

python3 scripts/queue_sync.py

python3 -m unittest discover -s tests -q

python3 scripts/claude_worker.py \
  --watch --once --poll-seconds 1 --output-root "." --lease-ttl-seconds 60

python3 scripts/claude_ds_worker.py \
  --watch --once --poll-seconds 1 --output-root "." --lease-ttl-seconds 60

python3 scripts/codex_worker.py \
  --watch --once --poll-seconds 1 --output-root "." --lease-ttl-seconds 60
```

### 统一验证入口

- `make test`
  - 运行当前全部 `unittest` 回归
- `make smoke`
  - 先跑 `make test`
  - 再跑一次 `queue_sync.py`
  - 默认把 smoke 报告写到 `/tmp/agent-bus-queue-sync-smoke.md`
- `make smoke-cli AGENT=<agent> REQUEST=<request-json>`
  - 统一触发真实 CLI smoke
  - 当前支持：`claude` / `claude-ds` / `codex` / `gemini`
  - 默认附带 `--invoke-cli --preflight --timeout-seconds 45`
  - 可选变量：
    - `OUTPUT_ROOT=...`
    - `RESPONSE_OUT=...`
    - `MODEL=...`
    - `TIMEOUT=...`
    - `EXTRA_ARGS='...'`
- `make smoke-cli-example AGENT=<agent>`
  - 复用仓库内置的最小示例 request：
    [examples/smoke-cli.request.json](/Users/ekowang/Library/CloudStorage/OneDrive-个人/应用/remotely-save/个人/70-Vibe%20Coding%20(Vibe%20Coding)/06-%E4%BB%A3%E7%A0%81%E5%BA%93%20(Code%20Repository)/agent-bus/examples/smoke-cli.request.json:1)
  - 默认产出 Markdown 会写到 `examples/outputs/smoke-cli-output.md`
  - `AGENT` 决定实际调用哪个 worker，示例 request 本身只作为最小输入载体

### Queue Sync 约定

- `queue_sync.py` 会同时读取 `requests/` 与 `responses/`
- `孤儿 request`
  - request 存在，但还没有同名 `response`
- `幽灵 response`
  - response 存在，但没有对应 request
- 这两个状态都只做报告，不直接改写任何队列文件
