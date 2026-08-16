"""Contracts for the Strix 1.5.3 + cryptography 50.0.0 override lock."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-strix-ci.txt"
OVERRIDES = ROOT / "requirements-strix-ci-overrides.txt"
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
COMPILE = ROOT / "scripts" / "ci" / "compile_strix_ci_lock.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
QUALITY = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
DOCTORING = ROOT / "docs" / "doctoring" / "strix-agent-cryptography-override.md"
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"

_PIN_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\\\s]+)", re.MULTILINE)


def _lock_pins() -> dict[str, str]:
    """Return exact name==version pins from the compiled Strix lock."""

    pins: dict[str, str] = {}
    for match in _PIN_RE.finditer(LOCK.read_text(encoding="utf-8")):
        pins[match.group("name")] = match.group("version")
    return pins


def test_requirements_pin_atomic_report_strix_and_cve_fixed_cryptography() -> None:
    """The input set must name both the crash-fixed scanner and the CVE wheel."""

    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert "strix-agent==1.5.3" in requirements
    assert "cryptography==50.0.0" in requirements


def test_override_file_contains_only_the_cryptography_cve_pin() -> None:
    """The override must not silently replace any other locked package."""

    pins = [
        line.strip()
        for line in OVERRIDES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert pins == ["cryptography==50.0.0"]


def test_compiled_lock_keeps_both_pins_after_override_resolution() -> None:
    """A buyer-shaped lock must install 1.5.3 without dropping cryptography 50."""

    pins = _lock_pins()
    assert pins["strix-agent"] == "1.5.3"
    assert pins["cryptography"] == "50.0.0"
    header = LOCK.read_text(encoding="utf-8").splitlines()[:3]
    assert any("./scripts/ci/compile_strix_ci_lock.sh" in line for line in header)


def test_compile_script_records_the_override_and_linux_ci_platform() -> None:
    """Regeneration must stay hash-pinned, 3.13, manylinux, and override-aware."""

    script = COMPILE.read_text(encoding="utf-8")
    assert "--overrides requirements-strix-ci-overrides.txt" in script
    assert "--python-version 3.13" in script
    assert "--python-platform x86_64-manylinux_2_28" in script
    assert "--generate-hashes" in script
    assert "--custom-compile-command \"./scripts/ci/compile_strix_ci_lock.sh\"" in script
    assert "requirements-strix-ci.txt" in script


def test_strix_workflow_installs_the_complete_lock_without_re_resolving() -> None:
    """pip must not re-apply strix-agent's stale cryptography<49 metadata bound."""

    install = WORKFLOW.read_text(encoding="utf-8")
    assert "--require-hashes --no-deps -r requirements-strix-ci-hashes.txt" in install
    assert "--require-hashes -r requirements-strix-ci-hashes.txt\n" not in install
    assert 'expected = {"strix-agent": "1.5.3", "cryptography": "50.0.0"}' in install
    assert "metadata.version(name)" in install


def test_quality_workflow_reruns_when_the_override_contract_changes() -> None:
    """Changing the pin, override, lock, or doctoring must retrigger quality."""

    trigger = QUALITY.read_text(encoding="utf-8")
    assert "docs/doctoring/strix-agent-cryptography-override.md" in trigger
    assert "requirements-strix-ci.txt" in trigger
    assert "requirements-strix-ci-hashes.txt" in trigger
    assert "requirements-strix-ci-overrides.txt" in trigger
    assert "scripts/ci/compile_strix_ci_lock.sh" in trigger
    assert "tests/test_strix_agent_cryptography_override.py" in trigger
    assert ".github/workflows/strix.yml" in trigger


def test_doctoring_records_the_cve_and_upstream_atomic_write_fix() -> None:
    """The durable record must name the buyer gap and the standards used."""

    doctoring = DOCTORING.read_text(encoding="utf-8")
    assert "CVE-2026-69247" in doctoring
    assert "CVE-2026-39892" in doctoring
    assert "strix-agent==1.5.3" in doctoring
    assert "cryptography==50.0.0" in doctoring
    assert "--no-deps" in doctoring
    assert "National Institute of Standards and Technology" in doctoring
    assert "NIST Special Publication 800-218" in doctoring
    assert "CWE-754" in doctoring
    assert "MITRE" in doctoring
    assert "No Strix vulnerability report artifact was produced" in doctoring
    assert "ContextualWisdomLab/.github#969" in doctoring
    assert "vulnerabilities/*.md" in doctoring


def test_fail_closed_gate_still_requires_atomic_markdown_report_files() -> None:
    """1.5.3 must persist the Markdown files the gate already knows how to judge."""

    gate = GATE.read_text(encoding="utf-8")
    assert 'local vulnerabilities_dir="$run_dir/vulnerabilities"' in gate
    assert '"$vulnerabilities_dir"/*.md' in gate
    assert (
        "No Strix vulnerability report artifact was produced; log-only "
        "severity markers are incomplete evidence, so the scan is failing closed."
    ) in gate
    assert "Penetration test completed" not in gate
