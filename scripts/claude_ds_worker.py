#!/usr/bin/env python3
"""Claude-DS AGENT-BUS worker.

Claude-DS is treated as a distinct bus endpoint. For reliability, the worker
reconstructs the user's `claude-ds` shell function semantics directly instead of
calling that shell function verbatim:

- scrub proxy envs that interfere with DeepSeek
- map DEEPSEEK_API_KEY -> ANTHROPIC_API_KEY for current Claude CLI
- force DeepSeek-compatible model envs

This preserves separate routing and execution behavior without depending on a
potentially stale shell alias/function implementation. Environment overrides are
injected only into the Claude subprocess, not written back to the parent
process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from worker_common import (
    build_generic_prompt,
    invoke_streaming_command,
    process_generic_request_file,
    watch_generic_requests,
)


CLAUDE_DS_SYSTEM_PROMPT = (
    "你是 Claude-DS。你的职责不是通用协作，而是偏中文、偏研究、偏策略审查的独立分析执行器。"
    "若用户请求与投资、策略、研报、中文信息整合相关，优先给出结构化结论，少寒暄，少元话术。"
    "输出直接给 AGENT-BUS 消费，因此请只给最终 Markdown，不要额外说明执行过程。"
)


def claude_ds_prompt_builder(request: dict, output_root: Path) -> str:
    return build_generic_prompt(request, output_root, "Claude-DS")


def load_deepseek_api_key_from_login_shell() -> str:
    try:
        result = subprocess.run(
            ["/bin/zsh", "-lic", 'printf %s "${DEEPSEEK_API_KEY:-}"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def claude_ds_cli_invoker(
    prompt: str,
    output_root: Path,
    model: str | None,
    timeout_seconds: float,
    preflight: bool,
    cli_bin: str,
    claude_agent_name: str | None,
) -> tuple[bool, str, str]:
    cmd = [
        cli_bin,
        "-p",
        prompt,
        "--output-format",
        "text",
        "--permission-mode",
        "plan",
        "--no-session-persistence",
        "--append-system-prompt",
        CLAUDE_DS_SYSTEM_PROMPT,
    ]
    if claude_agent_name:
        cmd.extend(["--agent", claude_agent_name])
    if model:
        cmd.extend(["--model", model])

    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        env.pop(key, None)

    env["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
    deepseek_api_key = env.get("DEEPSEEK_API_KEY", "")
    if not deepseek_api_key:
        deepseek_api_key = load_deepseek_api_key_from_login_shell()
    if deepseek_api_key:
        env["DEEPSEEK_API_KEY"] = deepseek_api_key
        env["ANTHROPIC_API_KEY"] = deepseek_api_key
    env.setdefault("ANTHROPIC_MODEL", "deepseek-v4-pro")
    env.setdefault("ANTHROPIC_DEFAULT_OPUS_MODEL", "deepseek-v4-pro")
    env.setdefault("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-pro")
    env.setdefault("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-v4-flash")
    env.setdefault("CLAUDE_CODE_SUBAGENT_MODEL", "deepseek-v4-flash")
    env.setdefault("CLAUDE_CODE_EFFORT_LEVEL", "max")

    return invoke_streaming_command(
        cmd,
        cwd=output_root,
        timeout_seconds=timeout_seconds,
        env=env,
    )


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
    parser.add_argument("--cli-bin", default="claude")
    parser.add_argument("--claude-agent-name")
    args = parser.parse_args()

    output_root = Path(args.output_root)

    def cli_invoker(prompt: str, output_root: Path, model: str | None, timeout_seconds: float, preflight: bool):
        return claude_ds_cli_invoker(
            prompt=prompt,
            output_root=output_root,
            model=model,
            timeout_seconds=timeout_seconds,
            preflight=preflight,
            cli_bin=args.cli_bin,
            claude_agent_name=args.claude_agent_name,
        )

    if args.watch:
        base_dir = Path(__file__).resolve().parent.parent
        return watch_generic_requests(
            requests_dir=Path(args.requests_dir) if args.requests_dir else base_dir / "requests",
            responses_dir=Path(args.responses_dir) if args.responses_dir else base_dir / "responses",
            leases_dir=Path(args.leases_dir) if args.leases_dir else base_dir / "leases",
            output_root=output_root,
            poll_seconds=args.poll_seconds,
            once=args.once,
            handled_by="claude-ds",
            invoke_cli=args.invoke_cli,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            preflight=args.preflight,
            prompt_builder=claude_ds_prompt_builder,
            cli_invoker=cli_invoker,
        )

    if not args.request_json:
        raise SystemExit("request_json is required unless --watch is used")

    out_path = process_generic_request_file(
        request_path=Path(args.request_json),
        output_root=output_root,
        response_path=Path(args.out) if args.out else None,
        handled_by="claude-ds",
        invoke_cli=args.invoke_cli,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        preflight=args.preflight,
        prompt_builder=claude_ds_prompt_builder,
        cli_invoker=cli_invoker,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
