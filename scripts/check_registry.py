#!/usr/bin/env python3
"""Validate registry.json against the current repository layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_RESPONSE_PROFILES = {"generic", "decision-structured", "none"}
REQUIRED_AGENT_FIELDS = {
    "agent_id",
    "provider",
    "mode",
    "capabilities",
    "domains",
    "status",
    "accepts_bus_requests",
    "worker_script",
    "supports_watch",
    "supports_invoke_cli",
    "supports_preflight",
    "response_profile",
}


def validate_registry(registry_path: Path, repo_root: Path) -> list[str]:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        return ["registry.agents must be a non-empty list"]

    seen_ids: set[str] = set()
    for index, agent in enumerate(agents):
        prefix = f"agents[{index}]"
        if not isinstance(agent, dict):
            errors.append(f"{prefix} must be an object")
            continue

        missing = sorted(field for field in REQUIRED_AGENT_FIELDS if field not in agent)
        for field in missing:
            errors.append(f"{prefix}.{field} is required")

        agent_id = str(agent.get("agent_id", "")).strip()
        if not agent_id:
            errors.append(f"{prefix}.agent_id must be non-empty")
        elif agent_id in seen_ids:
            errors.append(f"{prefix}.agent_id duplicates '{agent_id}'")
        else:
            seen_ids.add(agent_id)

        capabilities = agent.get("capabilities")
        if not isinstance(capabilities, list):
            errors.append(f"{prefix}.capabilities must be a list")
        elif not all(isinstance(item, str) and item.strip() for item in capabilities):
            errors.append(f"{prefix}.capabilities must contain non-empty strings")

        domains = agent.get("domains")
        if not isinstance(domains, list):
            errors.append(f"{prefix}.domains must be a list")
        elif not all(isinstance(item, str) and item.strip() for item in domains):
            errors.append(f"{prefix}.domains must contain non-empty strings")

        response_profile = str(agent.get("response_profile", "")).strip()
        if response_profile not in ALLOWED_RESPONSE_PROFILES:
            errors.append(
                f"{prefix}.response_profile must be one of {sorted(ALLOWED_RESPONSE_PROFILES)}"
            )

        accepts_bus_requests = bool(agent.get("accepts_bus_requests", False))
        worker_script = str(agent.get("worker_script", "")).strip()
        worker_path = repo_root / worker_script if worker_script else None

        if accepts_bus_requests:
            if not worker_script:
                errors.append(f"{prefix}.worker_script is required when accepts_bus_requests=true")
            elif not worker_path.exists():
                errors.append(f"{prefix}.worker_script not found: {worker_script}")

            for field in (
                "supports_watch",
                "supports_invoke_cli",
                "supports_preflight",
            ):
                if not isinstance(agent.get(field), bool):
                    errors.append(f"{prefix}.{field} must be a boolean")

            for field in ("default_timeout_seconds", "default_lease_ttl_seconds"):
                value = agent.get(field)
                if not isinstance(value, int) or value <= 0:
                    errors.append(f"{prefix}.{field} must be a positive integer")
        else:
            if worker_script and worker_path is not None and not worker_path.exists():
                errors.append(f"{prefix}.worker_script not found: {worker_script}")

            if response_profile != "none":
                errors.append(
                    f"{prefix}.response_profile must be 'none' when accepts_bus_requests=false"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    repo_root = Path(args.repo_root)
    errors = validate_registry(registry_path=registry_path, repo_root=repo_root)
    if errors:
        for line in errors:
            print(f"ERROR: {line}")
        return 1

    print("registry_ok: true")
    print(f"registry_path: {registry_path}")
    print(f"agent_count: {len(json.loads(registry_path.read_text(encoding='utf-8')).get('agents', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
