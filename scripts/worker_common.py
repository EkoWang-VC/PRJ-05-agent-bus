#!/usr/bin/env python3
"""Shared helpers for CLI-based AGENT-BUS workers."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ


def normalize_heading_marks(text: str) -> str:
    return re.sub(r"^(#{1,6})\s+\1\s+", r"\1 ", text, flags=re.M)


def extract_required_sections(text: str, required: list[str]) -> bool:
    normalized = normalize_heading_marks(text)
    return all(section in normalized for section in required)


def clean_cli_output(text: str) -> str:
    cleaned_lines = [
        line
        for line in text.splitlines()
        if "cached credentials" not in line.lower()
    ]
    return "\n".join(cleaned_lines).strip()


def classify_cli_error(text: str) -> str:
    lowered = text.lower()
    if "model_capacity_exhausted" in lowered or "no capacity available for model" in lowered:
        return "model_capacity_exhausted"
    if "resource_exhausted" in lowered or '"code": 429' in lowered or "status 429" in lowered:
        return "rate_limited"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "not logged in" in lowered or "please run /login" in lowered or "please run login" in lowered:
        return "auth_error"
    if "permission" in lowered or "approval" in lowered:
        return "approval_blocked"
    if "proxy" in lowered or "econnrefused" in lowered or "enotfound" in lowered:
        return "network_error"
    if "login" in lowered or "auth" in lowered or "unauthorized" in lowered:
        return "auth_error"
    return "cli_error"


def invoke_streaming_command(
    cmd: list[str],
    cwd: Path,
    timeout_seconds: float,
    env: dict[str, str] | None = None,
) -> tuple[bool, str, str]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
        bufsize=1,
        env=env if env is not None else os.environ.copy(),
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    selector = DefaultSelector()
    selector.register(proc.stdout, EVENT_READ)
    selector.register(proc.stderr, EVENT_READ)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    deadline = time.monotonic() + timeout_seconds

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)

            events = selector.select(timeout=min(0.5, remaining))
            for key, _ in events:
                line = key.fileobj.readline()
                if line == "":
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is proc.stdout:
                    stdout_chunks.append(line)
                else:
                    stderr_chunks.append(line)

                combined_so_far = "".join(stdout_chunks) + "".join(stderr_chunks)
                error_code = classify_cli_error(combined_so_far)
                if error_code in {
                    "model_capacity_exhausted",
                    "rate_limited",
                    "auth_error",
                    "network_error",
                    "approval_blocked",
                }:
                    proc.kill()
                    proc.wait(timeout=5)
                    cleaned = clean_cli_output(combined_so_far)
                    return False, cleaned, error_code

        return_code = proc.wait(timeout=5)
    finally:
        selector.close()

    combined = "".join(stdout_chunks) + "".join(stderr_chunks)
    cleaned = clean_cli_output(combined)
    if return_code == 0 and cleaned:
        return True, cleaned, ""
    return False, cleaned, classify_cli_error(cleaned)


def build_generic_prompt(request: dict, output_root: Path, agent_label: str) -> str:
    refs: list[str] = []
    for rel_path in request.get("source_docs", []):
        abs_path = (output_root / rel_path).resolve()
        refs.append(f"- {abs_path}")

    required_sections = request.get("output_schema", {}).get("required_sections", [])
    section_lines = "\n".join(f"- {section}" for section in required_sections) or "- 无强制章节"
    prompt_summary = request.get("prompt_summary", "").strip()
    title = request.get("title", "").strip()

    return "\n".join(
        [
            f"你是 {agent_label}，正在处理 AGENT-BUS 请求。",
            f"任务标题：{title}",
            f"任务摘要：{prompt_summary}",
            "请阅读以下文件路径并完成任务：",
            *refs,
            "请直接输出最终 Markdown，不要额外解释。",
            "如有强制章节，请包含：",
            section_lines,
        ]
    ).strip()


def summarize_output(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return " ".join(lines[:3])[:280]


def build_generic_response(
    request: dict,
    output_text: str,
    output_exists: bool,
    handled_by: str,
) -> dict:
    required_sections = request.get("output_schema", {}).get("required_sections", [])
    sections_complete = output_exists and extract_required_sections(output_text, required_sections)
    can_transition = output_exists and (sections_complete or not required_sections)
    reason = (
        "已检测到产出文件，且必选章节满足要求，可支持主队列推进建议。"
        if can_transition
        else "产出文件不存在或必选章节不完整，暂不建议推进主队列状态。"
    )

    return {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "handled_by": handled_by,
        "status": "completed" if output_exists else "failed",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_path": request.get("output_path", ""),
        "summary": {
            "preview": summarize_output(output_text) if output_exists else "",
        },
        "queue_readiness": {
            "can_support_task_queue_transition": can_transition,
            "recommended_task_status": "待验收" if can_transition else request.get("queue_context", {}).get("task_status", ""),
            "reason": reason,
        },
        "validation_checks": {
            "output_exists": output_exists,
            "sections_complete": sections_complete,
            "needs_human_verification": True,
        },
        "error": "" if output_exists else "output file not found",
    }


def _read_lease_payload(lease_path: Path) -> dict | None:
    try:
        return json.loads(lease_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _lease_is_expired(payload: dict, now_ts: float) -> bool:
    expires_at = str(payload.get("expires_at", "")).strip()
    if not expires_at:
        return True
    try:
        expires_ts = datetime.fromisoformat(expires_at).timestamp()
    except ValueError:
        return True
    return expires_ts <= now_ts


def try_acquire_lease(
    lease_path: Path,
    request_id: str,
    handled_by: str,
    lease_ttl_seconds: int,
) -> bool:
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    now_ts = now.timestamp()
    if lease_path.exists():
        payload = _read_lease_payload(lease_path)
        if payload is None or _lease_is_expired(payload, now_ts):
            try:
                lease_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return False
    try:
        with lease_path.open("x", encoding="utf-8") as fh:
            payload = {
                "request_id": request_id,
                "handled_by": handled_by,
                "pid": os.getpid(),
                "created_at": now.isoformat(timespec="seconds"),
                "expires_at": datetime.fromtimestamp(
                    now_ts + lease_ttl_seconds, tz=now.tzinfo
                ).isoformat(timespec="seconds"),
                "lease_ttl_seconds": lease_ttl_seconds,
            }
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return True
    except FileExistsError:
        return False


def write_pid_file(
    pid_file_path: Path,
    handled_by: str,
    requests_dir: Path,
    poll_seconds: float,
    lease_ttl_seconds: int,
) -> None:
    pid_file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "handled_by": handled_by,
        "pid": os.getpid(),
        "requests_dir": str(requests_dir),
        "poll_seconds": poll_seconds,
        "lease_ttl_seconds": lease_ttl_seconds,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    pid_file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_pid_file(pid_file_path: Path | None) -> None:
    if pid_file_path is None:
        return
    try:
        pid_file_path.unlink()
    except FileNotFoundError:
        pass


def process_generic_request_file(
    request_path: Path,
    output_root: Path,
    response_path: Path | None,
    handled_by: str,
    invoke_cli: bool,
    model: str | None,
    timeout_seconds: float,
    preflight: bool,
    prompt_builder,
    cli_invoker,
) -> Path:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    output_path = output_root / request.get("output_path", "")
    output_exists = output_path.exists()
    output_text = output_path.read_text(encoding="utf-8") if output_exists else ""
    cli_error = ""
    cli_error_code = ""

    if invoke_cli and not output_exists:
        try:
            if preflight:
                ok, preflight_output, preflight_error_code = cli_invoker(
                    prompt="Reply with exactly OK.",
                    output_root=output_root,
                    model=model,
                    timeout_seconds=min(timeout_seconds, 15.0),
                    preflight=True,
                )
                if not ok:
                    cli_error_code = preflight_error_code or "preflight_failed"
                    cli_error = preflight_output or f"{handled_by} cli preflight failed"
                    raise RuntimeError("preflight_failed")

            prompt = prompt_builder(request, output_root)
            ok, generated, cli_error_code = cli_invoker(
                prompt=prompt,
                output_root=output_root,
                model=model,
                timeout_seconds=timeout_seconds,
                preflight=False,
            )
            if ok:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(generated + "\n", encoding="utf-8")
                output_exists = True
                output_text = generated
            else:
                cli_error = generated or f"{handled_by} cli invocation failed"
        except RuntimeError as exc:
            if str(exc) != "preflight_failed":
                raise
        except subprocess.TimeoutExpired:
            cli_error_code = "timeout"
            cli_error = f"{handled_by} cli timed out after {timeout_seconds:.1f}s"

    response = build_generic_response(
        request=request,
        output_text=output_text,
        output_exists=output_exists,
        handled_by=handled_by,
    )
    if cli_error:
        response["error"] = cli_error
        response["status"] = "failed"
    if cli_error_code:
        response["error_code"] = cli_error_code

    out_path = response_path or request_path.parent.parent / "responses" / f"{request['request_id']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def watch_generic_requests(
    requests_dir: Path,
    responses_dir: Path,
    leases_dir: Path,
    output_root: Path,
    poll_seconds: float,
    once: bool,
    handled_by: str,
    invoke_cli: bool,
    model: str | None,
    timeout_seconds: float,
    preflight: bool,
    lease_ttl_seconds: int,
    pid_file_path: Path | None,
    prompt_builder,
    cli_invoker,
) -> int:
    stop_state = {"requested": False, "signal": ""}

    def _request_stop(signum, _frame) -> None:
        stop_state["requested"] = True
        stop_state["signal"] = signal.Signals(signum).name

    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    if pid_file_path is not None:
        write_pid_file(pid_file_path, handled_by, requests_dir, poll_seconds, lease_ttl_seconds)

    try:
        while True:
            processed = 0
            for request_path in sorted(requests_dir.glob("*.json")):
                if stop_state["requested"]:
                    break
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if str(request.get("to_agent", "")).lower() != handled_by:
                    continue
                request_id = request.get("request_id", request_path.stem)
                response_path = responses_dir / f"{request_id}.json"
                if response_path.exists():
                    continue
                lease_path = leases_dir / f"{request_id}.{handled_by}.lock"
                if not try_acquire_lease(lease_path, request_id, handled_by, lease_ttl_seconds):
                    continue
                out_path = process_generic_request_file(
                    request_path=request_path,
                    output_root=output_root,
                    response_path=response_path,
                    handled_by=handled_by,
                    invoke_cli=invoke_cli,
                    model=model,
                    timeout_seconds=timeout_seconds,
                    preflight=preflight,
                    prompt_builder=prompt_builder,
                    cli_invoker=cli_invoker,
                )
                print(str(out_path))
                processed += 1

            if once:
                print(f"processed_requests: {processed}")
                return 0
            if stop_state["requested"]:
                print(f"shutdown_requested: {stop_state['signal'] or 'unknown'}")
                print(f"processed_requests: {processed}")
                return 0
            time.sleep(poll_seconds)
    finally:
        remove_pid_file(pid_file_path)
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)
