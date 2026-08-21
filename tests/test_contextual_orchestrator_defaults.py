"""Tests for the fail-closed adaptive-orchestration policy scanner."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import check_contextual_orchestrator_defaults as policy

ROOT = Path(__file__).parents[1]


def _write(root: Path, relative: str, content: str) -> None:
    """Write one UTF-8 source fixture below a temporary repository root."""

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_inspect_repository_reports_forced_and_implicit_modes(tmp_path: Path) -> None:
    """Production route and omitted mode are both reported with stable fields."""

    _write(
        tmp_path,
        "src/forced.py",
        'endpoint = "/v1/chat/completions"\nmodel = "contextual-orchestrator"\nmode = "route"\n',
    )
    _write(
        tmp_path,
        "src/implicit.ts",
        "const endpoint = '/v1/chat/completions';\nconst body = { model: 'contextual-orchestrator' };\n",
    )
    _write(
        tmp_path,
        "src/auto.rs",
        'json!({"model": "contextual-orchestrator", "orchestration_mode": "auto"});\n',
    )
    _write(tmp_path, "docs/example.py", 'mode = "route"\n')
    _write(tmp_path, "tests/example.py", 'mode = "route"\n')
    _write(tmp_path, "src/readme.txt", 'contextual-orchestrator mode = "route"\n')
    _write(tmp_path, "src/other.py", "value = 1\n")

    findings = policy.inspect_repository(tmp_path)

    assert [(item.finding_code, item.source_path) for item in findings] == [
        ("forced_single_route", "src/forced.py"),
        ("implicit_orchestration_mode", "src/forced.py"),
        ("implicit_orchestration_mode", "src/implicit.ts"),
    ]
    assert findings[0].as_dict()["message"].startswith("production contextual-orchestrator")


def test_policy_exceptions_are_path_scoped(tmp_path: Path) -> None:
    """Fixed modes pass only when their exact paths are explicitly exempted."""

    _write(
        tmp_path,
        "src/forced.py",
        'model = "contextual-orchestrator"\nmode = "route"\n',
    )
    _write(
        tmp_path,
        "src/constructor.ts",
        "const endpoint = '/v1/chat/completions';\nconst body = { model: 'contextual-orchestrator' };\n",
    )
    _write(
        tmp_path,
        ".cwl/contextual_orchestrator_policy.json",
        json.dumps(
            {
                "allowed_fixed_mode_paths": ["src/forced.py"],
                "request_constructor_exemptions": ["src/constructor.ts"],
            }
        ),
    )

    assert policy.inspect_repository(tmp_path) == []


def test_unquoted_modes_are_detected_without_partial_matches(tmp_path: Path) -> None:
    """Detect equivalent unquoted assignments while rejecting longer values."""

    _write(
        tmp_path,
        "src/forced.py",
        'endpoint = "/v1/chat/completions"\n'
        'model = "contextual-orchestrator"\n'
        "orchestration_mode = route\n",
    )
    _write(
        tmp_path,
        "src/partial.py",
        'endpoint = "/v1/chat/completions"\n'
        'model = "contextual-orchestrator"\n'
        'mode = "router"\n',
    )
    _write(
        tmp_path,
        "src/auto.py",
        'endpoint = "/v1/chat/completions"\n'
        'model = "contextual-orchestrator"\n'
        "mode = auto\n",
    )

    findings = policy.inspect_repository(tmp_path)

    assert [(item.finding_code, item.source_path) for item in findings] == [
        ("forced_single_route", "src/forced.py"),
        ("implicit_orchestration_mode", "src/forced.py"),
        ("implicit_orchestration_mode", "src/partial.py"),
    ]


def test_malformed_policy_fails_closed(tmp_path: Path) -> None:
    """Malformed exception configuration raises instead of weakening the scan."""

    path = tmp_path / ".cwl" / "contextual_orchestrator_policy.json"
    path.parent.mkdir()
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        policy.inspect_repository(tmp_path)

    path.write_text(json.dumps({"allowed_fixed_mode_paths": [1]}), encoding="utf-8")
    with pytest.raises(ValueError, match="allowed_fixed_mode_paths"):
        policy.inspect_repository(tmp_path)


def test_main_writes_bounded_json_and_returns_status(tmp_path: Path, capsys) -> None:
    """The CLI emits machine-readable evidence and a non-zero finding status."""

    _write(tmp_path, "src/client.py", 'mode = "route"\nmodel = "contextual-orchestrator"\n')
    output = tmp_path / "evidence.json"

    assert policy.main([str(tmp_path), "--json-output", str(output)]) == 1
    rendered = json.loads(output.read_text(encoding="utf-8"))
    assert rendered["finding_count"] == 1
    assert json.loads(capsys.readouterr().out)["policy_name"] == (
        "contextual_orchestrator_adaptive_default"
    )

    _write(tmp_path, "src/clean.py", 'mode = "auto"\nmodel = "contextual-orchestrator"\n')
    assert policy.main([str(tmp_path)]) == 1


def test_json_output_rejects_symbolic_link(tmp_path: Path) -> None:
    """Evidence cannot overwrite a path that resolves through a symbolic link."""

    target = tmp_path / "target.json"
    target.write_text("keep\n", encoding="utf-8")
    output = tmp_path / "evidence.json"
    output.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        policy._write_json_output(str(output), "{}")

    assert target.read_text(encoding="utf-8") == "keep\n"


def test_source_read_errors_are_not_suppressed(tmp_path: Path) -> None:
    """Invalid source bytes fail closed rather than being silently skipped."""

    path = tmp_path / "src" / "broken.py"
    path.parent.mkdir()
    path.write_bytes(b'model = "contextual-orchestrator"\n\xff')

    with pytest.raises(UnicodeDecodeError):
        policy.inspect_repository(tmp_path)


def test_module_entrypoint_returns_clean_status(tmp_path: Path, monkeypatch) -> None:
    """The standalone scanner entrypoint exits successfully for a clean tree."""

    monkeypatch.setattr(sys, "argv", [str(policy.__file__), str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(policy.__file__), run_name="__main__")
    assert exit_info.value.code == 0


def test_reusable_workflow_is_exact_ref_read_only_governance() -> None:
    """The reusable workflow pins both source identities and cannot mutate repos."""

    workflow = (ROOT / ".github/workflows/contextual-orchestrator-policy.yml").read_text(
        encoding="utf-8"
    )
    assert "governance_sha:" in workflow
    assert "target_ref:" in workflow
    assert '[[ "$GOVERNANCE_SHA" =~ ^[0-9a-fA-F]{40}$ ]]' in workflow
    assert '[[ "$TARGET_REF" =~ ^[0-9a-fA-F]{40}$ ]]' in workflow
    assert "ref: ${{ inputs.governance_sha }}" in workflow
    assert "ref: ${{ inputs.target_ref }}" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "contents: write" not in workflow
    assert "persist-credentials: false" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
