#!/usr/bin/env python3
"""Offline Gemini worker: turn a request + existing markdown output into a response."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
from selectors import DefaultSelector, EVENT_READ
from datetime import datetime
from pathlib import Path


def normalize_heading_marks(text: str) -> str:
    text = re.sub(r"^(#{1,6})\s+\1\s+", r"\1 ", text, flags=re.M)
    return text


def extract_required_sections(text: str, required: list[str]) -> bool:
    normalized = normalize_heading_marks(text)
    return all(section in normalized for section in required)


def section_slice(text: str, title: str) -> str:
    normalized = normalize_heading_marks(text)
    pattern = rf"^###\s+{re.escape(title)}\n(.*?)(?=^###\s+|\Z)"
    match = re.search(pattern, normalized, re.M | re.S)
    return match.group(1) if match else ""


def parse_decisions(text: str) -> dict[str, list[str]]:
    normalized = normalize_heading_marks(text)
    decisions: dict[str, list[str]] = {
        "adopt": [],
        "weaken_adopt": [],
        "need_data": [],
        "defer": [],
    }

    heading_pattern = re.compile(
        r"^#{3,4}\s+\**(P[1-6])\.[^\n]*?（(建议采纳|建议弱化后采纳|建议弱化采纳|需补数据再决定|需补数据|建议暂缓)",
        re.M,
    )
    label_to_bucket = {
        "建议采纳": "adopt",
        "建议弱化后采纳": "weaken_adopt",
        "建议弱化采纳": "weaken_adopt",
        "需补数据再决定": "need_data",
        "需补数据": "need_data",
        "建议暂缓": "defer",
    }

    for code, label in heading_pattern.findall(normalized):
        bucket = label_to_bucket[label]
        if code not in decisions[bucket]:
            decisions[bucket].append(code)
    return decisions


def build_response(request: dict, output_text: str, output_exists: bool) -> dict:
    required_sections = request.get("output_schema", {}).get("required_sections", [])
    decisions = parse_decisions(output_text) if output_exists else {
        "adopt": [],
        "weaken_adopt": [],
        "need_data": [],
        "defer": [],
    }
    sections_complete = output_exists and extract_required_sections(output_text, required_sections)
    decision_complete = all(
        any(code == f"P{i}" for codes in decisions.values() for code in codes)
        for i in range(1, 7)
    )

    can_transition = output_exists and sections_complete and decision_complete
    reason = (
        "已检测到产出文件、必选章节完整、P1-P6 均已明确归类，可支持主队列推进建议。"
        if can_transition
        else "产出文件、章节或 P1-P6 归类仍不完整，暂不建议推进主队列状态。"
    )

    return {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "handled_by": "gemini",
        "status": "completed" if output_exists else "failed",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_path": request.get("output_path", ""),
        "summary": decisions,
        "queue_readiness": {
            "can_support_task_queue_transition": can_transition,
            "recommended_task_status": "待验收" if can_transition else request.get("queue_context", {}).get("task_status", ""),
            "reason": reason,
        },
        "validation_checks": {
            "output_exists": output_exists,
            "sections_complete": sections_complete,
            "decision_complete_for_p1_p6": decision_complete,
            "needs_human_verification": True,
        },
        "error": "" if output_exists else "output file not found",
    }


def build_cli_prompt(request: dict, output_root: Path) -> str:
    refs: list[str] = []
    for rel_path in request.get("source_docs", []):
        abs_path = (output_root / rel_path).resolve()
        refs.append(f"@{abs_path}")

    required_sections = request.get("output_schema", {}).get("required_sections", [])
    section_lines = "\n".join(f"- {section}" for section in required_sections)
    prompt_summary = request.get("prompt_summary", "").strip()
    title = request.get("title", "").strip()

    return "\n".join(
        refs
        + [
            "",
            f"任务标题：{title}",
            f"任务摘要：{prompt_summary}",
            "请基于以上文件完成该任务，并直接输出最终 Markdown，不要补充额外说明。",
            "必须包含以下章节：",
            section_lines,
        ]
    ).strip()


def invoke_gemini_prompt(
    prompt: str,
    output_root: Path,
    model: str,
    approval_mode: str,
    timeout_seconds: float,
) -> tuple[bool, str, str]:
    cmd = [
        "gemini",
        "-p",
        prompt,
        "-m",
        model,
        "-o",
        "text",
        "--approval-mode",
        approval_mode,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(output_root),
        bufsize=1,
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
                if error_code in {"model_capacity_exhausted", "rate_limited", "auth_error", "network_error"}:
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


def run_preflight(
    output_root: Path,
    model: str,
    approval_mode: str,
    timeout_seconds: float,
) -> tuple[bool, str, str]:
    return invoke_gemini_prompt(
        prompt="Reply with exactly OK.",
        output_root=output_root,
        model=model,
        approval_mode=approval_mode,
        timeout_seconds=timeout_seconds,
    )


def invoke_gemini_cli(
    request: dict,
    output_root: Path,
    model: str,
    approval_mode: str,
    timeout_seconds: float,
) -> tuple[bool, str, str]:
    prompt = build_cli_prompt(request, output_root)
    return invoke_gemini_prompt(
        prompt=prompt,
        output_root=output_root,
        model=model,
        approval_mode=approval_mode,
        timeout_seconds=timeout_seconds,
    )


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
    if "permission" in lowered or "approval" in lowered:
        return "approval_blocked"
    if "proxy" in lowered or "econnrefused" in lowered or "enotfound" in lowered:
        return "network_error"
    if "login" in lowered or "auth" in lowered or "unauthorized" in lowered:
        return "auth_error"
    return "cli_error"


def process_request_file(
    request_path: Path,
    output_root: Path,
    response_path: Path | None = None,
    invoke_cli: bool = False,
    model: str = "gemini-3.1-pro-preview",
    approval_mode: str = "plan",
    timeout_seconds: float = 45.0,
    preflight: bool = False,
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
                ok, preflight_output, preflight_error_code = run_preflight(
                    output_root=output_root,
                    model=model,
                    approval_mode=approval_mode,
                    timeout_seconds=min(timeout_seconds, 15.0),
                )
                if not ok:
                    cli_error_code = preflight_error_code or "preflight_failed"
                    cli_error = preflight_output or "gemini cli preflight failed"
                    raise RuntimeError("preflight_failed")
            ok, generated, cli_error_code = invoke_gemini_cli(
                request=request,
                output_root=output_root,
                model=model,
                approval_mode=approval_mode,
                timeout_seconds=timeout_seconds,
            )
            if ok:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(generated + "\n", encoding="utf-8")
                output_exists = True
                output_text = generated
            else:
                cli_error = generated or "gemini cli invocation failed"
        except RuntimeError as exc:
            if str(exc) != "preflight_failed":
                raise
        except subprocess.TimeoutExpired:
            cli_error_code = "timeout"
            cli_error = f"gemini cli timed out after {timeout_seconds:.1f}s"

    response = build_response(request, output_text, output_exists)
    if cli_error:
        response["error"] = cli_error
        response["status"] = "failed"
    if cli_error_code:
        response["error_code"] = cli_error_code
    out_path = response_path or request_path.parent.parent / "responses" / f"{request['request_id']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


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


def try_acquire_lease(lease_path: Path, request_id: str, lease_ttl_seconds: int) -> bool:
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
                "handled_by": "gemini",
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
    requests_dir: Path,
    poll_seconds: float,
    lease_ttl_seconds: int,
) -> None:
    pid_file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "handled_by": "gemini",
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


def watch_requests(
    requests_dir: Path,
    responses_dir: Path,
    leases_dir: Path,
    output_root: Path,
    poll_seconds: float,
    once: bool,
    invoke_cli: bool,
    model: str,
    approval_mode: str,
    timeout_seconds: float,
    preflight: bool,
    lease_ttl_seconds: int,
    pid_file_path: Path | None,
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
        write_pid_file(pid_file_path, requests_dir, poll_seconds, lease_ttl_seconds)

    try:
        while True:
            processed = 0
            for request_path in sorted(requests_dir.glob("*.json")):
                if stop_state["requested"]:
                    break
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if str(request.get("to_agent", "")).lower() != "gemini":
                    continue
                request_id = request.get("request_id", request_path.stem)
                response_path = responses_dir / f"{request_id}.json"
                if response_path.exists():
                    continue

                lease_path = leases_dir / f"{request_id}.gemini.lock"
                if not try_acquire_lease(lease_path, request_id, lease_ttl_seconds):
                    continue

                out_path = process_request_file(
                    request_path=request_path,
                    output_root=output_root,
                    response_path=response_path,
                    invoke_cli=invoke_cli,
                    model=model,
                    approval_mode=approval_mode,
                    timeout_seconds=timeout_seconds,
                    preflight=preflight,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_json", nargs="?")
    parser.add_argument("--output-root", default=".")
    parser.add_argument("--out")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--requests-dir")
    parser.add_argument("--responses-dir")
    parser.add_argument("--leases-dir")
    parser.add_argument("--invoke-cli", action="store_true")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--approval-mode", default="plan")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--lease-ttl-seconds", type=int, default=60)
    parser.add_argument("--pid-file")
    args = parser.parse_args()

    output_root = Path(args.output_root)

    if args.watch:
        base_dir = Path(__file__).resolve().parent.parent
        requests_dir = Path(args.requests_dir) if args.requests_dir else base_dir / "requests"
        responses_dir = Path(args.responses_dir) if args.responses_dir else base_dir / "responses"
        leases_dir = Path(args.leases_dir) if args.leases_dir else base_dir / "leases"
        return watch_requests(
            requests_dir=requests_dir,
            responses_dir=responses_dir,
            leases_dir=leases_dir,
            output_root=output_root,
            poll_seconds=args.poll_seconds,
            once=args.once,
            invoke_cli=args.invoke_cli,
            model=args.model,
            approval_mode=args.approval_mode,
            timeout_seconds=args.timeout_seconds,
            preflight=args.preflight,
            lease_ttl_seconds=args.lease_ttl_seconds,
            pid_file_path=Path(args.pid_file) if args.pid_file else (leases_dir / "gemini.pid"),
        )

    if not args.request_json:
        raise SystemExit("request_json is required unless --watch is used")

    request_path = Path(args.request_json)
    out_path = process_request_file(
        request_path=request_path,
        output_root=output_root,
        response_path=Path(args.out) if args.out else None,
        invoke_cli=args.invoke_cli,
        model=args.model,
        approval_mode=args.approval_mode,
        timeout_seconds=args.timeout_seconds,
        preflight=args.preflight,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
