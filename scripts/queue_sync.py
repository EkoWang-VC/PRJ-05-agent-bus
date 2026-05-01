#!/usr/bin/env python3
"""Summarize AGENT-BUS requests/responses into a queue-facing markdown report."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_responses(responses_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(responses_dir.glob("*.json")):
        if path.name == ".gitkeep":
            continue
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def load_requests(requests_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(requests_dir.glob("*.json")):
        if path.name == ".gitkeep":
            continue
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def load_registry(registry_path: Path) -> dict[str, dict]:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    agents = payload.get("agents", [])
    return {
        str(agent.get("agent_id", "")).strip().lower(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agent_id", "")).strip()
    }


def classify(rows: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("status") == "failed":
            buckets["failed"].append(row)
        elif row.get("queue_readiness", {}).get("can_support_task_queue_transition"):
            buckets["ready"].append(row)
        else:
            buckets["needs_review"].append(row)
    return buckets


def render_entry(row: dict) -> str:
    task_id = row.get("task_id", "—")
    request_id = row.get("request_id", "—")
    status = row.get("status", "—")
    recommended = row.get("queue_readiness", {}).get("recommended_task_status", "—")
    reason = row.get("queue_readiness", {}).get("reason", "") or row.get("error", "")
    error_code = row.get("error_code", "")
    suffix = f" | error_code={error_code}" if error_code else ""
    return f"- `{task_id}` / `{request_id}` | `{status}` -> 建议 `{recommended}`{suffix}\n  {reason}"


def build_request_response_index(
    requests: list[dict],
    responses: list[dict],
    registry: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    response_ids = {row.get("request_id", "") for row in responses}
    request_ids = {row.get("request_id", "") for row in requests}

    invalid_requests = []
    invalid_request_ids: set[str] = set()
    for row in requests:
        to_agent = str(row.get("to_agent", "")).strip().lower()
        agent = registry.get(to_agent)
        if not to_agent:
            invalid_request_ids.add(str(row.get("request_id", "")).strip())
            invalid_requests.append(
                {
                    **row,
                    "_registry_reason": "to_agent 为空",
                }
            )
        elif agent is None:
            invalid_request_ids.add(str(row.get("request_id", "")).strip())
            invalid_requests.append(
                {
                    **row,
                    "_registry_reason": f"to_agent `{to_agent}` 未在 registry.json 中注册",
                }
            )
        elif not bool(agent.get("accepts_bus_requests", False)):
            invalid_request_ids.add(str(row.get("request_id", "")).strip())
            invalid_requests.append(
                {
                    **row,
                    "_registry_reason": f"to_agent `{to_agent}` 当前不接受 bus request",
                }
            )
    orphan_requests = [
        row
        for row in requests
        if row.get("request_id", "") not in response_ids
        and row.get("request_id", "") not in invalid_request_ids
    ]
    ghost_responses = [
        row for row in responses if row.get("request_id", "") not in request_ids
    ]
    return orphan_requests, ghost_responses, invalid_requests


def render_request_entry(row: dict) -> str:
    reason = row.get("_registry_reason", "")
    suffix = f"\n  {reason}" if reason else ""
    return (
        f"- `{row.get('task_id', '—')}` / `{row.get('request_id', '—')}`"
        f" -> `{row.get('to_agent', '—')}`\n"
        f"  {row.get('title', '') or row.get('prompt_summary', '')}{suffix}"
    )


def build_report(
    requests: list[dict],
    responses: list[dict],
    registry: dict[str, dict],
) -> str:
    buckets = classify(responses)
    orphan_requests, ghost_responses, invalid_requests = build_request_response_index(
        requests, responses, registry
    )
    lines: list[str] = []
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    lines.extend(
        [
            "---",
            "tags:",
            "  - vibe-coding/workflow",
            "  - agent-bus",
            "  - queue-sync",
            f"updated: {now}",
            "---",
            "",
            "# AGENT-BUS Queue Sync Report",
            "",
            "> 本报告只汇总 `responses/` 对 `TASK-QUEUE` 的推进建议，不直接改写任何队列文件。",
            "",
            "## 概览",
            "",
            f"- 总 request 数：{len(requests)}",
            f"- 总 response 数：{len(responses)}",
            f"- 可推进：{len(buckets['ready'])}",
            f"- 失败：{len(buckets['failed'])}",
            f"- 待人工复核：{len(buckets['needs_review'])}",
            f"- 孤儿 request：{len(orphan_requests)}",
            f"- 不可调度 request：{len(invalid_requests)}",
            f"- 幽灵 response：{len(ghost_responses)}",
            "",
            "## 可推进",
            "",
        ]
    )

    if buckets["ready"]:
        lines.extend(render_entry(row) for row in buckets["ready"])
    else:
        lines.append("- 当前为空")

    lines.extend(["", "## 失败", ""])
    if buckets["failed"]:
        lines.extend(render_entry(row) for row in buckets["failed"])
    else:
        lines.append("- 当前为空")

    lines.extend(["", "## 待人工复核", ""])
    if buckets["needs_review"]:
        lines.extend(render_entry(row) for row in buckets["needs_review"])
    else:
        lines.append("- 当前为空")

    lines.extend(["", "## 孤儿 Request", ""])
    if orphan_requests:
        lines.extend(render_request_entry(row) for row in orphan_requests)
    else:
        lines.append("- 当前为空")

    lines.extend(["", "## 不可调度 Request", ""])
    if invalid_requests:
        lines.extend(render_request_entry(row) for row in invalid_requests)
    else:
        lines.append("- 当前为空")

    lines.extend(["", "## 幽灵 Response", ""])
    if ghost_responses:
        lines.extend(render_entry(row) for row in ghost_responses)
    else:
        lines.append("- 当前为空")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests-dir", default="requests")
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--responses-dir", default="70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/AGENT-BUS/responses")
    parser.add_argument("--out", default="70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/AGENT-BUS-QUEUE-SYNC-REPORT.md")
    args = parser.parse_args()

    requests_dir = Path(args.requests_dir)
    registry_path = Path(args.registry)
    responses_dir = Path(args.responses_dir)
    out_path = Path(args.out)
    requests = load_requests(requests_dir)
    responses = load_responses(responses_dir)
    registry = load_registry(registry_path)
    report = build_report(requests, responses, registry)
    out_path.write_text(report, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
