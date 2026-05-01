#!/usr/bin/env python3
"""Summarize AGENT-BUS responses into a queue-facing markdown report."""

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


def build_report(rows: list[dict]) -> str:
    buckets = classify(rows)
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
            f"- 总 response 数：{len(rows)}",
            f"- 可推进：{len(buckets['ready'])}",
            f"- 失败：{len(buckets['failed'])}",
            f"- 待人工复核：{len(buckets['needs_review'])}",
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

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses-dir", default="70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/AGENT-BUS/responses")
    parser.add_argument("--out", default="70-Vibe Coding (Vibe Coding)/04-工作流 (Workflow)/AGENT-BUS-QUEUE-SYNC-REPORT.md")
    args = parser.parse_args()

    responses_dir = Path(args.responses_dir)
    out_path = Path(args.out)
    rows = load_responses(responses_dir)
    report = build_report(rows)
    out_path.write_text(report, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
