#!/usr/bin/env python3
"""Stage unit tests for the organization adaptive-orchestration policy scanner."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_PATH = ROOT / "tests" / "ci" / "test_contextual_orchestrator_defaults.py"
CONTENT = '''"""Tests for the contextual-orchestrator adaptive-default policy scanner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCANNER = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_contextual_orchestrator_defaults.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_rejects_forced_single_route_in_production(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/client.py",
        'url = "https://gateway/v1/chat/completions"\nmodel = "contextual-orchestrator"\npayload = {"mode": "route"}\n',
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "forced_single_route" in result.stdout


def test_rejects_implicit_mode_at_request_constructor(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/client.ts",
        "const endpoint = '/v1/chat/completions';\nconst body = { model: 'contextual-orchestrator', messages };\n",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "implicit_orchestration_mode" in result.stdout


def test_accepts_explicit_auto_request(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/client.rs",
        'let endpoint = "/v1/chat/completions";\njson!({"model": "contextual-orchestrator", "orchestration_mode": "auto", "messages": messages});\n',
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ignores_tests_docs_and_live_ablation_fixtures(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/live_ablation.py",
        'endpoint = "/v1/chat/completions"\nmodel = "contextual-orchestrator"\nmode = "route"\n',
    )
    _write(
        tmp_path,
        "docs/example.md",
        'contextual-orchestrator /v1/chat/completions mode="route"',
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_allows_explicit_policy_exception_for_controlled_ablation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/live_conformance.ts",
        "const endpoint = '/v1/chat/completions';\nconst request = { model: 'contextual-orchestrator', mode: 'route' };\n",
    )
    _write(
        tmp_path,
        ".cwl/contextual_orchestrator_policy.json",
        json.dumps({"allowed_fixed_mode_paths": ["src/live_conformance.ts"]}),
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
'''

if TEST_PATH.exists():
    if TEST_PATH.read_text(encoding="utf-8") != CONTENT:
        raise SystemExit(f"refusing to replace a different test: {TEST_PATH}")
else:
    TEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEST_PATH.write_text(CONTENT, encoding="utf-8")
