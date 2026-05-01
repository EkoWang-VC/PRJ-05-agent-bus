---
tags:
  - vibe-coding/workflow
  - agent-bus
  - operations
created: 2026-05-02
updated: 2026-05-02
status: draft
---

# AGENT-BUS 运维手册

> 本文档面向日常使用、排障和交接。目标不是解释设计理念，而是回答“现在怎么跑、失败怎么看、卡住怎么处理”。

## 一、最常用入口

在仓库根目录执行：

```bash
make test
make smoke
make smoke-cli-example AGENT=claude
make smoke-cli AGENT=gemini REQUEST=requests/REQ-XXX.json
```

推荐顺序：

1. `make test`
2. `make smoke`
3. 需要验证真实模型链路时，再跑 `make smoke-cli` 或 `make smoke-cli-example`

## 二、命令用途

### 1. `make test`

- 运行当前全部 `unittest`
- 不依赖外部模型
- 适合改代码后的最快回归

### 2. `make smoke`

- 先跑 `make test`
- 再执行一次 `queue_sync.py`
- 默认输出：
  - `/tmp/agent-bus-queue-sync-smoke.md`

适合确认：

- `tests/` 仍然通过
- `queue_sync.py` 没有被改坏
- 报告输出路径正常

### 3. `make smoke-cli`

示例：

```bash
make smoke-cli AGENT=claude REQUEST=requests/REQ-XXX.json
make smoke-cli AGENT=claude-ds REQUEST=examples/smoke-cli.request.json
make smoke-cli AGENT=gemini REQUEST=examples/smoke-cli.request.json MODEL=gemini-3.1-pro-preview
```

默认行为：

- 统一附带 `--invoke-cli`
- 统一附带 `--preflight`
- 默认 `TIMEOUT=45`
- 默认 response 输出到：
  - `/tmp/agent-bus-cli-smoke-<agent>.json`

可选变量：

- `AGENT`
- `REQUEST`
- `OUTPUT_ROOT`
- `RESPONSE_OUT`
- `MODEL`
- `TIMEOUT`
- `EXTRA_ARGS`

### 4. `make smoke-cli-example`

示例：

```bash
make smoke-cli-example AGENT=claude
make smoke-cli-example AGENT=claude-ds
```

说明：

- 复用仓库内置示例 request：
  - `examples/smoke-cli.request.json`
- 适合先验证“命令链路是否能跑通”
- 不需要手工准备 request 文件

## 三、目录观察点

### 1. `requests/`

- 待处理 request
- 重点看：
  - `to_agent`
  - `output_path`
  - `output_schema.required_sections`

### 2. `responses/`

- 已完成或失败的 response
- 重点看：
  - `status`
  - `handled_by`
  - `error`
  - `error_code`
  - `queue_readiness`

### 3. `leases/`

- lock 与 pid 元数据
- lock 文件格式：
  - `leases/<request_id>.<agent>.lock`
- pid 文件示例：
  - `leases/claude.pid`
  - `leases/claude-ds.pid`
  - `leases/codex.pid`
  - `leases/gemini.pid`

## 四、常见失败码

### 1. `timeout`

含义：

- CLI 在限定时间内没有完成输出

优先排查：

1. prompt 是否过大
2. 模型是否在重试或无响应
3. `TIMEOUT` 是否过短

建议动作：

- 先缩 request
- 再增大 `TIMEOUT`
- 必要时改用更稳定模型

### 2. `model_capacity_exhausted`

含义：

- 服务端模型容量不足

已知情况：

- `gemini-2.5-pro` 之前出现过该问题
- 当前更稳定的是 `gemini-3.1-pro-preview`

建议动作：

- 不要盲目重试同一模型
- 先切换到当前可用模型

### 3. `rate_limited`

含义：

- 被服务端限流

建议动作：

- 等待后重试
- 降低并发
- 缩短 smoke prompt

### 4. `auth_error`

含义：

- 未登录、token 不存在，或认证变量没生效

建议动作：

- 先手工跑最小命令验证 CLI 登录态
- 再检查 worker 的环境注入链路

### 5. `network_error`

含义：

- 网络不可达、代理异常、DNS 失败

建议动作：

- 优先确认本机代理
- 再确认目标 CLI 是否本就需要清代理

### 6. `approval_blocked`

含义：

- CLI 侧权限/审批模式阻塞

建议动作：

- 检查 worker 默认参数
- 尽量维持 `plan` / 非破坏性模式做 smoke

### 7. `cli_error`

含义：

- 已知分类都没命中，但 CLI 仍然失败

建议动作：

- 先看 response 里的 `error`
- 再手工复现最小命令

## 五、Claude-DS 专项说明

`claude-ds` 不是独立 runtime，而是：

- 独立 bus endpoint
- 独立 worker
- 独立路由目标

当前实现特点：

- `claude_ds_worker.py` 只在 Claude 子进程级注入 DeepSeek 兼容环境
- 会主动清理代理环境
- 会把 `DEEPSEEK_API_KEY` 映射为 `ANTHROPIC_API_KEY`

如果 `claude-ds` smoke 失败，优先分两层判断：

1. 路由层是否正确
   - `to_agent` 是否等于 `claude-ds`
   - response 的 `handled_by` 是否等于 `claude-ds`
2. CLI 层是否正确
   - 最小 `claude-ds -p ...` 是否可跑
   - 是否仍然受 shell function / 环境变量污染

## 六、Watch 模式排障

### 1. worker 不消费 request

优先检查：

1. `to_agent` 是否和 worker 名一致
2. 对应 `response` 是否已经存在
3. lease 是否被旧进程占住

### 2. lease 一直不释放

当前机制：

- lease 带 `expires_at`
- 超时后可自动回收

优先检查：

1. `lease_ttl_seconds` 是否过长
2. 进程是否已经退出但旧 lock 还在
3. 系统时间是否异常

### 3. pid 文件残留

正常情况下：

- `SIGINT` / `SIGTERM` 优雅退出后会清理 pid 文件

若残留：

- 说明进程可能被强杀或异常退出
- 先确认实际进程是否已不存在
- 再手动删 pid 文件

## 七、建议排障顺序

遇到问题时，按这个顺序最省时间：

1. `make test`
2. `make smoke`
3. 看 `responses/*.json` 的 `error_code`
4. 看 `leases/` 与 pid 文件
5. 手工跑最小 CLI 命令
6. 再判断是：
   - request/schema 问题
   - worker 路由问题
   - CLI / 模型 / 网络问题

## 八、不建议直接做的事

- 不要先删整个 `leases/`
- 不要直接改写 `responses/` 来伪造成功
- 不要把 `smoke-cli` 失败直接当成 bus 设计失败

先区分：

- 脚本路由失败
- 外部 CLI 失败
- 模型服务失败

这三类问题不是一回事。
