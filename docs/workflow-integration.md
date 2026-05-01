---
tags:
  - vibe-coding/workflow
  - agent-bus
  - task-queue
created: 2026-05-01
updated: 2026-05-01
status: draft
---

# AGENT-BUS 与 TASK-QUEUE 集成说明

> **定位**：`AGENT-BUS` 不是平行于 `TASK-QUEUE` 的第二套流程，而是 `TASK-QUEUE` 的进阶自动化层。

---

## 一、核心关系

### TASK-QUEUE 负责什么

- 面向人类与知识库可读
- 记录任务主状态
- 决定谁该做什么
- 提供 Claude / Codex / Gemini 的唤醒入口

### AGENT-BUS 负责什么

- 面向脚本与 wrapper 可读
- 承载任务拆分后的子请求
- 负责跨 terminal Agent 的消息投递
- 负责结构化结果回收

因此：

> `TASK-QUEUE` 管主任务，`AGENT-BUS` 管子任务。

---

## 二、建议流程

### 2.1 当前阶段

```text
用户 / Claude
  → 创建或更新 Task Card
  → 更新 TASK-QUEUE
  → 人工决定是否需要调用其他 Agent
  → 若需要，再手动写入 AGENT-BUS request
```

### 2.2 未来阶段

```text
用户 / Claude
  → 创建或更新 Task Card
  → 更新 TASK-QUEUE
  → wrapper / orchestrator 根据规则生成 AGENT-BUS request
  → 目标 Agent 处理
  → 回写 response
  → 主 Agent 消费结果并推进 TASK-QUEUE
```

---

## 三、一个标准映射

### 任务层

- `CONTENT-20260504-02`
- 存在于：
  - 任务卡
  - `TASK-QUEUE`

### 子请求层

- `REQ-20260501-001`
- 存在于：
  - `AGENT-BUS/requests/REQ-20260501-001.json`
  - `AGENT-BUS/responses/REQ-20260501-001.json`

规则：

- 一个 `Task ID` 可以拆成多个 `Request ID`
- `Request ID` 不能反客为主替代 `Task ID`
- 只有当关键 request 完成后，主任务状态才允许推进

---

## 四、状态映射建议

| TASK-QUEUE 状态 | AGENT-BUS 含义 |
|---|---|
| `🔴 待执行` | 可生成 0-N 个 pending request |
| `🟡 待审查` | 相关 request 已完成，等待人工/Agent review |
| `🔵 待验收` | 关键 request 与 review 已完成 |
| `✅ 已完成` | request 已归档或可清理 |
| `❄️ 已冻结` | request 不应继续派发 |

补充规则：

- `AGENT-BUS` 不单独定义更高层“已完成”
- 主状态永远由 `TASK-QUEUE` 决定

---

## 五、第一批适用场景

最适合先接入 `AGENT-BUS` 的任务：

1. `Claude -> Gemini` 的内容评审 / 调研
2. `Claude -> Codex` 的局部 review / rescue 请求
3. `Codex -> Gemini` 的非代码分析子任务

不建议首批接入的任务：

1. 需要复杂交互确认的编码任务
2. 需要共享大量隐式上下文的长链任务
3. 直接改写 Git/部署状态的高风险任务

---

## 六、当前边界

本轮只完成：

- 关系定义
- 目录 scaffold
- schema 草案
- 与 `TASK-QUEUE` 的上下位关系确认

本轮没做：

- 自动从 `TASK-QUEUE` 生成 bus request
- 自动消费 response 后推进队列
- wrapper 守护进程

---

## 七、推荐下一步

如果按“`TASK-QUEUE` 的进阶版”推进，最合理的顺序是：

1. 选一个单 Task 场景
2. 手动从任务卡派生一个 `request.json`
3. 手动生成 `response.json`
4. 验证该 response 是否足够支撑 `TASK-QUEUE` 状态推进
5. 再决定是否写 wrapper

先证明映射关系成立，再做自动化。
