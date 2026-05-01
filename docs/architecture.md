---
tags:
  - vibe-coding/workflow
  - multi-agent
  - terminal-orchestration
created: 2026-05-01
updated: 2026-05-01
status: draft
---

# AGENT BUS 设计草案

> **目标**：在不推翻现有 `Obsidian + Terminal + CLI Agent` 体系的前提下，为 `Claude / Codex / Gemini / QwenCode` 增加一层可脚本化的跨终端协作总线。

---

## 一、问题定义

当前所有 Agent 的运行方式，本质上都是：

- 在 Obsidian 中打开 terminal
- 在 terminal 中启动某个 CLI Agent
- 由人或文档在不同 terminal 之间转述任务

这有 3 个限制：

1. terminal 窗口只是**启动器**，不是可路由的 Agent 总线
2. Agent 间协作主要靠 `TASK-QUEUE / 任务卡 / handoff 文档`
3. 缺少可脚本消费的请求/响应协议，无法稳定实现“Agent A 调 Agent B”

因此，问题不是“能否直接让一个 terminal 窗口访问另一个 terminal 窗口”，而是：

> 能否在这些 terminal 之上增加一层轻量通信机制，让各 Agent 通过脚本进行任务投递、结果回收与状态同步？

结论：**可以，而且应优先做轻量 Agent Bus，而不是直接控制终端窗口本身。**

---

## 二、设计原则

1. **不替换现有 CLI**  
   继续使用 Claude Code / Codex / Gemini / QwenCode CLI。

2. **不依赖读取另一个 terminal 的屏幕内容**  
   避免 `tmux capture-pane` / AppleScript 抓屏式脆弱方案作为主路径。

3. **总线传任务，不传隐式脑内上下文**  
   Agent 间只交换显式输入、文件路径、任务目标、输出 schema。

4. **作为 TASK-QUEUE 的进阶层存在**  
   `TASK-QUEUE` 负责人类可读、知识库可见的主任务流；`AGENT-BUS` 负责其下的脚本化子任务流。

5. **先异步，后同步**  
   第一阶段先做“投递-处理-回写”异步模式，不急着做实时 RPC。

---

## 三、推荐架构

```text
Obsidian
  └── Terminal Plugin
        ├── Claude CLI
        ├── Codex CLI
        ├── Gemini CLI
        └── QwenCode CLI
                 ↑
                 │
          AGENT-BUS wrapper
                 ↑
                 │
      file-based message bus
```

核心思路：

- 每个 Agent 不直接“互相读取 terminal”
- 而是通过一个共享目录进行消息交换
- 每个 Agent 前面包一层 wrapper，负责：
  - 注册自身信息
  - 轮询 inbox
  - 拉起对应 CLI
  - 写回结构化结果

---

## 四、目录建议

在 `70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/AGENT-BUS/` 下建立：

```text
AGENT-BUS/
  README.md
  registry.json
  requests/
  responses/
  leases/
  examples/
    request.example.json
    response.example.json
```

含义：

- `registry.json`
  记录可用 Agent、能力、状态、入口命令
- `requests/`
  待处理请求
- `responses/`
  已完成响应
- `leases/`
  锁文件、执行权租约、心跳

---

## 五、最小消息模型

### 5.1 Request

```json
{
  "request_id": "REQ-20260501-001",
  "from_agent": "claude",
  "to_agent": "gemini",
  "domain": "investment",
  "task_type": "analysis",
  "title": "评估 Strategy A v1.1 补丁",
  "input_files": [
    "80-投资 (Investment)/01-策略与框架 (Strategies)/Strategy A v1.1 补丁清单.md"
  ],
  "prompt": "请评估哪些补丁应采纳，哪些应暂缓。",
  "output_schema": {
    "format": "markdown",
    "sections": ["结论", "逐条建议", "风险"]
  },
  "status": "pending",
  "created_at": "2026-05-01T10:00:00+08:00"
}
```

### 5.2 Response

```json
{
  "request_id": "REQ-20260501-001",
  "handled_by": "gemini",
  "status": "completed",
  "started_at": "2026-05-01T10:02:00+08:00",
  "completed_at": "2026-05-01T10:06:00+08:00",
  "output_path": "80-投资 (Investment)/02-日常复盘 (Daily Backtests)/2026-05-01-Strategy-A-Gemini评估.md",
  "summary": "建议采纳 P1/P2/P6，P3 仅作为复核触发器。",
  "error": ""
}
```

---

## 六、Registry 最小字段

`registry.json` 建议至少包含：

```json
{
  "agents": [
    {
      "agent_id": "claude",
      "provider": "anthropic",
      "mode": "terminal-cli",
      "capabilities": ["planning", "coding", "verification"],
      "status": "idle",
      "domain": ["workflow", "system", "coding"]
    }
  ]
}
```

关键字段：

- `agent_id`
- `provider`
- `mode`
- `capabilities`
- `status`
- `domain`

后续可扩展：

- `cwd`
- `launch_cmd`
- `last_seen_at`
- `accepts_bus_requests`

---

## 七、分阶段落地

### Phase 0：文档与协议

- 完成目录设计
- 固定 request/response schema
- 明确与 `TASK-QUEUE` 的关系

### Phase 1：手动半自动模式

- 人工写入 `request.json`
- 由目标 Agent 手动读取并执行
- 人工写回 `response.json`

目标：验证 schema 是否够用。

### Phase 2：wrapper 轮询模式

- 为每个 Agent 加一个轻量 wrapper
- 自动轮询 `requests/`
- 自动写回 `responses/`

目标：实现真正的“跨 terminal 异步调用”。

### Phase 3：与 TASK-QUEUE 联动

- 高层任务仍在 `TASK-QUEUE`
- 子任务可自动拆成 `AGENT-BUS` request
- 结果回收后自动更新任务卡或 handoff 文档

---

## 八、为什么不优先用 tmux / AppleScript

虽然也能实现“一个终端驱动另一个终端”，但问题明显：

- 依赖终端 UI 状态
- 难以保证输出结构稳定
- 容易被交互确认、分页、颜色码、异常提示打断
- 复盘和审计成本高

因此：

- `tmux / AppleScript` 可做实验工具
- **不建议作为主工作流基座**

---

## 九、为什么不直接引入 Hermes / OpenClaw

它们提供的重要启发是对的：

- 多 Agent 编排
- agent-to-agent 通信
- shared context / isolation
- parallel worker 模式

但对当前体系来说，直接上完整 runtime 的成本偏高：

- 会改写现有 `Obsidian + CLI` 使用习惯
- 要重建权限边界
- 要迁移现有文档工作流

所以更稳妥的策略是：

> 先在 Vibe Coding 内做一个 file-based Agent Bus，验证价值，再决定是否升级成更重的 orchestrator。

---

## 十、与当前工作流的关系

建议分工：

- `99-系统/System/WORKFLOW/TASK-QUEUE.md`
  知识库级任务入口
- `70-Vibe Coding/.../TASK-QUEUE.md`
  Vibe Coding 领域执行队列
- `70-Vibe Coding/.../AGENT-BUS/`
  `TASK-QUEUE` 的进阶自动化层，负责终端 Agent 之间的脚本通信

换句话说：

- `TASK-QUEUE` 负责“看得见的任务流”
- `AGENT-BUS` 负责“脚本可消费的子任务流”

二者不是替代关系，而是上下层关系。

### 10.1 推荐心智模型

```text
Task Card / TASK-QUEUE
        ↓
  人类可见任务流
        ↓
   AGENT-BUS request
        ↓
  Agent CLI 实际执行
        ↓
 AGENT-BUS response
        ↓
 Task Card / TASK-QUEUE 状态推进
```

这意味着：

- **Task Queue 是主编排层**
- **Agent Bus 是执行编排层**
- 没有 `TASK-QUEUE` 的任务，原则上不应直接进入自动总线
- `AGENT-BUS` 更像“把 handoff 文档和口头交接的一部分，升级成机器可处理消息”

---

## 十一、当前建议

如果继续推进，建议下一步只做一个 **Phase 1 原型**：

1. 建 `registry.json`
2. 固定 `request/response` schema
3. 选 1 个最小场景验证
   - 例如：`Claude -> Gemini` 内容评审请求
4. 由 `TASK-QUEUE` 的单个任务显式触发一个 bus request
5. 暂时不要接入全部 Agent
6. 暂时不要自动改写 `TASK-QUEUE`

先证明“能可靠投递、可靠回收”，再谈完全自动化。
