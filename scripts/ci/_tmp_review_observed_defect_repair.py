#!/usr/bin/env python3
"""Temporary one-shot driver for the observed-defect review repair."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests/test_review_observed_defect_corpus.py"

RED_TESTS = dedent('''\
"""RED regressions for observed reviewer false-negative classes."""
from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import opencode_review_normalize_output as opencode

DIFF = """diff --git a/tool.py b/tool.py
new file mode 100644
--- /dev/null
+++ b/tool.py
@@ -0,0 +1,2 @@
+first = True
+second = True
"""


def _probe(line: int, suffix: str) -> dict[str, object]:
    return {
        "path": "tool.py",
        "line": line,
        "side": "RIGHT",
        "hypothesis": f"hypothesis {suffix}",
        "attack_or_counterexample": f"attack {suffix}",
        "evidence": f"observed evidence {suffix}",
        "outcome": "falsified",
    }


def _approval() -> dict[str, object]:
    return {
        "decision": "approve",
        "summary": "bounded review",
        "reviewed_lines": [{"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "checked"}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "bounded",
            "probes": [_probe(1, "one"), _probe(2, "two")],
        },
        "findings": [],
    }


def test_noema_rejects_boolean_line_alias(monkeypatch):
    monkeypatch.delenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", raising=False)
    verdict = _approval()
    verdict["reviewed_lines"][0]["line"] = True
    with pytest.raises(RuntimeError, match="positive integer line"):
        noema.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_noema_comment_cannot_bypass_required_evidence(monkeypatch):
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    with pytest.raises(noema.NoemaModelOutputError, match="reviewed changed line"):
        noema.validate_substantive_verdict(
            {"decision": "comment", "summary": "looks fine", "findings": []},
            DIFF,
            ["tool.py"],
        )


def test_opencode_requires_distinct_observed_probe_classes(monkeypatch):
    monkeypatch.setenv("OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    monkeypatch.setattr(opencode, "required_adversarial_probe_count", lambda: 2)
    monkeypatch.setattr(opencode, "current_changed_files", lambda: ["tool.py"])
    monkeypatch.setattr(opencode, "adversarial_probe_location_error", lambda *_: "")
    monkeypatch.setattr(opencode, "unreceipted_runtime_tool_claim", lambda *_: "")
    monkeypatch.setattr(opencode, "adversarial_evidence_rejection_reason", lambda *_: "")
    monkeypatch.setattr(opencode, "adversarial_probe_source_receipt_error", lambda *_: "")
    probes = []
    for line, suffix in ((1, "one"), (2, "two")):
        probe = _probe(line, suffix)
        probe.pop("side")
        probes.append(probe)
    result = opencode.adversarial_validation_error(
        {"status": "passed", "residual_risk": "bounded", "probes": probes},
        result="APPROVE",
        findings=[],
    )
    assert "probe_kind" in result
''')

TAXONOMY = dedent('''\
"""Shared observed defect taxonomy for Noema and OpenCode review gates.

The taxonomy is grounded in executable, externally demonstrated defect shapes.
It intentionally avoids proprietary reviewer wording and comparative superiority claims.
"""
from __future__ import annotations

import os
from typing import Any

OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "mutable_alias": ("alias_origin", "mutation_attempt", "post_validation_observation"),
    "time_of_check_time_of_use": ("check_observation", "intervening_change", "use_observation"),
    "execution_identity": ("incoming_identity", "retained_identity", "mismatch_guard"),
    "coercion_boundary": ("raw_value", "conversion_path", "canonicality_guard"),
    "test_oracle": ("assertion_under_test", "negative_control", "distinguishing_observation"),
    "cross_contract": ("first_contract", "second_contract", "contradiction_or_alignment"),
    "authority_boundary": ("component_authority", "external_authority", "enforcement_boundary"),
    "dependency_context": ("dependency", "omitted_or_included_context", "causal_effect"),
    "state_machine_race": ("initial_state", "event_order", "invariant_observation"),
}
OBSERVED_REVIEW_PROBE_KINDS = frozenset(OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS)


def observed_probe_taxonomy_required(env_name: str) -> bool:
    """Return whether a trusted workflow enables observed-class admission."""
    return os.environ.get(env_name, "").strip().casefold() in {"1", "true", "yes", "on"}


def observed_probe_taxonomy_prompt() -> str:
    """Return compact class-to-witness guidance shared by both review reasoners."""
    return "; ".join(
        f"{kind}=[{','.join(fields)}]"
        for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()
    )


def observed_probe_class_evidence_error(
    probe: dict[str, Any],
    *,
    index: int,
    path: str,
    line: int,
    side: str | None = None,
) -> str:
    """Validate one class witness against the probe's exact source location."""
    probe_kind = probe.get("probe_kind")
    if not isinstance(probe_kind, str) or probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:
        return f"adversarial probe {index} requires probe_kind from the observed defect taxonomy"
    required_fields = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[probe_kind]
    class_evidence = probe.get("class_evidence")
    if not isinstance(class_evidence, dict) or set(class_evidence) != set(required_fields):
        expected = ", ".join(required_fields)
        return (
            f"adversarial probe {index} class_evidence for {probe_kind} "
            f"must contain exactly: {expected}"
        )
    expected_keys = {"path", "line", "observation"}
    if side is not None:
        expected_keys.add("side")
    observations: set[str] = set()
    for field in required_fields:
        witness = class_evidence.get(field)
        if not isinstance(witness, dict) or set(witness) != expected_keys:
            return (
                f"adversarial probe {index} class_evidence.{field} requires "
                "an exact source-bound observation"
            )
        witness_path = witness.get("path")
        witness_line = witness.get("line")
        witness_side = witness.get("side") if side is not None else None
        observation = witness.get("observation")
        if witness_path != path or type(witness_line) is not int or witness_line != line:
            return (
                f"adversarial probe {index} class_evidence.{field} must bind "
                "to the probe path and positive integer line"
            )
        if side is not None and witness_side != side:
            return f"adversarial probe {index} class_evidence.{field} must bind to the probe side"
        if not isinstance(observation, str) or not observation.strip():
            return f"adversarial probe {index} class_evidence.{field} requires observation"
        normalized = " ".join(observation.split()).casefold()
        if normalized in observations:
            return (
                f"adversarial probe {index} class_evidence observations "
                "must be materially distinct"
            )
        observations.add(normalized)
    return ""
''')

FINAL_TESTS = dedent('''\
"""Executable corpus for independently observed review false-negative classes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import opencode_review_normalize_output as opencode
from scripts.ci.review_probe_taxonomy import (
    OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS,
    OBSERVED_REVIEW_PROBE_KINDS,
    observed_probe_class_evidence_error,
)

ROOT = Path(__file__).resolve().parents[1]
DIFF = """diff --git a/tool.py b/tool.py
new file mode 100644
--- /dev/null
+++ b/tool.py
@@ -0,0 +1,2 @@
+first = True
+second = True
"""


def _class_evidence(kind: str, line: int, *, side: str | None = "RIGHT") -> dict[str, object]:
    evidence: dict[str, object] = {}
    for index, field in enumerate(OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind], start=1):
        witness: dict[str, object] = {
            "path": "tool.py",
            "line": line,
            "observation": f"{kind} witness {index} observed",
        }
        if side is not None:
            witness["side"] = side
        evidence[field] = witness
    return evidence


def _probe(line: int, kind: str, *, side: str | None = "RIGHT") -> dict[str, object]:
    probe: dict[str, object] = {
        "path": "tool.py",
        "line": line,
        "probe_kind": kind,
        "class_evidence": _class_evidence(kind, line, side=side),
        "hypothesis": f"{kind} can violate the intended invariant",
        "attack_or_counterexample": f"exercise the {kind} counterexample",
        "evidence": f"bounded source or execution proof falsified {kind}",
        "outcome": "falsified",
    }
    if side is not None:
        probe["side"] = side
    return probe


def _noema_approval() -> dict[str, object]:
    return {
        "decision": "approve",
        "summary": "bounded review",
        "reviewed_lines": [{"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "checked"}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "bounded",
            "probes": [_probe(1, "mutable_alias"), _probe(2, "time_of_check_time_of_use")],
        },
        "findings": [],
    }


def _patch_opencode_evidence(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    monkeypatch.setattr(opencode, "required_adversarial_probe_count", lambda: 2)
    monkeypatch.setattr(opencode, "current_changed_files", lambda: ["tool.py"])
    monkeypatch.setattr(opencode, "adversarial_probe_location_error", lambda *_: "")
    monkeypatch.setattr(opencode, "unreceipted_runtime_tool_claim", lambda *_: "")
    monkeypatch.setattr(opencode, "adversarial_evidence_rejection_reason", lambda *_: "")
    monkeypatch.setattr(opencode, "adversarial_probe_source_receipt_error", lambda *_: "")


def test_corpus_covers_every_closed_observed_defect_class():
    corpus = json.loads((ROOT / "tests/fixtures/review_observed_defect_cases.json").read_text(encoding="utf-8"))
    assert {case["probe_kind"] for case in corpus} == OBSERVED_REVIEW_PROBE_KINDS
    assert all(case["observable_case"].strip() and case["source"].strip() for case in corpus)


def test_noema_rejects_boolean_line_alias(monkeypatch):
    monkeypatch.delenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", raising=False)
    verdict = _noema_approval()
    verdict["reviewed_lines"][0]["line"] = True
    with pytest.raises(noema.NoemaModelOutputError, match="positive integer line"):
        noema.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_noema_comment_cannot_bypass_required_evidence(monkeypatch):
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    with pytest.raises(noema.NoemaModelOutputError, match="reviewed changed line"):
        noema.validate_substantive_verdict(
            {"decision": "comment", "summary": "looks fine", "findings": []}, DIFF, ["tool.py"]
        )


def test_noema_requires_two_distinct_classes_for_material_change(monkeypatch):
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    verdict = _noema_approval()
    verdict["adversarial_validation"]["probes"] = [_probe(1, "mutable_alias"), _probe(2, "mutable_alias")]
    with pytest.raises(noema.NoemaModelOutputError, match="distinct probe_kind"):
        noema.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_noema_accepts_two_source_bound_observed_classes(monkeypatch):
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    noema.validate_substantive_verdict(_noema_approval(), DIFF, ["tool.py"])


def test_noema_taxonomy_failures_remain_typed_model_output(monkeypatch):
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    verdict = _noema_approval()
    verdict["adversarial_validation"]["probes"][0].pop("probe_kind")
    with pytest.raises(noema.NoemaModelOutputError, match="probe_kind"):
        noema.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_open_code_rejects_generic_probe_diversity(monkeypatch):
    _patch_opencode_evidence(monkeypatch)
    probes = []
    for line in (1, 2):
        probes.append({
            "path": "tool.py", "line": line, "hypothesis": f"generic {line}",
            "attack_or_counterexample": f"generic attack {line}",
            "evidence": f"generic evidence {line}", "outcome": "falsified",
        })
    error = opencode.adversarial_validation_error(
        {"status": "passed", "residual_risk": "bounded", "probes": probes},
        result="APPROVE", findings=[]
    )
    assert "probe_kind" in error


def test_open_code_rejects_relabelled_single_class(monkeypatch):
    _patch_opencode_evidence(monkeypatch)
    error = opencode.adversarial_validation_error(
        {"status": "passed", "residual_risk": "bounded", "probes": [
            _probe(1, "mutable_alias", side=None), _probe(2, "mutable_alias", side=None)
        ]}, result="APPROVE", findings=[]
    )
    assert "distinct probe_kind" in error


def test_open_code_accepts_distinct_source_bound_classes(monkeypatch):
    _patch_opencode_evidence(monkeypatch)
    error = opencode.adversarial_validation_error(
        {"status": "passed", "residual_risk": "bounded", "probes": [
            _probe(1, "mutable_alias", side=None), _probe(2, "test_oracle", side=None)
        ]}, result="APPROVE", findings=[]
    )
    assert error == ""


def test_class_witnesses_require_distinct_observations():
    probe = _probe(1, "state_machine_race")
    for witness in probe["class_evidence"].values():
        witness["observation"] = "same repeated sentence"
    error = observed_probe_class_evidence_error(probe, index=1, path="tool.py", line=1, side="RIGHT")
    assert "materially distinct" in error


def test_trusted_workflows_enable_observed_taxonomy():
    opencode_workflow = (ROOT / ".github/workflows/opencode-review.yml").read_text(encoding="utf-8")
    noema_workflow = (ROOT / ".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    assert 'OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY: "true"' in opencode_workflow
    assert 'export NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY="true"' in noema_workflow


def test_both_reasoners_receive_shared_taxonomy_guidance():
    noema_source = (ROOT / "scripts/ci/noema_review_gate.py").read_text(encoding="utf-8")
    opencode_prompt = (ROOT / "scripts/ci/opencode_review_prompt_template.md").read_text(encoding="utf-8")
    assert "observed_probe_taxonomy_prompt()" in noema_source
    for kind in OBSERVED_REVIEW_PROBE_KINDS:
        assert f"`{kind}`" in opencode_prompt
''')


def write_red() -> None:
    TEST.write_text(RED_TESTS, encoding="utf-8")


def patch_noema() -> None:
    path = ROOT / "scripts/ci/noema_review_gate.py"
    text = path.read_text(encoding="utf-8")
    marker = "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n"
    if marker not in text:
        raise SystemExit("Noema import marker missing")
    text = text.replace(
        marker,
        marker
        + "from scripts.ci.review_probe_taxonomy import (\n"
        + "    observed_probe_class_evidence_error,\n"
        + "    observed_probe_taxonomy_prompt,\n"
        + "    observed_probe_taxonomy_required,\n"
        + ")\n",
        1,
    )
    start = text.index("def validate_substantive_verdict(\n")
    end = text.index("def truncate_text(", start)
    validator = dedent('''\
    def _canonical_changed_location(record: dict[str, Any], label: str) -> tuple[str, int, str]:
        """Return one exact changed-side location without bool/int aliasing."""
        path_value = record.get("path")
        line_value = record.get("line")
        side_value = record.get("side")
        if not isinstance(path_value, str) or not path_value.strip():
            raise NoemaModelOutputError(f"{label} requires a canonical changed-side path")
        if type(line_value) is not int or line_value <= 0:
            raise NoemaModelOutputError(f"{label} requires a canonical positive integer line")
        if side_value not in {"LEFT", "RIGHT"}:
            raise NoemaModelOutputError(f"{label} requires canonical LEFT/RIGHT side")
        return (path_value, line_value, side_value)


    def validate_substantive_verdict(
        verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()
    ) -> None:
        """Reject completed verdicts without exact-line and observed-class evidence."""
        decision = str(verdict.get("decision") or "").strip().lower()
        require_observed = observed_probe_taxonomy_required("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY")
        if decision == "comment" and not require_observed:
            return
        evidence_decision = "approve" if decision == "comment" else decision
        locations = changed_diff_locations(diff)
        if not locations:
            raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")

        reviewed_lines = verdict.get("reviewed_lines")
        if not isinstance(reviewed_lines, list) or not reviewed_lines:
            raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")
        for index, reviewed in enumerate(reviewed_lines, start=1):
            if not isinstance(reviewed, dict):
                raise NoemaModelOutputError(f"Noema reviewed line {index} must be an object")
            location = _canonical_changed_location(reviewed, f"Noema reviewed line {index}")
            if location not in locations:
                raise NoemaModelOutputError(f"Noema reviewed line {index} is not an exact changed-side line")
            analysis = reviewed.get("analysis")
            if not isinstance(analysis, str) or not analysis.strip():
                raise NoemaModelOutputError(f"Noema reviewed line {index} requires concrete analysis")

        validation = verdict.get("adversarial_validation")
        if not isinstance(validation, dict):
            raise NoemaModelOutputError("Noema formal verdict requires adversarial_validation")
        status = validation.get("status")
        expected_status = "passed" if evidence_decision == "approve" else "failed"
        if status != expected_status:
            raise NoemaModelOutputError(
                f"Noema {decision} requires adversarial_validation.status={expected_status}"
            )
        residual_risk = validation.get("residual_risk")
        if not isinstance(residual_risk, str) or not residual_risk.strip():
            raise NoemaModelOutputError("Noema adversarial validation requires residual_risk")
        probes = validation.get("probes")
        all_changed_paths = set(changed_paths) or {path for path, _line, _side in locations}
        required_probes = 2 if any(changed_file_is_material(path) for path in all_changed_paths) else 1
        if not isinstance(probes, list) or len(probes) < required_probes:
            raise NoemaModelOutputError(
                f"Noema adversarial validation requires at least {required_probes} concrete probe(s)"
            )

        confirmed: set[tuple[str, int, str]] = set()
        identities: set[tuple[Any, ...]] = set()
        probe_kinds: set[str] = set()
        for index, probe in enumerate(probes, start=1):
            if not isinstance(probe, dict):
                raise NoemaModelOutputError(f"Noema adversarial probe {index} must be an object")
            location = _canonical_changed_location(probe, f"Noema adversarial probe {index}")
            if location not in locations:
                raise NoemaModelOutputError(
                    f"Noema adversarial probe {index} is not an exact changed-side line"
                )
            if require_observed:
                class_error = observed_probe_class_evidence_error(
                    probe, index=index, path=location[0], line=location[1], side=location[2]
                )
                if class_error:
                    raise NoemaModelOutputError(f"Noema {class_error}")
                probe_kinds.add(str(probe["probe_kind"]))
            for field in ("hypothesis", "attack_or_counterexample", "evidence"):
                value = probe.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise NoemaModelOutputError(f"Noema adversarial probe {index} requires {field}")
            outcome = probe.get("outcome")
            if outcome not in {"falsified", "confirmed"}:
                raise NoemaModelOutputError(
                    f"Noema adversarial probe {index} outcome must be falsified or confirmed"
                )
            identity = (
                *location,
                probe["hypothesis"].strip().casefold(),
                probe["attack_or_counterexample"].strip().casefold(),
            )
            if identity in identities:
                raise NoemaModelOutputError(f"Noema adversarial probe {index} duplicates an earlier probe")
            identities.add(identity)
            if outcome == "confirmed":
                confirmed.add(location)

        if require_observed and len(probe_kinds) < required_probes:
            raise NoemaModelOutputError(
                f"Noema {decision} requires at least {required_probes} distinct probe_kind values"
            )
        if evidence_decision == "approve" and confirmed:
            raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")
        if evidence_decision == "request_changes":
            finding_locations: set[tuple[str, int, str]] = set()
            for index, finding in enumerate(verdict.get("findings") or [], start=1):
                if not isinstance(finding, dict):
                    continue
                finding_location = _canonical_changed_location(
                    {"path": finding.get("file"), "line": finding.get("line"), "side": finding.get("side")},
                    f"Noema finding {index}",
                )
                if finding_location not in locations:
                    raise NoemaModelOutputError(f"Noema finding {index} is not an exact changed-side line")
                finding_locations.add(finding_location)
            if not confirmed or not confirmed.intersection(finding_locations):
                raise NoemaModelOutputError(
                    "Noema request_changes requires a confirmed probe on a published finding"
                )


    ''')
    text = text[:start] + validator + text[end:]

    shape = re.compile(
        r'(\s+\*\*location_example,\n)'
        r'(\s+"hypothesis": "\.\.\.",\n)'
        r'(\s+"attack_or_counterexample": "\.\.\.",\n)'
        r'(\s+"evidence": "observed or source-traced result",\n)'
        r'(\s+"outcome": "falsified\|confirmed",\n)'
    )
    match = shape.search(text)
    if not match:
        raise SystemExit("Noema probe JSON shape marker missing")
    indent = re.match(r"\s+", match.group(2)).group(0)
    replacement = (
        match.group(1)
        + f'{indent}"probe_kind": "mutable_alias",\n'
        + f'{indent}"class_evidence": {{\n'
        + f'{indent}    "alias_origin": {{**location_example, "observation": "caller-owned reference observed"}},\n'
        + f'{indent}    "mutation_attempt": {{**location_example, "observation": "post-validation mutation attempted"}},\n'
        + f'{indent}    "post_validation_observation": {{**location_example, "observation": "post-mutation invariant observed"}},\n'
        + f'{indent}}},\n'
        + match.group(2) + match.group(3) + match.group(4) + match.group(5)
    )
    text = text[:match.start()] + replacement + text[match.end():]
    guidance = (
        '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n'
    )
    if guidance not in text:
        raise SystemExit("Noema prompt guidance marker missing")
    text = text.replace(
        guidance,
        guidance
        + '                "Choose independent probe_kind values and populate every class_evidence witness with the exact probe path/line/side plus a concrete, distinct observation. Observed defect taxonomy: " + observed_probe_taxonomy_prompt(),\n',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_opencode() -> None:
    path = ROOT / "scripts/ci/opencode_review_normalize_output.py"
    text = path.read_text(encoding="utf-8")
    marker = "from typing import Any\n\n"
    if marker not in text:
        raise SystemExit("OpenCode import marker missing")
    text = text.replace(
        marker,
        marker
        + "try:\n"
        + "    from review_probe_taxonomy import (\n"
        + "        observed_probe_class_evidence_error,\n"
        + "        observed_probe_taxonomy_required,\n"
        + "    )\n"
        + "except ModuleNotFoundError:  # pragma: no cover - package import path\n"
        + "    from scripts.ci.review_probe_taxonomy import (\n"
        + "        observed_probe_class_evidence_error,\n"
        + "        observed_probe_taxonomy_required,\n"
        + "    )\n\n",
        1,
    )
    identities = (
        "    confirmed_locations: set[tuple[str, int]] = set()\n"
        "    probe_identities: set[tuple[str, int, str, str, str, str]] = set()\n"
    )
    if identities not in text:
        raise SystemExit("OpenCode probe identity marker missing")
    text = text.replace(
        identities,
        identities
        + "    probe_kinds: set[str] = set()\n"
        + "    require_observed = observed_probe_taxonomy_required(\n"
        + '        "OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY"\n'
        + "    )\n",
        1,
    )
    location = (
        "        if location_error:\n"
        "            return f\"adversarial probe {index} {location_error}\"\n"
        "        for field in (\"hypothesis\", \"attack_or_counterexample\", \"evidence\"):\n"
    )
    if location not in text:
        raise SystemExit("OpenCode probe location marker missing")
    text = text.replace(
        location,
        "        if location_error:\n"
        "            return f\"adversarial probe {index} {location_error}\"\n"
        "        if require_observed:\n"
        "            class_error = observed_probe_class_evidence_error(\n"
        "                probe, index=index, path=path, line=line\n"
        "            )\n"
        "            if class_error:\n"
        "                return class_error\n"
        "            probe_kinds.add(str(probe[\"probe_kind\"]))\n"
        "        for field in (\"hypothesis\", \"attack_or_counterexample\", \"evidence\"):\n",
        1,
    )
    start = text.index("def adversarial_validation_error(")
    result_pos = text.find('    if result == "APPROVE":\n', start)
    if result_pos < 0:
        raise SystemExit("OpenCode result marker missing")
    block = (
        "    if require_observed and len(probe_kinds) < minimum_probes:\n"
        "        return (\n"
        "            f\"adversarial_validation requires at least {minimum_probes} \"\n"
        "            \"distinct probe_kind values from the observed defect taxonomy\"\n"
        "        )\n\n"
    )
    text = text[:result_pos] + block + text[result_pos:]
    path.write_text(text, encoding="utf-8")


def patch_prompts_and_workflows() -> None:
    opwf = ROOT / ".github/workflows/opencode-review.yml"
    text = opwf.read_text(encoding="utf-8")
    if "OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY" in text:
        raise SystemExit("OpenCode taxonomy env unexpectedly exists")
    text, count = re.subn(
        r'^(\s*)OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION: "true"$',
        r'\1OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION: "true"\n\1OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY: "true"',
        text,
        flags=re.MULTILINE,
    )
    if count < 1:
        raise SystemExit("OpenCode adversarial env marker missing")
    opwf.write_text(text, encoding="utf-8")

    nowf = ROOT / ".github/workflows/noema-review.yml"
    text = nowf.read_text(encoding="utf-8")
    if "NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY" in text:
        raise SystemExit("Noema taxonomy env unexpectedly exists")
    marker = '          export NOEMA_LLM_MODEL="orchestrator/free"\n'
    if marker not in text:
        raise SystemExit("Noema orchestrator/free marker missing")
    nowf.write_text(
        text.replace(marker, marker + '          export NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY="true"\n', 1),
        encoding="utf-8",
    )

    prompt_path = ROOT / "scripts/ci/opencode_review_prompt_template.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    execution = "\n\nExecution provenance is mandatory."
    if execution not in prompt:
        raise SystemExit("OpenCode execution marker missing")
    paragraph = (
        "\n\nThe trusted production workflow requires observed-defect class diversity. Every adversarial "
        "probe must set `probe_kind` to one of `mutable_alias`, `time_of_check_time_of_use`, "
        "`execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, "
        "`authority_boundary`, `dependency_context`, or `state_machine_race`. Material changes "
        "require at least two distinct classes. Populate `class_evidence` with exactly the "
        "class-specific witnesses: mutable_alias=[alias_origin,mutation_attempt,post_validation_observation]; "
        "time_of_check_time_of_use=[check_observation,intervening_change,use_observation]; "
        "execution_identity=[incoming_identity,retained_identity,mismatch_guard]; "
        "coercion_boundary=[raw_value,conversion_path,canonicality_guard]; "
        "test_oracle=[assertion_under_test,negative_control,distinguishing_observation]; "
        "cross_contract=[first_contract,second_contract,contradiction_or_alignment]; "
        "authority_boundary=[component_authority,external_authority,enforcement_boundary]; "
        "dependency_context=[dependency,omitted_or_included_context,causal_effect]; "
        "state_machine_race=[initial_state,event_order,invariant_observation]. Each witness must "
        "repeat the probe's exact path and positive line and add a concrete `observation`; the "
        "observations within one probe must be distinct. These labels supplement rather than "
        "replace the existing exact current-head source-line SHA-256 receipt and proof requirements."
    )
    prompt = prompt.replace(execution, paragraph + execution, 1)
    old_example = (
        '{"path":"COPY_EXACT_PATH_FROM_TRUSTED_RECEIPT_SECTION","line":1,"hypothesis":"concrete failure hypothesis","attack_or_counterexample":"input, state, race, threat, or boundary used to challenge it","evidence":"trusted test/check/log/diff/source-trace outcome at matching path:line and exactly one copied source-line-sha256 receipt","outcome":"CHOOSE_FALSIFIED_OR_CONFIRMED"}'
    )
    new_example = (
        '{"path":"COPY_EXACT_PATH_FROM_TRUSTED_RECEIPT_SECTION","line":1,"probe_kind":"mutable_alias","class_evidence":{"alias_origin":{"path":"COPY_EXACT_PATH_FROM_TRUSTED_RECEIPT_SECTION","line":1,"observation":"concrete alias origin observation"},"mutation_attempt":{"path":"COPY_EXACT_PATH_FROM_TRUSTED_RECEIPT_SECTION","line":1,"observation":"concrete mutation attempt observation"},"post_validation_observation":{"path":"COPY_EXACT_PATH_FROM_TRUSTED_RECEIPT_SECTION","line":1,"observation":"concrete post-validation observation"}},"hypothesis":"concrete failure hypothesis","attack_or_counterexample":"input, state, race, threat, or boundary used to challenge it","evidence":"trusted test/check/log/diff/source-trace outcome at matching path:line and exactly one copied source-line-sha256 receipt","outcome":"CHOOSE_FALSIFIED_OR_CONFIRMED"}'
    )
    if old_example not in prompt:
        raise SystemExit("OpenCode control-block probe example missing")
    prompt_path.write_text(prompt.replace(old_example, new_example, 1), encoding="utf-8")


def write_corpus_and_docs() -> None:
    (ROOT / "scripts/ci/review_probe_taxonomy.py").write_text(TAXONOMY, encoding="utf-8")
    fixture_dir = ROOT / "tests/fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    corpus = [
        {"id": "noema-528-mutable-alias", "probe_kind": "mutable_alias", "observable_case": "caller-owned mutable state remains aliased after validation and can invalidate an invariant", "source": "ContextualWisdomLab/noema#528"},
        {"id": "noema-528-changing-getter", "probe_kind": "time_of_check_time_of_use", "observable_case": "a changing getter or Proxy can return a different value between validation and use", "source": "ContextualWisdomLab/noema#528"},
        {"id": "noema-528-execution-identity", "probe_kind": "execution_identity", "observable_case": "lifecycle state can retain one execution identity while a later request supplies another", "source": "ContextualWisdomLab/noema#528"},
        {"id": "github-1589-bool-line", "probe_kind": "coercion_boundary", "observable_case": "JSON true can compare equal to integer line 1 unless exact integer canonicality is enforced", "source": "ContextualWisdomLab/.github#1589"},
        {"id": "noema-528-substring-oracle", "probe_kind": "test_oracle", "observable_case": "a substring assertion can pass because released is contained inside unreleased", "source": "ContextualWisdomLab/noema#528"},
        {"id": "noema-528-doc-contract", "probe_kind": "cross_contract", "observable_case": "two changed documents can assert incompatible operating contracts while each looks locally plausible", "source": "ContextualWisdomLab/noema#528"},
        {"id": "github-1623-review-authority", "probe_kind": "authority_boundary", "observable_case": "target-repository reviewer authority must not be reused as central control-plane mutation authority", "source": "ContextualWisdomLab/.github#1623"},
        {"id": "github-1589-merge-base-context", "probe_kind": "dependency_context", "observable_case": "base-tip versus head context can omit causal merge-base dependency scope required to explain a change", "source": "ContextualWisdomLab/.github#1589"},
        {"id": "github-1589-workflow-lifecycle", "probe_kind": "state_machine_race", "observable_case": "temporary repair workflow creation, execution, deletion, and superseding pushes can race and leave active capacity or stale authority", "source": "ContextualWisdomLab/.github#1589"},
    ]
    (ROOT / "tests/fixtures/review_observed_defect_cases.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    TEST.write_text(FINAL_TESTS, encoding="utf-8")

    doctoring = dedent('''\
    # Observed-defect review corpus

    ## Decision

    Noema and OpenCode production review admission must attack independently observed defect
    shapes, not merely emit two differently worded generic probes. The shared taxonomy is
    executable policy in `scripts/ci/review_probe_taxonomy.py`; the corpus in
    `tests/fixtures/review_observed_defect_cases.json` records observable public cases and
    provenance without copying proprietary reviewer language or claiming benchmark superiority.

    ## Current classes and evidence

    The closed set covers mutable aliases, validation/use TOCTOU, execution identity,
    coercion/canonicality boundaries, weak test oracles, cross-contract contradictions, authority
    boundaries, omitted dependency context, and state-machine races. Material changes require two
    distinct classes when the trusted workflow enables the policy. Each class carries three named
    witnesses; every witness repeats the exact probe source coordinate and adds a distinct concrete
    observation. These labels supplement, rather than replace, OpenCode's changed-file manifest and
    SHA-256 source-line receipt or Noema's exact changed-side diff coordinate.

    ## Observable regression sources

    The initial corpus is grounded in public review evidence from `ContextualWisdomLab/noema#528`,
    `ContextualWisdomLab/.github#1589`, and `ContextualWisdomLab/.github#1623`. The cases cover
    mutable aliasing, changing-getter/Proxy TOCTOU, execution identity confusion, weak substring
    oracles, cross-document contradiction, bool/int line coercion, missing merge-base dependency
    context, reviewer/control-plane authority confusion, and workflow lifecycle races. The corpus
    means only that these defect shapes must be attacked; it does not claim one reviewer is
    universally better than another.

    ## Failure semantics

    Missing/unknown classes, repeated classes on a material verdict, malformed or bool line
    coordinates, vacuous/repeated class observations, or witnesses detached from the exact probe
    location fail closed. Production Noema comment verdicts also pass the same completed-review
    evidence admission instead of bypassing it. Noema taxonomy/schema failures remain typed
    `NoemaModelOutputError`, preserving the bounded repair behavior integrated by #1617.
    ''')
    (ROOT / "docs/doctoring/review-observed-defect-corpus.md").write_text(doctoring, encoding="utf-8")

    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n"
    entry = (
        "- **Require observed-defect diversity in production Noema/OpenCode review.** A shared "
        "closed taxonomy and executable corpus turn public external-review cases into active probes "
        "for mutable aliases, TOCTOU, identity confusion, coercion boundaries, weak test oracles, "
        "cross-contract contradictions, authority boundaries, missing dependency context, and "
        "state-machine races. Material reviews need two distinct source-bound classes; Noema also "
        "rejects bool-as-line aliases and production comment verdicts can no longer bypass "
        "completed-review evidence. Noema validation failures remain typed for #1617's bounded "
        "model-output repair path.\n"
    )
    if marker not in text:
        raise SystemExit("CHANGELOG marker missing")
    changelog.write_text(text.replace(marker, marker + entry, 1), encoding="utf-8")

    baseline = ROOT / "docs/product-technical-gap-baseline.md"
    text = baseline.read_text(encoding="utf-8")
    marker = "\n## 1. 근거와 범위\n"
    entry = dedent('''

    ## 2026-09-02 Noema/OpenCode observed-defect review-quality gap

    **Live owner state at repair convergence:** protected `.github/main` was
    `0774e29acd7d4688fa2224f1c6fe6c56a03bbbb6`, including #1617's typed/bounded Noema
    model-output repair. Open #1589 contains an older broad implementation but is materially behind
    live main and merge-conflicted, so this successor preserves current-main behavior and ports only
    the causal review-admission contract.

    **Observed gap:** current main required two adversarial probes for material changes but accepted
    two generic differently worded probes. Noema additionally compared Python tuple locations
    without exact integer canonicality, so JSON `true` could alias line `1`, and `decision=comment`
    returned before substantive evidence validation. Public external review evidence in noema#528
    and .github#1589/#1623 supplies durable defect shapes covering mutable aliasing, TOCTOU/changing
    getters, execution identity, weak/vacuous oracles, cross-contract contradiction, authority
    boundaries, dependency context, and lifecycle races.

    **Repair contract:** `scripts/ci/review_probe_taxonomy.py` is the shared closed taxonomy.
    Trusted Noema/OpenCode workflows enable class admission; material verdicts require at least two
    distinct classes, every class witness is exact-source-bound with a distinct observation, and all
    earlier cryptographic/source evidence remains mandatory. Noema taxonomy/schema rejections use
    `NoemaModelOutputError` so #1617's bounded corrective attempt retains typed diagnostics. No
    proprietary reviewer wording is copied and no benchmark superiority is claimed. Executable
    evidence lives in `tests/fixtures/review_observed_defect_cases.json` and
    `tests/test_review_observed_defect_corpus.py`.
    ''')
    if marker not in text:
        raise SystemExit("product gap marker missing")
    baseline.write_text(text.replace(marker, entry + marker, 1), encoding="utf-8")


def apply_green() -> None:
    (ROOT / "scripts/ci/review_probe_taxonomy.py").write_text(TAXONOMY, encoding="utf-8")
    patch_noema()
    patch_opencode()
    patch_prompts_and_workflows()
    write_corpus_and_docs()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("red", "green"))
    args = parser.parse_args()
    if args.mode == "red":
        write_red()
    else:
        apply_green()


if __name__ == "__main__":
    main()
