#!/usr/bin/env python3
"""One-shot writer for the observed reviewer defect taxonomy; removed after use."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


TAXONOMY_MODULE = '''#!/usr/bin/env python3
"""Deterministic admission contract for observed code-review defect probes."""

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
    """Return whether a reviewer publication path requires the observed corpus."""
    return os.environ.get(env_name, "").strip().casefold() in {"1", "true", "yes", "on"}


def observed_probe_class_evidence_error(
    probe: dict[str, Any],
    *,
    label: str,
    path: str,
    line: int,
    side: str | None = None,
) -> str:
    """Return why one class label is not bound to its exact source location."""
    probe_kind = probe.get("probe_kind")
    if not isinstance(probe_kind, str) or probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:
        return f"{label} requires probe_kind from the observed defect taxonomy"

    class_evidence = probe.get("class_evidence")
    required_fields = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[probe_kind]
    if not isinstance(class_evidence, dict) or set(class_evidence) != set(required_fields):
        expected = ", ".join(required_fields)
        return (
            f"{label} class_evidence for {probe_kind} must contain exactly: {expected}"
        )

    expected_keys = {"path", "line"} if side is None else {"path", "line", "side"}
    expected_location: dict[str, Any] = {"path": path, "line": line}
    if side is not None:
        expected_location["side"] = side
    for field in required_fields:
        source_ref = class_evidence.get(field)
        if not isinstance(source_ref, dict) or set(source_ref) != expected_keys:
            return f"{label} class_evidence.{field} requires a source-bound probe-location reference"
        if type(source_ref.get("line")) is not int or source_ref != expected_location:
            return f"{label} class_evidence.{field} must bind to the probe location"
    return ""
'''


DOCTORING = '''# Observed reviewer defect-probe taxonomy

## Incident class

Externally demonstrated review findings on `ContextualWisdomLab/noema#528` exposed concrete failure shapes worth preserving as executable review regressions: caller-owned mutable aliases escaping an immutable-looking boundary, changing getter/Proxy time-of-check/time-of-use behavior, execution identity confusion, a weak substring oracle that accepted `unreleased` for `released`, and contradictory cross-document contracts. Related central review incidents also showed component-vs-host authority mistakes, omitted causal dependency context, coercion-boundary mistakes, and cancellation/retry/publication state-machine races.

These are observed defect shapes, not a claim that Noema or OpenCode missed every historical instance and not a claim of parity or superiority over CodeRabbitAI, Devin, or any proprietary reviewer.

## Contract

Both Noema and OpenCode production publication paths require every adversarial probe to choose one closed `probe_kind`: `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, or `state_machine_race`. Material changes require at least two distinct classes.

A class label is not evidence. Every class has three named witness fields in `class_evidence`, and each witness is deterministically bound to the exact source location of that probe. Existing exact-head, source-line digest, changed-file, finding-anchor, and stale-evidence gates remain in force. The model must still supply the hypothesis, attack/counterexample, observed/source-backed evidence, and outcome; deterministic code only validates structure and provenance.

## Regression intent

The durable corpus must keep attacking mutable-alias/immutability escapes; changing getter/Proxy TOCTOU; execution/tenant/request identity confusion; coercion and canonicalization boundaries; weak substring/vacuous test oracles; code/docs/schema/API contract contradictions; internal-vs-external authority overreach; omitted causal dependency context; and security/reliability state-machine races. Reviewer prompts name these classes explicitly so they are attempted before a verdict rather than merely learned after an external reviewer finds them.
'''


def main() -> None:
    write("scripts/ci/review_probe_taxonomy.py", TAXONOMY_MODULE)
    write("docs/doctoring/observed-review-defect-probe-taxonomy.md", DOCTORING)

    # OpenCode deterministic publication gate.
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "from typing import Any\n\ntry:\n    from adversarial_evidence import (",
        "from typing import Any\n\ntry:\n    from review_probe_taxonomy import (\n        observed_probe_class_evidence_error,\n        observed_probe_taxonomy_required,\n    )\nexcept ModuleNotFoundError:  # pragma: no cover - package import path\n    from scripts.ci.review_probe_taxonomy import (\n        observed_probe_class_evidence_error,\n        observed_probe_taxonomy_required,\n    )\n\ntry:\n    from adversarial_evidence import (",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "    changed_files = current_changed_files()\n    confirmed_locations: set[tuple[str, int]] = set()\n    probe_identities: set[tuple[str, int, str, str, str, str]] = set()\n    for index, probe in enumerate(probes, start=1):",
        "    changed_files = current_changed_files()\n    require_observed_taxonomy = observed_probe_taxonomy_required(\n        \"OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY\"\n    )\n    confirmed_locations: set[tuple[str, int]] = set()\n    probe_identities: set[tuple[str, int, str, str, str, str]] = set()\n    probe_kinds: set[str] = set()\n    for index, probe in enumerate(probes, start=1):",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "        line = probe.get(\"line\")\n        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:\n            return f\"adversarial probe {index} line must be a positive integer\"\n        location_error = adversarial_probe_location_error(path, line)",
        "        line = probe.get(\"line\")\n        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:\n            return f\"adversarial probe {index} line must be a positive integer\"\n        if require_observed_taxonomy:\n            class_error = observed_probe_class_evidence_error(\n                probe,\n                label=f\"adversarial probe {index}\",\n                path=path,\n                line=line,\n            )\n            if class_error:\n                return class_error\n            probe_kinds.add(str(probe[\"probe_kind\"]))\n        location_error = adversarial_probe_location_error(path, line)",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if result == \"APPROVE\":",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if require_observed_taxonomy and len(probe_kinds) < minimum_probes:\n        return (\n            \"adversarial_validation requires at least \"\n            f\"{minimum_probes} distinct probe_kind values for this changed-file scope\"\n        )\n\n    if result == \"APPROVE\":",
    )

    # Noema deterministic publication gate and model schema.
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n",
        "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\nfrom scripts.ci.review_probe_taxonomy import (\n    OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS,\n    observed_probe_class_evidence_error,\n    observed_probe_taxonomy_required,\n)\n",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    for index, probe in enumerate(probes, start=1):",
        "    require_observed_taxonomy = observed_probe_taxonomy_required(\n        \"NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY\"\n    )\n    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    probe_kinds: set[str] = set()\n    for index, probe in enumerate(probes, start=1):",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "        location = (probe.get(\"path\"), probe.get(\"line\"), probe.get(\"side\"))\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema adversarial probe {index} is not an exact changed-side line\")",
        "        location = (probe.get(\"path\"), probe.get(\"line\"), probe.get(\"side\"))\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema adversarial probe {index} is not an exact changed-side line\")\n        if require_observed_taxonomy:\n            class_error = observed_probe_class_evidence_error(\n                probe,\n                label=f\"adversarial probe {index}\",\n                path=str(location[0]),\n                line=int(location[1]),\n                side=str(location[2]),\n            )\n            if class_error:\n                raise NoemaModelOutputError(f\"Noema {class_error}\")\n            probe_kinds.add(str(probe[\"probe_kind\"]))",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "        if outcome == \"confirmed\":\n            confirmed.add((str(probe[\"path\"]), int(probe[\"line\"]), str(probe[\"side\"])))\n\n    if decision == \"approve\" and confirmed:",
        "        if outcome == \"confirmed\":\n            confirmed.add((str(probe[\"path\"]), int(probe[\"line\"]), str(probe[\"side\"])))\n\n    if require_observed_taxonomy and len(probe_kinds) < required_probes:\n        raise NoemaModelOutputError(\n            f\"Noema adversarial validation requires at least {required_probes} distinct probe_kind values\"\n        )\n\n    if decision == \"approve\" and confirmed:",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "                                    **location_example,\n                                    \"hypothesis\": \"...\",",
        "                                    **location_example,\n                                    \"probe_kind\": \"mutable_alias|time_of_check_time_of_use|execution_identity|coercion_boundary|test_oracle|cross_contract|authority_boundary|dependency_context|state_machine_race\",\n                                    \"class_evidence\": {\"exact_fields_for_selected_probe_kind\": {**location_example}},\n                                    \"hypothesis\": \"...\",",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "                \"Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.\",\n                \"Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.\",",
        "                \"Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.\",\n                \"Classify every adversarial probe with one observed defect class and use distinct classes when multiple probes are required: mutable_alias, time_of_check_time_of_use, execution_identity, coercion_boundary, test_oracle, cross_contract, authority_boundary, dependency_context, state_machine_race.\",\n                \"A probe_kind label is not evidence by itself. class_evidence must use exactly the class-specific fields in this schema: \" + json.dumps(OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS, separators=(\",\", \":\")) + \". Every witness must repeat that probe's exact changed-side {path,line,side}; free-form or borrowed-line witnesses fail closed.\",\n                \"Actively attack caller-owned mutable aliases and readonly illusions; changing getters or Proxies between validation and use; execution/tenant/request identity confusion; coercion at enum, key, digest, and identity boundaries; weak substring or vacuous test oracles; contradictions across PRD/ADR/architecture/changelog/API/schema contracts; component-vs-host authority overreach; omitted causal dependency context; and cancellation/retry/publication state-machine races.\",\n                \"Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.\",",
    )

    # Production workflow admission flags.
    replace_once(
        ".github/workflows/noema-review.yml",
        "permissions:\n  contents: read\n  pull-requests: read\n  checks: read\n  id-token: write\n\njobs:",
        "permissions:\n  contents: read\n  pull-requests: read\n  checks: read\n  id-token: write\n\nenv:\n  NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY: \"1\"\n\njobs:",
    )
    replace_once(
        ".github/workflows/opencode-review-dispatch.yml",
        "permissions:\n  contents: read\n\njobs:",
        "permissions:\n  contents: read\n\nenv:\n  OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY: \"true\"\n\njobs:",
    )

    # OpenCode model prompts: make the externally observed classes first-class attacks.
    observed_prompt = (
        " In addition, every probe must declare one `probe_kind` from `mutable_alias`, "
        "`time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, "
        "`test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, or "
        "`state_machine_race`; material changes must use at least two distinct classes. "
        "Supply `class_evidence` with the selected class's three named witness fields, each "
        "bound to that probe's exact `path` and `line`. Actively try caller-owned alias "
        "mutation, changing getter/Proxy TOCTOU, execution/tenant/request identity mismatch, "
        "coercion/canonicalization edges, substring/vacuous negative controls, cross-file and "
        "cross-document contradictions, component-vs-host authority overreach, missing causal "
        "dependency context, and cancellation/retry/publication state-machine races."
    )
    for path in ("scripts/ci/opencode_review_prompt_template.md", "ci-review-prompt.md", "code-reviewer-prompt.md"):
        text = read(path)
        anchor = "Adversarial validation is mandatory before every verdict."
        if anchor not in text:
            anchor = "Perform an explicit adversarial phase before every verdict."
        if anchor not in text:
            anchor = "Run a dedicated adversarial phase before the verdict."
        if anchor not in text:
            raise SystemExit(f"{path}: adversarial prompt anchor not found")
        # Place the durable class contract at the start of the adversarial section once.
        text = text.replace(anchor, anchor + observed_prompt, 1)
        write(path, text)

    # Repair prompt must preserve the structured class contract rather than degrade it.
    replace_once(
        "scripts/ci/run_opencode_review_model_pool.sh",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n\t\tprintf 'Every probe must retain a supported observed-defect probe_kind plus its exact class_evidence witness fields; material changes require distinct probe_kind values, and schema repair must not erase or fabricate that evidence.\\n'\n",
    )

    # Architecture and traceability.
    replace_once(
        "ARCHITECTURE.md",
        "- OpenCode remains the review reasoner. Deterministic code may repair only\n  trusted `path:line` source-line digest bindings on LLM probes; it never\n  invents a hypothesis, observed result, or verdict.\n",
        "- OpenCode remains the review reasoner. Deterministic code may repair only\n  trusted `path:line` source-line digest bindings on LLM probes; it never\n  invents a hypothesis, observed result, or verdict.\n- Noema and OpenCode share a deterministic observed-defect probe taxonomy. Production\n  publication requires source-bound class witnesses and distinct classes for material\n  changes, so generic differently worded probes cannot satisfy adversarial diversity.\n",
    )
    baseline = read("docs/product-technical-gap-baseline.md")
    marker = "# Product and Technical Gap Baseline\n"
    if marker not in baseline:
        raise SystemExit("baseline title anchor missing")
    baseline_entry = '''\n## 2026-09-02 — Shared Noema/OpenCode observed-defect review corpus\n\n**Closed gap:** both production reviewer publication paths now turn independently demonstrated defect shapes into a deterministic, source-bound adversarial corpus. The closed taxonomy covers mutable aliases, changing-getter/Proxy TOCTOU, execution identity, coercion boundaries, weak/vacuous test oracles, cross-contract contradictions, authority boundaries, omitted causal dependency context, and state-machine races. Material changes require at least two distinct classes; every class carries exact probe-location witnesses. This extends existing exact-head, current-source-line digest, unresolved-thread, CodeGraph, and stale-evidence protections without claiming proprietary benchmark superiority. Regression source: concrete CodeRabbitAI/Devin findings recorded on `ContextualWisdomLab/noema#528` and central review incidents; verification lives in `tests/test_review_observed_defect_probe_taxonomy.py` and `docs/doctoring/observed-review-defect-probe-taxonomy.md`.\n\n'''
    write("docs/product-technical-gap-baseline.md", baseline.replace(marker, marker + baseline_entry, 1))

    changelog = read("CHANGELOG.md")
    change_anchor = "## [Unreleased]\n"
    if change_anchor not in changelog:
        raise SystemExit("CHANGELOG Unreleased anchor missing")
    change = '''- **Require source-bound observed defect classes in both Noema and OpenCode reviews.**\n  Production review publication now rejects missing/unknown `probe_kind`, borrowed or malformed\n  class witnesses, and material verdicts whose required probes all exercise the same defect\n  class. Reviewer and repair prompts explicitly attack mutable aliases, TOCTOU/getter races,\n  identity confusion, coercion boundaries, weak test oracles, cross-contract contradictions,\n  authority boundaries, missing dependency context, and state-machine races.\n'''
    write("CHANGELOG.md", changelog.replace(change_anchor, change_anchor + change, 1))


if __name__ == "__main__":
    main()
