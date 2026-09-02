#!/usr/bin/env python3
"""One-shot exact-source edge repair for PR 1641; deletes itself after GREEN."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests/test_noema_class_evidence_observation_contract.py"
GATE = ROOT / "scripts/ci/noema_review_gate.py"
DOCS = ROOT / "docs/product-technical-gap-baseline.md"
CHANGELOG = ROOT / "CHANGELOG.md"

WHITESPACE_TEST = r'''


def test_whitespace_only_changed_source_requires_explicit_blank_marker() -> None:
    """Whitespace-only source cannot satisfy the quote guard via incidental spacing."""
    source = "    "
    diff = f"""diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+{source}
"""
    verdict = _verdict(observations=True, source_excerpt=True)
    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["source_excerpt"] = source
            witness["observation"] = (
                f"Incidental    spacing is not a source quote for {probe['probe_kind']}:{field}."
            )
    with pytest.raises(noema.NoemaModelOutputError, match="quote the exact source_excerpt"):
        noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])
'''

LONG_TEST = r'''


def test_long_changed_line_uses_structural_exact_source_binding() -> None:
    """An over-cap changed line remains reviewable without impossible prose repetition."""
    source = "x" * (noema.MAX_THREAD_BODY_CHARS + 64)
    diff = f"""diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+{source}
"""
    verdict = _verdict(observations=True, source_excerpt=True)
    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["source_excerpt"] = source
            witness["observation"] = (
                f"Bounded structural observation for {probe['probe_kind']}:{field} at the exact cited line."
            )
    noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])
'''


def run(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != expect:
        raise SystemExit(f"command {args!r} returned {result.returncode}, expected {expect}")
    return result


def append_regressions() -> None:
    text = TEST.read_text(encoding="utf-8")
    if "def test_whitespace_only_changed_source_requires_explicit_blank_marker" not in text:
        text += WHITESPACE_TEST
    if "def test_long_changed_line_uses_structural_exact_source_binding" not in text:
        text += LONG_TEST
    TEST.write_text(text, encoding="utf-8")


def prove_red() -> None:
    specs = (
        "tests/test_noema_class_evidence_observation_contract.py::test_whitespace_only_changed_source_requires_explicit_blank_marker",
        "tests/test_noema_class_evidence_observation_contract.py::test_long_changed_line_uses_structural_exact_source_binding",
    )
    for spec in specs:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", spec],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode == 0 or "1 failed" not in (result.stdout + result.stderr):
            raise SystemExit(f"expected focused RED regression did not fail exactly: {spec}")


def repair_source() -> None:
    text = GATE.read_text(encoding="utf-8")
    old = '''        source_marker = source_excerpt if source_excerpt else "<blank>"
        if source_marker not in observation:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                "must quote the exact source_excerpt (or <blank> for an empty line)"
            )
'''
    new = '''        source_is_blank = not source_excerpt.strip()
        source_marker = "<blank>" if source_is_blank else source_excerpt
        # Exact source identity is already established by equality against the
        # trusted changed-line map. Repetition inside bounded prose is an
        # anti-vacuity signal only when the source can fit; blank lines use
        # an explicit structural marker rather than incidental whitespace.
        if source_is_blank or len(source_excerpt) <= MAX_THREAD_BODY_CHARS:
            if source_marker not in observation:
                raise NoemaModelOutputError(
                    f"Noema adversarial probe {index} class_evidence.{field} observation "
                    "must quote the exact source_excerpt (or <blank> for an empty line)"
                )
'''
    if text.count(old) != 1:
        raise SystemExit(f"unexpected source quote guard count: {text.count(old)}")
    text = text.replace(old, new, 1)
    old_prompt = "The observation must quote that exact source_excerpt (or <blank>) and explain the claimed behavior."
    new_prompt = (
        "For an empty or whitespace-only source line the observation must quote <blank>; "
        "for a bounded nonblank source_excerpt it must quote the exact text. Longer nonblank "
        "lines remain exactly bound by source_excerpt equality while observation stays bounded "
        "and explains the claimed behavior."
    )
    if old_prompt in text:
        text = text.replace(old_prompt, new_prompt, 1)
    GATE.write_text(text, encoding="utf-8")


def update_traceability() -> None:
    dtext = DOCS.read_text(encoding="utf-8")
    heading = "## 2026-09-02 — Noema exact-source edge binding"
    if heading not in dtext:
        dtext = dtext.rstrip() + "\n\n" + heading + "\n\n"
        dtext += (
            "External exact-head review exposed two executable source-evidence edge defects: "
            "whitespace-only changed lines could be admitted by incidental spacing, while a "
            "nonblank changed line longer than the bounded observation field could become "
            "structurally impossible to admit. Exact identity remains equality between "
            "`class_evidence.source_excerpt` and the trusted changed-side diff map. Whitespace-only "
            "source now requires the explicit `<blank>` observation marker; over-cap nonblank lines "
            "remain exactly source-bound without requiring impossible prose repetition. Focused "
            "regressions preserve both contracts.\n"
        )
        DOCS.write_text(dtext, encoding="utf-8")

    ctext = CHANGELOG.read_text(encoding="utf-8")
    entry = (
        "- Harden Noema exact-source evidence edges: whitespace-only changed lines require "
        "`<blank>`, while over-cap nonblank lines retain exact structural source binding without "
        "impossible bounded-prose repetition.\n"
    )
    if entry not in ctext:
        marker = "## [Unreleased]\n"
        ctext = ctext.replace(marker, marker + entry, 1) if marker in ctext else entry + "\n" + ctext
        CHANGELOG.write_text(ctext, encoding="utf-8")


def prove_green() -> None:
    run(sys.executable, "-m", "pytest", "-q", "tests/test_noema_class_evidence_observation_contract.py", "tests/test_noema_observed_defect_corpus_current_main.py")
    run(sys.executable, "-m", "pytest", "-q", "tests/test_noema_*.py")
    run(sys.executable, "-m", "compileall", "-q", "scripts/ci")
    run("git", "diff", "--check")


def main() -> None:
    append_regressions()
    prove_red()
    repair_source()
    update_traceability()
    prove_green()
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
