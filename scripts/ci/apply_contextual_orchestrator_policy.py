#!/usr/bin/env python3
"""Install the organization adaptive-orchestration policy scanner and workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNER_PATH = ROOT / "scripts" / "ci" / "check_contextual_orchestrator_defaults.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "contextual-orchestrator-policy.yml"
ADR_PATH = ROOT / "docs" / "adr" / "0012-adaptive-orchestration-default-governance.md"

SCANNER_PATH.write_text(
    '''#!/usr/bin/env python3
"""Fail closed when a production consumer forces or omits orchestration policy."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SOURCE_SUFFIXES = frozenset(
    {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rs", ".go", ".java", ".kt", ".cs"}
)
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".github",
        "build",
        "dist",
        "docs",
        "examples",
        "fixtures",
        "migrations",
        "node_modules",
        "scripts",
        "spec",
        "specs",
        "target",
        "test",
        "tests",
        "vendor",
    }
)
ORCHESTRATOR_MARKERS = ("contextual-orchestrator", "contextual_orchestrator")
CHAT_ENDPOINT_MARKERS = ("/v1/chat/completions", "/chat/completions", "chat/completions")
FORCED_ROUTE_PATTERN = re.compile(
    r"(?:orchestration_mode|mode)(?:\s*:\s*str)?\s*[:=]\s*[\"']route[\"']",
    re.IGNORECASE,
)
AUTO_PATTERN = re.compile(
    r"(?:orchestration_mode|mode)(?:\s*:\s*str)?\s*[:=]\s*[\"']auto[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    """One source-backed policy violation."""

    finding_code: str
    source_path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return the stable JSON representation."""
        return {
            "finding_code": self.finding_code,
            "source_path": self.source_path,
            "message": self.message,
        }


def _load_policy(root: Path) -> dict[str, list[str]]:
    path = root / ".cwl" / "contextual_orchestrator_policy.json"
    if not path.exists():
        return {"allowed_fixed_mode_paths": [], "request_constructor_exemptions": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contextual_orchestrator_policy.json must contain an object")
    policy: dict[str, list[str]] = {}
    for key in ("allowed_fixed_mode_paths", "request_constructor_exemptions"):
        entries = value.get(key, [])
        if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
            raise ValueError(f"{key} must be an array of path globs")
        policy[key] = entries
    return policy


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _production_sources(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        lowered_parts = {part.lower() for part in relative.parts}
        if lowered_parts & EXCLUDED_PARTS:
            continue
        yield path


def inspect_repository(root: Path) -> list[Finding]:
    """Return every forced-route or implicit-mode production violation."""
    policy = _load_policy(root)
    findings: list[Finding] = []
    for path in _production_sources(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="strict")
        lowered = text.lower()
        if not any(marker in lowered for marker in ORCHESTRATOR_MARKERS):
            continue
        fixed_allowed = _matches(relative, policy["allowed_fixed_mode_paths"])
        constructor_exempt = _matches(
            relative, policy["request_constructor_exemptions"]
        )
        if FORCED_ROUTE_PATTERN.search(text) and not fixed_allowed:
            findings.append(
                Finding(
                    "forced_single_route",
                    relative,
                    "production contextual-orchestrator code forces route instead of delegating to auto",
                )
            )
        constructs_chat_request = any(marker in lowered for marker in CHAT_ENDPOINT_MARKERS)
        names_gateway_model = "contextual-orchestrator" in lowered
        if (
            constructs_chat_request
            and names_gateway_model
            and not AUTO_PATTERN.search(text)
            and not constructor_exempt
            and not fixed_allowed
        ):
            findings.append(
                Finding(
                    "implicit_orchestration_mode",
                    relative,
                    "production chat request must explicitly select contextual-orchestrator auto",
                )
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository_root", nargs="?", default=".")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    root = Path(args.repository_root).resolve()
    findings = inspect_repository(root)
    payload = {
        "policy_name": "contextual_orchestrator_adaptive_default",
        "repository_root": str(root),
        "finding_count": len(findings),
        "findings": [finding.as_dict() for finding in findings],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        Path(args.json_output).write_text(rendered + "\n", encoding="utf-8")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    encoding="utf-8",
)

WORKFLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
WORKFLOW_PATH.write_text(
    '''name: Contextual Orchestrator Adaptive Default

on:
  workflow_call:

permissions:
  contents: read

jobs:
  adaptive-default-policy:
    name: contextual-orchestrator adaptive default
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout consumer repository exact ref
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # actions/checkout@v4
        with:
          path: consumer
          persist-credentials: false

      - name: Checkout central governance scanner
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # actions/checkout@v4
        with:
          repository: ContextualWisdomLab/.github
          ref: main
          path: governance
          persist-credentials: false

      - name: Enforce explicit adaptive orchestration defaults
        run: >-
          python governance/scripts/ci/check_contextual_orchestrator_defaults.py
          consumer
          --json-output contextual-orchestrator-policy.json

      - name: Upload bounded policy evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: contextual-orchestrator-policy-${{ github.sha }}
          path: contextual-orchestrator-policy.json
          if-no-files-found: ignore
          retention-days: 14
''',
    encoding="utf-8",
)

ADR_PATH.parent.mkdir(parents=True, exist_ok=True)
ADR_PATH.write_text(
    '''# ADR-0012: Organization governance requires explicit adaptive orchestration defaults

- Status: Accepted
- Date: 2026-08-16

## Context

Consumer repositories can unintentionally bypass contextual-orchestrator by
hard-coding `route`, omitting the mode at a request constructor, or copying a direct
provider model. This makes quality/cost policy drift invisible and forces each product
to rediscover the same control. Controlled live-conformance and ablation fixtures
still need explicit fixed modes.

## Decision

The central `.github` repository provides a reusable fail-closed workflow and scanner.
Production source that constructs a contextual-orchestrator chat request must
explicitly select `auto`; a fixed `route` is rejected. Tests, documentation, examples,
and fixtures are excluded. A repository may declare narrow path-glob exceptions in
`.cwl/contextual_orchestrator_policy.json` for controlled ablation or a request
constructor whose mode is injected by a separately tested wrapper.

`auto` means quality and safety requirements are satisfied first; known cost is used
only among capability-equivalent choices, and unpriced models are not treated as
free. The gateway remains responsible for route/verify/conduct selection.

## Consequences

The guard prevents future regressions after consumer migration without forcing all
work through an expensive workflow. It does not certify semantic quality, provider
pricing, or production SLOs; those require measured evaluation and telemetry.

## References

Omidvar, H., & Akhlaghi, V. (2026). *A communication-theoretic framework for LLM agents: Cost-aware adaptive reliability* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2605.09121

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv. https://doi.org/10.48550/arXiv.2606.21228
''',
    encoding="utf-8",
)
