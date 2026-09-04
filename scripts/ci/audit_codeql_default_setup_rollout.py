#!/usr/bin/env python3
"""Classify CodeQL default-setup removal snapshots without mutating GitHub."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote

try:
    from scripts.ci.organization_commercial_readiness_loop import (
        GitHubClient,
        GitHubError,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from organization_commercial_readiness_loop import GitHubClient, GitHubError

EXEMPT_REPOSITORIES = frozenset({".github", "noema", "IRT-bibliography-set"})
SUCCESS = frozenset({"success", "neutral", "skipped"})
PENDING = frozenset({"queued", "in_progress", "pending", "requested", "waiting"})
RULESET_ID = 18156473
CENTRAL_CODEQL_PATH = ".github/workflows/codeql-pr.yml"
CENTRAL_REPOSITORY_ID = 1274066402
MAX_PAGES = 20
MAX_WORKFLOW_BYTES = 1_048_576


class EvidenceError(RuntimeError):
    """Report missing or ambiguous live rollout evidence."""


def _pages(client: Any, path: str, key: str | None = None) -> list[dict[str, Any]]:
    """Read every bounded REST page and reject malformed evidence."""
    values: list[dict[str, Any]] = []
    separator = "" if path.endswith("?") else "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        payload = client.request(f"{path}{separator}per_page=100&page={page}")
        batch = payload.get(key) if key and isinstance(payload, dict) else payload
        if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
            raise EvidenceError(f"GitHub returned malformed pagination data for {path}")
        values.extend(batch)
        if len(batch) < 100:
            return values
    raise EvidenceError(f"GitHub pagination exceeded {MAX_PAGES} pages for {path}")


def _step_has_disabled_upload(lines: list[str], start: int) -> bool:
    """Recognize only explicit, local neutralization of one CodeQL action step."""
    uses_indent = len(lines[start]) - len(lines[start].lstrip())
    block_start = start
    for index in range(start - 1, -1, -1):
        stripped = lines[index].lstrip()
        indent = len(lines[index]) - len(stripped)
        if stripped.startswith("-") and indent <= uses_indent:
            block_start = index
            break
    step_indent = len(lines[block_start]) - len(lines[block_start].lstrip())
    block = [lines[block_start]]
    for line in lines[block_start + 1 :]:
        stripped = line.lstrip()
        line_indent = len(line) - len(stripped)
        if stripped.startswith("-") and line_indent <= step_indent:
            break
        block.append(line)
    text = "\n".join(block)
    return bool(
        re.search(r"(?m)^\s*if:\s*(?:false|\$\{\{\s*false\s*\}\})\s*$", text)
        or re.search(r"(?m)^\s*upload:\s*['\"]?never['\"]?\s*$", text)
    )


def _has_active_advanced_upload(source: str) -> bool:
    """Conservatively detect an executable local CodeQL/SARIF upload step."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if re.search(
            r"uses:\s*github/codeql-action/(?:analyze|upload-sarif)@", line
        ) and not _step_has_disabled_upload(lines, index):
            return True
    return False


def _active_advanced_uploader(client: Any, repository: str, head_sha: str) -> bool:
    """Inspect active repository-owned workflow sources at the exact PR head."""
    workflows = _pages(client, f"/repos/{repository}/actions/workflows?", "workflows")
    inspected_paths: set[str] = set()
    for workflow in workflows:
        path = str(workflow.get("path") or "")
        if workflow.get("state") != "active" or not path.startswith(".github/workflows/"):
            continue
        if path in inspected_paths:
            raise EvidenceError(f"active workflow identity is ambiguous: {path}")
        inspected_paths.add(path)
        encoded = quote(path, safe="/")
        try:
            source = client.request(
                f"/repos/{repository}/contents/{encoded}?ref={head_sha}"
            )
        except GitHubError as exc:
            if "HTTP 404" in str(exc):
                continue
            raise EvidenceError(f"active workflow source lookup failed: {path}") from exc
        if not isinstance(source, dict) or source.get("encoding") != "base64":
            raise EvidenceError(f"active workflow source is unavailable: {path}")
        size = source.get("size")
        if not isinstance(size, int) or size < 0 or size > MAX_WORKFLOW_BYTES:
            raise EvidenceError(f"active workflow source has invalid size: {path}")
        try:
            encoded_content = "".join(str(source.get("content") or "").split())
            decoded = base64.b64decode(encoded_content, validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise EvidenceError(f"active workflow source is invalid: {path}") from exc
        if len(decoded.encode()) != size:
            raise EvidenceError(f"active workflow source size mismatch: {path}")
        if _has_active_advanced_upload(decoded):
            return True
    return False


def collect_live_snapshot(client: Any, repository: str, pr_number: int) -> dict[str, Any]:
    """Collect one exact-head rollout snapshot using read-only GitHub requests."""
    if not re.fullmatch(r"ContextualWisdomLab/[A-Za-z0-9_.-]+", repository):
        raise EvidenceError("repository must belong to ContextualWisdomLab")
    if pr_number < 1:
        raise EvidenceError("pull request number must be positive")

    pull = client.request(f"/repos/{repository}/pulls/{pr_number}")
    head_sha = str(((pull or {}).get("head") or {}).get("sha") or "")
    if (pull or {}).get("state") != "open" or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise EvidenceError("pull request is not open or has no valid exact head")

    inherited = _pages(client, f"/repos/{repository}/rulesets?includes_parents=true")
    matches = [item for item in inherited if item.get("id") == RULESET_ID]
    if len(matches) > 1:
        raise EvidenceError("central ruleset evidence is ambiguous")
    ruleset_applies = len(matches) == 1
    central_required = False
    if ruleset_applies:
        detail = client.request(
            f"/repos/{repository}/rulesets/{RULESET_ID}?includes_parents=true"
        )
        owners = [
            workflow
            for rule in (detail or {}).get("rules", [])
            if isinstance(rule, dict) and rule.get("type") == "workflows"
            for workflow in (rule.get("parameters") or {}).get("workflows", [])
            if isinstance(workflow, dict)
            and workflow.get("path") == CENTRAL_CODEQL_PATH
            and workflow.get("ref") == "refs/heads/main"
            and workflow.get("repository_id") == CENTRAL_REPOSITORY_ID
        ]
        if len(owners) > 1:
            raise EvidenceError("central CodeQL ruleset owner is ambiguous")
        central_required = len(owners) == 1

    name = repository.partition("/")[2]
    if name in EXEMPT_REPOSITORIES:
        latest_pull = client.request(f"/repos/{repository}/pulls/{pr_number}")
        if str(((latest_pull or {}).get("head") or {}).get("sha") or "") != head_sha:
            raise EvidenceError("pull request head changed during live evidence collection")
        return {"name": name, "ruleset_applies": ruleset_applies}

    default_setup = client.request(f"/repos/{repository}/code-scanning/default-setup")
    default_state = str((default_setup or {}).get("state") or "")
    if default_state not in {"configured", "not-configured"}:
        raise EvidenceError("default-setup state is unavailable")

    runs = _pages(
        client,
        f"/repos/{repository}/actions/runs?head_sha={head_sha}",
        "workflow_runs",
    )
    central_runs = [
        run
        for run in runs
        if run.get("path") == CENTRAL_CODEQL_PATH
        and run.get("event") == "pull_request"
        and run.get("head_sha") == head_sha
    ]
    if len(central_runs) != 1:
        raise EvidenceError(
            "exact-head central CodeQL run is missing or ambiguous"
        )
    run = central_runs[0]
    status = str(run.get("conclusion") or run.get("status") or "")
    if not status:
        raise EvidenceError("exact-head central CodeQL run has no status")

    result = {
        "name": name,
        "ruleset_applies": ruleset_applies,
        "central_codeql_required": central_required,
        "expected_head": head_sha,
        "central_codeql_head": str(run.get("head_sha") or ""),
        "central_codeql_status": status,
        "default_setup_state": default_state,
        "active_advanced_upload": _active_advanced_uploader(
            client, repository, head_sha
        ),
    }
    latest_pull = client.request(f"/repos/{repository}/pulls/{pr_number}")
    if str(((latest_pull or {}).get("head") or {}).get("sha") or "") != head_sha:
        raise EvidenceError("pull request head changed during live evidence collection")
    return result


def classify(repository: dict[str, Any]) -> tuple[str, str]:
    """Return a fail-closed rollout state and its operator-facing reason."""
    name = str(repository.get("name") or "")
    ruleset_applies = repository.get("ruleset_applies") is True
    if name in EXEMPT_REPOSITORIES:
        if ruleset_applies:
            return "BLOCK", "documented exception is unexpectedly covered by the central ruleset"
        return "EXEMPT", "documented ruleset exception"

    if not ruleset_applies or repository.get("central_codeql_required") is not True:
        return "BLOCK", "central CodeQL is not enforced by ruleset 18156473"

    expected_head = repository.get("expected_head")
    observed_head = repository.get("central_codeql_head")
    if not isinstance(expected_head, str) or len(expected_head) != 40 or observed_head != expected_head:
        return "BLOCK", "central CodeQL evidence is absent or belongs to another head"

    central_status = repository.get("central_codeql_status")
    default_state = repository.get("default_setup_state")
    active_advanced_upload = repository.get("active_advanced_upload") is True

    if default_state == "configured":
        if active_advanced_upload:
            return "BLOCK", "default setup conflicts with an active advanced CodeQL uploader"
        if central_status in SUCCESS:
            return "READY_DISABLE", "exact-head central CodeQL passed; disable one repository only"
        return "WAIT", "keep default setup until exact-head central CodeQL passes"

    if default_state != "not-configured":
        return "BLOCK", "default-setup state is unavailable or unsupported"
    if central_status in SUCCESS:
        return "VERIFIED", "default setup is off and exact-head central CodeQL passed"
    if central_status in PENDING:
        return "WAIT", "default setup is off; wait for the exact-head central CodeQL verdict"
    if active_advanced_upload:
        return "BLOCK", "central CodeQL failed and default setup cannot coexist with the active uploader"
    return "ROLLBACK", "central CodeQL failed; re-enable default setup before continuing"


def audit(repositories: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Classify every repository snapshot in input order."""
    return [
        (str(repository.get("name") or "<missing>"), *classify(repository))
        for repository in repositories
    ]


def load_payload(path: Path | None, stdin: TextIO) -> list[dict[str, Any]]:
    """Load a repository snapshot array from a file or standard input."""
    if path:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.load(stdin)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("repository snapshot root must be an array of objects")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse this audit's CLI arguments (a snapshots file, or live --repository/--pr)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots_json", nargs="?", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--pr", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the CodeQL default-setup rollout audit CLI."""
    args = parse_args(argv)
    try:
        live_mode = args.repository is not None or args.pr is not None
        if live_mode:
            if args.snapshots_json or not args.repository or args.pr is None:
                raise ValueError("live mode requires --repository and --pr only")
            repositories = [
                collect_live_snapshot(
                    GitHubClient.from_environment(), args.repository, args.pr
                )
            ]
        else:
            repositories = load_payload(args.snapshots_json, sys.stdin)
        results = audit(repositories)
    except (OSError, ValueError, json.JSONDecodeError, EvidenceError, GitHubError) as exc:
        print(f"ERROR: unable to load CodeQL rollout snapshots: {exc}", file=sys.stderr)
        return 2
    for name, state, reason in results:
        print(f"CODEQL_ROLLOUT repository={name} state={state} reason={reason}")
    return 0 if all(state in {"EXEMPT", "VERIFIED"} for _, state, _ in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
