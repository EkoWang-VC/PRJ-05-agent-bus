#!/usr/bin/env python3
"""Claude AGENT-BUS worker."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from worker_common import (
    build_generic_prompt,
    classify_cli_error,
    clean_cli_output,
    invoke_streaming_command,
    process_generic_request_file,
    watch_generic_requests,
)


def claude_prompt_builder(request: dict, output_root: Path) -> str:
    return build_generic_prompt(request, output_root, "Claude")


def claude_cli_invoker(
    prompt: str,
    output_root: Path,
    model: str | None,
    timeout_seconds: float,
    preflight: bool,
) -> tuple[bool, str, str]:
    cmd = ["claude", "-p", prompt, "--output-format", "text", "--permission-mode", "plan"]
    if model:
        cmd.extend(["--model", model])
    return invoke_streaming_command(cmd, cwd=output_root, timeout_seconds=timeout_seconds)


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
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--lease-ttl-seconds", type=int, default=60)
    parser.add_argument("--pid-file")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    if args.watch:
        base_dir = Path(__file__).resolve().parent.parent
        return watch_generic_requests(
            requests_dir=Path(args.requests_dir) if args.requests_dir else base_dir / "requests",
            responses_dir=Path(args.responses_dir) if args.responses_dir else base_dir / "responses",
            leases_dir=Path(args.leases_dir) if args.leases_dir else base_dir / "leases",
            output_root=output_root,
            poll_seconds=args.poll_seconds,
            once=args.once,
            handled_by="claude",
            invoke_cli=args.invoke_cli,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            preflight=args.preflight,
            lease_ttl_seconds=args.lease_ttl_seconds,
            pid_file_path=Path(args.pid_file) if args.pid_file else (base_dir / "leases" / "claude.pid"),
            prompt_builder=claude_prompt_builder,
            cli_invoker=claude_cli_invoker,
        )

    if not args.request_json:
        raise SystemExit("request_json is required unless --watch is used")

    out_path = process_generic_request_file(
        request_path=Path(args.request_json),
        output_root=output_root,
        response_path=Path(args.out) if args.out else None,
        handled_by="claude",
        invoke_cli=args.invoke_cli,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        preflight=args.preflight,
        prompt_builder=claude_prompt_builder,
        cli_invoker=claude_cli_invoker,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
