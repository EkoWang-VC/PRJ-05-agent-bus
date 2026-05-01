#!/usr/bin/env python3
"""Summarize a bus response into queue-readiness guidance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("response_json")
    args = parser.parse_args()

    path = Path(args.response_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    readiness = data.get("queue_readiness", {})
    checks = data.get("validation_checks", {})
    summary = data.get("summary", {})

    print(f"task_id: {data.get('task_id', '')}")
    print(f"request_id: {data.get('request_id', '')}")
    print(f"handled_by: {data.get('handled_by', '')}")
    print(f"status: {data.get('status', '')}")
    print(f"output_path: {data.get('output_path', '')}")
    print(f"queue_transition_ready: {readiness.get('can_support_task_queue_transition', False)}")
    print(f"recommended_task_status: {readiness.get('recommended_task_status', '')}")
    print(f"reason: {readiness.get('reason', '')}")
    print("summary:")
    for key in ("adopt", "weaken_adopt", "need_data", "defer"):
        if key in summary:
            print(f"  {key}: {', '.join(summary[key])}")
    print("validation_checks:")
    for key, value in checks.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
