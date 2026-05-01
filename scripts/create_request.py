#!/usr/bin/env python3
"""Create a bus request JSON from a content task card."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")

    raw = text[4:end].splitlines()
    body = text[end + 5 :]
    data: dict[str, object] = {}
    current_list_key: str | None = None

    for line in raw:
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, [])
            assert isinstance(data[current_list_key], list)
            data[current_list_key].append(line[4:].strip())
            continue
        if line.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, [])
            assert isinstance(data[current_list_key], list)
            data[current_list_key].append(line[2:].strip())
            continue

        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = value.strip('"')
    return data, body


def extract_section(body: str, heading: str) -> str:
    pattern = rf"^### {re.escape(heading)}\n(.*?)(?=^### |\Z)"
    match = re.search(pattern, body, re.M | re.S)
    return match.group(1).strip() if match else ""


def extract_required_sections(output_requirements: str) -> list[str]:
    sections: list[str] = []
    for line in output_requirements.splitlines():
        m = re.search(r"`([^`]+)`", line)
        if not m:
            continue
        candidate = m.group(1).strip()
        if candidate.startswith("#"):
            sections.append(candidate)
    return sections


def summarize_task(task_desc: str) -> str:
    first_para = task_desc.split("\n\n", 1)[0].strip()
    first_para = re.sub(r"\s+", " ", first_para)
    return first_para[:180]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_spec")
    parser.add_argument("--from-agent", default="claude")
    parser.add_argument("--to-agent")
    parser.add_argument("--request-id")
    parser.add_argument("--out")
    args = parser.parse_args()

    task_path = Path(args.task_spec)
    text = task_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    task_id = str(fm["task_id"])
    to_agent = args.to_agent or str(fm.get("assigned_to", "")).lower()
    if not to_agent:
        raise ValueError("assigned_to missing")

    task_desc = extract_section(body, "任务描述")
    output_req = extract_section(body, "输出要求")
    request_id = args.request_id or f"REQ-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{task_id}"

    payload = {
        "request_id": request_id,
        "task_id": task_id,
        "from_agent": args.from_agent,
        "to_agent": to_agent.lower(),
        "domain": "vibe-coding",
        "task_type": str(fm.get("type", "task")),
        "title": summarize_task(task_desc) or task_id,
        "source_docs": fm.get("source_docs", []),
        "output_path": fm.get("output_path", ""),
        "prompt_summary": summarize_task(task_desc),
        "output_schema": {
            "format": "markdown",
            "required_sections": extract_required_sections(output_req),
        },
        "queue_context": {
            "task_status": fm.get("status", ""),
            "verify_by": fm.get("verify_by", ""),
        },
        "status": "pending",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    out_path = Path(args.out) if args.out else task_path.parent.parent / "AGENT-BUS" / "requests" / f"{request_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
