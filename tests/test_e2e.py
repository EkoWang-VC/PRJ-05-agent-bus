#!/usr/bin/env python3
"""Minimal end-to-end coverage for AGENT-BUS scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class AgentBusE2ETest(unittest.TestCase):
    maxDiff = None

    def test_worker_check_response_and_queue_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requests_dir = root / "requests"
            responses_dir = root / "responses"
            leases_dir = root / "leases"
            outputs_dir = root / "outputs"
            requests_dir.mkdir()
            responses_dir.mkdir()
            leases_dir.mkdir()
            outputs_dir.mkdir()

            request_id = "REQ-E2E-001"
            task_id = "TASK-E2E-001"
            output_rel = "outputs/review.md"
            output_path = root / output_rel
            output_path.write_text(
                "# 审查结果\n\n## Findings\n\n- 文档完整\n",
                encoding="utf-8",
            )

            request = {
                "request_id": request_id,
                "task_id": task_id,
                "to_agent": "claude",
                "title": "E2E smoke",
                "prompt_summary": "验证 worker -> response -> queue sync",
                "source_docs": [],
                "output_path": output_rel,
                "output_schema": {"required_sections": ["## Findings"]},
                "queue_context": {"task_status": "待执行"},
            }
            request_path = requests_dir / f"{request_id}.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            response_path = responses_dir / f"{request_id}.json"
            worker = subprocess.run(
                [
                    sys.executable,
                    "scripts/claude_worker.py",
                    str(request_path),
                    "--output-root",
                    str(root),
                    "--out",
                    str(response_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(str(response_path), worker.stdout)

            response = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(response["status"], "completed")
            self.assertTrue(
                response["queue_readiness"]["can_support_task_queue_transition"]
            )
            self.assertEqual(
                response["queue_readiness"]["recommended_task_status"], "待验收"
            )

            check_result = subprocess.run(
                [sys.executable, "scripts/check_response.py", str(response_path)],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("queue_transition_ready: True", check_result.stdout)
            self.assertIn("recommended_task_status: 待验收", check_result.stdout)

            orphan_request = {
                "request_id": "REQ-E2E-ORPHAN",
                "task_id": "TASK-E2E-ORPHAN",
                "to_agent": "gemini",
                "title": "Orphan request",
                "prompt_summary": "还没有 response",
                "source_docs": [],
                "output_path": "outputs/orphan.md",
                "output_schema": {"required_sections": []},
                "queue_context": {"task_status": "待执行"},
            }
            (requests_dir / "REQ-E2E-ORPHAN.json").write_text(
                json.dumps(orphan_request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            ghost_response = {
                "request_id": "REQ-E2E-GHOST",
                "task_id": "TASK-E2E-GHOST",
                "handled_by": "codex",
                "status": "completed",
                "queue_readiness": {
                    "can_support_task_queue_transition": False,
                    "recommended_task_status": "待审查",
                    "reason": "仅用于 ghost response 检测",
                },
                "validation_checks": {"needs_human_verification": True},
                "summary": {"preview": "ghost"},
                "error": "",
            }
            (responses_dir / "REQ-E2E-GHOST.json").write_text(
                json.dumps(ghost_response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            report_path = root / "queue-report.md"
            sync = subprocess.run(
                [
                    sys.executable,
                    "scripts/queue_sync.py",
                    "--requests-dir",
                    str(requests_dir),
                    "--responses-dir",
                    str(responses_dir),
                    "--out",
                    str(report_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(str(report_path), sync.stdout)

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("- 总 request 数：2", report)
            self.assertIn("- 总 response 数：2", report)
            self.assertIn("- 孤儿 request：1", report)
            self.assertIn("- 幽灵 response：1", report)
            self.assertIn("## 孤儿 Request", report)
            self.assertIn("REQ-E2E-ORPHAN", report)
            self.assertIn("## 幽灵 Response", report)
            self.assertIn("REQ-E2E-GHOST", report)


if __name__ == "__main__":
    unittest.main()
