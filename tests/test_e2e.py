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

    def make_dirs(self, root: Path) -> tuple[Path, Path, Path, Path]:
        requests_dir = root / "requests"
        responses_dir = root / "responses"
        leases_dir = root / "leases"
        outputs_dir = root / "outputs"
        requests_dir.mkdir()
        responses_dir.mkdir()
        leases_dir.mkdir()
        outputs_dir.mkdir()
        return requests_dir, responses_dir, leases_dir, outputs_dir

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_registry_health_check(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/check_registry.py",
                "--registry",
                "registry.json",
                "--repo-root",
                ".",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("registry_ok: true", result.stdout)
        self.assertIn("agent_count: 5", result.stdout)

    def test_worker_check_response_and_queue_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requests_dir, responses_dir, leases_dir, _outputs_dir = self.make_dirs(root)

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
            self.write_json(request_path, request)

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
                json.dumps(orphan_request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            invalid_request = {
                "request_id": "REQ-E2E-INVALID",
                "task_id": "TASK-E2E-INVALID",
                "to_agent": "qwencode",
                "title": "Invalid request",
                "prompt_summary": "registry 中不可调度",
                "source_docs": [],
                "output_path": "outputs/invalid.md",
                "output_schema": {"required_sections": []},
                "queue_context": {"task_status": "待执行"},
            }
            (requests_dir / "REQ-E2E-INVALID.json").write_text(
                json.dumps(invalid_request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
                json.dumps(ghost_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            report_path = root / "queue-report.md"
            sync = subprocess.run(
                [
                    sys.executable,
                    "scripts/queue_sync.py",
                    "--requests-dir",
                    str(requests_dir),
                    "--registry",
                    "registry.json",
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
            self.assertIn("- 总 request 数：3", report)
            self.assertIn("- 总 response 数：2", report)
            self.assertIn("- 孤儿 request：1", report)
            self.assertIn("- 不可调度 request：1", report)
            self.assertIn("- 幽灵 response：1", report)
            self.assertIn("## 孤儿 Request", report)
            self.assertIn("REQ-E2E-ORPHAN", report)
            self.assertIn("## 不可调度 Request", report)
            self.assertIn("REQ-E2E-INVALID", report)
            self.assertIn("当前不接受 bus request", report)
            self.assertIn("## 幽灵 Response", report)
            self.assertIn("REQ-E2E-GHOST", report)

    def test_multi_worker_watch_routes_requests_and_writes_leases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requests_dir, responses_dir, leases_dir, _outputs_dir = self.make_dirs(root)

            requests = [
                {
                    "request_id": "REQ-MULTI-CLAUDE",
                    "task_id": "TASK-MULTI-CLAUDE",
                    "to_agent": "claude",
                    "title": "Claude request",
                    "prompt_summary": "路由到 claude",
                    "source_docs": [],
                    "output_path": "outputs/claude.md",
                    "output_schema": {"required_sections": ["## Findings"]},
                    "queue_context": {"task_status": "待执行"},
                },
                {
                    "request_id": "REQ-MULTI-CLAUDE-DS",
                    "task_id": "TASK-MULTI-CLAUDE-DS",
                    "to_agent": "claude-ds",
                    "title": "Claude-DS request",
                    "prompt_summary": "路由到 claude-ds",
                    "source_docs": [],
                    "output_path": "outputs/claude-ds.md",
                    "output_schema": {"required_sections": ["## Findings"]},
                    "queue_context": {"task_status": "待执行"},
                },
                {
                    "request_id": "REQ-MULTI-CODEX",
                    "task_id": "TASK-MULTI-CODEX",
                    "to_agent": "codex",
                    "title": "Codex request",
                    "prompt_summary": "路由到 codex",
                    "source_docs": [],
                    "output_path": "outputs/codex.md",
                    "output_schema": {"required_sections": ["## Findings"]},
                    "queue_context": {"task_status": "待执行"},
                },
                {
                    "request_id": "REQ-MULTI-GEMINI",
                    "task_id": "TASK-MULTI-GEMINI",
                    "to_agent": "gemini",
                    "title": "Gemini request",
                    "prompt_summary": "路由到 gemini",
                    "source_docs": [],
                    "output_path": "outputs/gemini.md",
                    "output_schema": {"required_sections": ["## 决策总览"]},
                    "queue_context": {"task_status": "待执行"},
                },
            ]

            outputs = {
                "outputs/claude.md": "# Claude\n\n## Findings\n\n- routed\n",
                "outputs/claude-ds.md": "# Claude-DS\n\n## Findings\n\n- routed\n",
                "outputs/codex.md": "# Codex\n\n## Findings\n\n- routed\n",
                "outputs/gemini.md": (
                    "# Gemini\n\n## 决策总览\n\n已完成归类。\n\n"
                    "### P1. 财报窗口强制复核（建议采纳）\n\n- ok\n\n"
                    "### P2. 治理风险一票否决（建议采纳）\n\n- ok\n\n"
                    "### P3. 盈利稳定性副过滤（建议弱化后采纳）\n\n- ok\n\n"
                    "### P4. 流动性下限（需补数据再决定）\n\n- ok\n\n"
                    "### P5. 风格逆风时仓位层调节（建议暂缓）\n\n- ok\n\n"
                    "### P6. 调仓动作分层（建议采纳）\n\n- ok\n"
                ),
            }

            for payload in requests:
                self.write_json(requests_dir / f"{payload['request_id']}.json", payload)
                (root / payload["output_path"]).write_text(
                    outputs[payload["output_path"]],
                    encoding="utf-8",
                )

            worker_cases = [
                (
                    "claude",
                    "scripts/claude_worker.py",
                    "REQ-MULTI-CLAUDE",
                    "REQ-MULTI-CLAUDE.claude.lock",
                ),
                (
                    "claude-ds",
                    "scripts/claude_ds_worker.py",
                    "REQ-MULTI-CLAUDE-DS",
                    "REQ-MULTI-CLAUDE-DS.claude-ds.lock",
                ),
                (
                    "codex",
                    "scripts/codex_worker.py",
                    "REQ-MULTI-CODEX",
                    "REQ-MULTI-CODEX.codex.lock",
                ),
                (
                    "gemini",
                    "scripts/gemini_worker.py",
                    "REQ-MULTI-GEMINI",
                    "REQ-MULTI-GEMINI.gemini.lock",
                ),
            ]

            for handled_by, script_path, request_id, lease_name in worker_cases:
                pid_file = leases_dir / f"{handled_by}.pid"
                result = subprocess.run(
                    [
                        sys.executable,
                        script_path,
                        "--watch",
                        "--once",
                        "--output-root",
                        str(root),
                        "--requests-dir",
                        str(requests_dir),
                        "--responses-dir",
                        str(responses_dir),
                        "--leases-dir",
                        str(leases_dir),
                        "--lease-ttl-seconds",
                        "60",
                        "--pid-file",
                        str(pid_file),
                    ],
                    cwd=REPO_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertIn("processed_requests: 1", result.stdout)

                response_path = responses_dir / f"{request_id}.json"
                self.assertTrue(response_path.exists(), response_path.name)
                response = self.read_json(response_path)
                self.assertEqual(response["handled_by"], handled_by)
                self.assertEqual(response["status"], "completed")

                lease_path = leases_dir / lease_name
                self.assertTrue(lease_path.exists(), lease_name)
                lease = self.read_json(lease_path)
                self.assertEqual(lease["request_id"], request_id)
                self.assertEqual(lease["handled_by"], handled_by)
                self.assertEqual(lease["lease_ttl_seconds"], 60)
                self.assertIsInstance(lease["pid"], int)
                self.assertFalse(pid_file.exists(), pid_file.name)

            all_response_ids = {
                path.stem for path in responses_dir.glob("*.json") if path.suffix == ".json"
            }
            self.assertEqual(
                all_response_ids,
                {
                    "REQ-MULTI-CLAUDE",
                    "REQ-MULTI-CLAUDE-DS",
                    "REQ-MULTI-CODEX",
                    "REQ-MULTI-GEMINI",
                },
            )


if __name__ == "__main__":
    unittest.main()
