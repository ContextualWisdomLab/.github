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
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def insert_after_first(path: str, anchors: tuple[str, ...], addition: str) -> None:
    text = read(path)
    for anchor in anchors:
        if anchor in text:
            write(path, text.replace(anchor, anchor + addition, 1))
            return
    raise SystemExit(f"{path}: none of the insertion anchors were present")


TAXONOMY_MODULE = '''#!/usr/bin/env python3
"""Deterministic admission contract for observed code-review defect probes."""

from __future__ import annotations

import os
import re
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
VACUOUS_OBSERVATIONS = frozenset(
    {
        "checked",
        "confirmed",
        "looks good",
        "no issue",
        "observed",
        "passes",
        "reviewed",
        "safe",
        "source inspection",
        "verified",
        "works as expected",
    }
)


def observed_probe_taxonomy_required(env_name: str) -> bool:
    """Return whether a reviewer publication path requires the observed corpus."""
    return os.environ.get(env_name, "").strip().casefold() in {"1", "true", "yes", "on"}


def canonical_observation(value: str) -> str:
    """Normalize witness text only for deterministic equality/containment checks."""
    return re.sub(r"\\s+", " ", value.strip()).casefold()


def observed_probe_class_evidence_error(
    probe: dict[str, Any],
    *,
    label: str,
) -> str:
    """Return why a claimed defect class lacks distinct semantic observations.

    Exact source identity is already enforced by the caller's changed-line / receipt
    gate.  This validator deliberately does *not* accept repeated coordinate objects as
    evidence: every class-specific field must carry a concrete observation and the
    parent evidence string must quote that observation under its field name.  This
    closes the externally observed failure mode where arbitrary labels plus repeated
    path/line references masqueraded as independent defect-class evidence.
    """
    probe_kind = probe.get("probe_kind")
    if not isinstance(probe_kind, str) or probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:
        return f"{label} requires probe_kind from the observed defect taxonomy"

    class_evidence = probe.get("class_evidence")
    required_fields = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[probe_kind]
    if not isinstance(class_evidence, dict) or set(class_evidence) != set(required_fields):
        expected = ", ".join(required_fields)
        return f"{label} class_evidence for {probe_kind} must contain exactly: {expected}"

    evidence = probe.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        return f"{label} requires parent evidence before class_evidence can be admitted"
    normalized_evidence = canonical_observation(evidence)
    hypothesis = canonical_observation(str(probe.get("hypothesis") or ""))
    attack = canonical_observation(str(probe.get("attack_or_counterexample") or ""))
    seen: set[str] = set()
    for field in required_fields:
        observation = class_evidence.get(field)
        if not isinstance(observation, str) or len(observation.strip()) < 16:
            return f"{label} class_evidence.{field} requires a concrete observation"
        normalized = canonical_observation(observation)
        if normalized in VACUOUS_OBSERVATIONS or len(normalized.split()) < 4:
            return f"{label} class_evidence.{field} is vacuous"
        if normalized in {hypothesis, attack}:
            return f"{label} class_evidence.{field} cannot merely restate hypothesis or attack text"
        if normalized in seen:
            return f"{label} class_evidence observations must be distinct"
        seen.add(normalized)
        tagged = canonical_observation(f"{field}={observation}")
        if tagged not in normalized_evidence:
            return f"{label} class_evidence.{field} must be quoted in probe evidence as {field}=<observation>"
    return ""
'''


DOCTORING = '''# Observed reviewer defect-probe taxonomy

## Incident class

Externally demonstrated CodeRabbitAI/Devin findings on `ContextualWisdomLab/noema#528` and central review PRs exposed concrete failure shapes worth preserving as executable review regressions: caller-owned mutable aliases escaping an immutable-looking boundary, changing getter/Proxy time-of-check/time-of-use behavior, execution identity confusion, a weak substring oracle that accepted `unreleased` for `released`, contradictory cross-document contracts, component-vs-host authority mistakes, omitted causal dependency context, coercion-boundary mistakes, and cancellation/retry/publication state-machine races.

These are observable defect cases, not proprietary wording and not a claim that Noema or OpenCode missed every historical instance or that either reviewer is superior to CodeRabbitAI, Devin, or another proprietary reviewer.

## Contract

Both Noema and OpenCode production publication paths require every adversarial probe to choose one closed `probe_kind`: `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, or `state_machine_race`. Material changes require at least two distinct classes.

A class label or repeated `path`/`line` object is not evidence. Every class has three named semantic witness fields in `class_evidence`. Each witness must be a concrete, distinct observation and must be repeated verbatim in the independently validated parent evidence as `field=<observation>`. OpenCode's existing exact current-head source-line receipt still binds that parent evidence to trusted changed-file bytes; Noema's changed-side diff validator supplies its exact-line bound. The model remains solely responsible for the hypothesis, counterexample, observed/source-backed evidence, and outcome; deterministic code validates only schema, diversity, non-vacuity, and provenance relationships.

Noema also rejects JSON booleans as line numbers before changed-line membership checks. Python equality makes `True == 1`, so accepting a boolean coordinate would let malformed model output impersonate changed line 1.

## Regression intent

The durable corpus actively attacks mutable-alias/immutability escapes; changing getter/Proxy TOCTOU; execution/tenant/request identity confusion; coercion and canonicalization boundaries; weak substring/vacuous test oracles; code/docs/schema/API contract contradictions; internal-vs-external authority overreach; omitted causal dependency context; and security/reliability state-machine races. A focused read-only CI workflow executes the corpus whenever its reviewer gates, prompts, dependency lock, or fixtures change.
'''


QUALITY_WORKFLOW = '''name: Observed Review Defect Corpus CI

on:
  pull_request:
    paths:
      - .github/workflows/noema-review.yml
      - .github/workflows/opencode-review-dispatch.yml
      - .github/workflows/review-observed-defect-corpus-quality-ci.yml
      - scripts/ci/noema_review_gate.py
      - scripts/ci/opencode_review_normalize_output.py
      - scripts/ci/review_probe_taxonomy.py
      - scripts/ci/opencode_review_prompt_template.md
      - scripts/ci/run_opencode_review_model_pool.sh
      - ci-review-prompt.md
      - code-reviewer-prompt.md
      - tests/test_review_observed_defect_probe_taxonomy.py
      - tests/test_noema_review_gate.py
      - tests/test_opencode_review_normalize_output.py
      - tests/test_opencode_agent_contract.py
      - requirements-opencode-review-ci-hashes.txt
      - docs/doctoring/observed-review-defect-probe-taxonomy.md
      - docs/product-technical-gap-baseline.md
      - ARCHITECTURE.md
      - CHANGELOG.md

permissions:
  contents: read

jobs:
  observed-review-defect-corpus:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - name: Checkout exact source
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install hash-locked review CI dependencies
        run: >-
          python3 -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-opencode-review-ci-hashes.txt
      - name: Verify observed reviewer defect corpus
        run: |
          set -euo pipefail
          PYTHONPATH=. python3 -m pytest -q \\
            tests/test_review_observed_defect_probe_taxonomy.py \\
            tests/test_noema_review_gate.py \\
            tests/test_opencode_review_normalize_output.py \\
            tests/test_opencode_agent_contract.py
          python3 -m compileall -q \\
            scripts/ci/noema_review_gate.py \\
            scripts/ci/opencode_review_normalize_output.py \\
            scripts/ci/review_probe_taxonomy.py \\
            tests/test_review_observed_defect_probe_taxonomy.py
          git diff --check
'''


def main() -> None:
    write("scripts/ci/review_probe_taxonomy.py", TAXONOMY_MODULE)
    write("docs/doctoring/observed-review-defect-probe-taxonomy.md", DOCTORING)
    write(".github/workflows/review-observed-defect-corpus-quality-ci.yml", QUALITY_WORKFLOW)

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
        "        line = probe.get(\"line\")\n        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:\n            return f\"adversarial probe {index} line must be a positive integer\"\n        if require_observed_taxonomy:\n            class_error = observed_probe_class_evidence_error(\n                probe, label=f\"adversarial probe {index}\"\n            )\n            if class_error:\n                return class_error\n            probe_kinds.add(str(probe[\"probe_kind\"]))\n        location_error = adversarial_probe_location_error(path, line)",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if result == \"APPROVE\":",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if require_observed_taxonomy and len(probe_kinds) < minimum_probes:\n        return (\n            \"adversarial_validation requires at least \"\n            f\"{minimum_probes} distinct probe_kind values for this changed-file scope\"\n        )\n\n    if result == \"APPROVE\":",
    )

    # Noema deterministic publication gate, exact-line canonicalization, and schema.
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n",
        "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\nfrom scripts.ci.review_probe_taxonomy import (\n    OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS,\n    observed_probe_class_evidence_error,\n    observed_probe_taxonomy_required,\n)\n",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "def validate_substantive_verdict(\n    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()\n) -> None:\n",
        "def _canonical_noema_changed_location(\n    record: dict[str, Any], *, label: str\n) -> tuple[str, int, str]:\n    \"\"\"Return an exact changed-side coordinate or reject JSON type aliases.\"\"\"\n    path = record.get(\"path\")\n    line = record.get(\"line\")\n    side = record.get(\"side\")\n    if not isinstance(path, str) or not path.strip():\n        raise NoemaModelOutputError(f\"{label} requires a non-empty path\")\n    if type(line) is not int or line <= 0:\n        raise NoemaModelOutputError(f\"{label} requires a canonical positive integer line\")\n    if side not in {\"LEFT\", \"RIGHT\"}:\n        raise NoemaModelOutputError(f\"{label} requires LEFT or RIGHT side\")\n    return path, line, side\n\n\ndef validate_substantive_verdict(\n    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()\n) -> None:\n",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "        location = (reviewed.get(\"path\"), reviewed.get(\"line\"), reviewed.get(\"side\"))\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema reviewed line {index} is not an exact changed-side line\")",
        "        location = _canonical_noema_changed_location(\n            reviewed, label=f\"Noema reviewed line {index}\"\n        )\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema reviewed line {index} is not an exact changed-side line\")",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    for index, probe in enumerate(probes, start=1):",
        "    require_observed_taxonomy = observed_probe_taxonomy_required(\n        \"NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY\"\n    )\n    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    probe_kinds: set[str] = set()\n    for index, probe in enumerate(probes, start=1):",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "        location = (probe.get(\"path\"), probe.get(\"line\"), probe.get(\"side\"))\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema adversarial probe {index} is not an exact changed-side line\")",
        "        location = _canonical_noema_changed_location(\n            probe, label=f\"Noema adversarial probe {index}\"\n        )\n        if location not in locations:\n            raise NoemaModelOutputError(f\"Noema adversarial probe {index} is not an exact changed-side line\")\n        if require_observed_taxonomy:\n            class_error = observed_probe_class_evidence_error(\n                probe, label=f\"adversarial probe {index}\"\n            )\n            if class_error:\n                raise NoemaModelOutputError(f\"Noema {class_error}\")\n            probe_kinds.add(str(probe[\"probe_kind\"]))",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "        if outcome == \"confirmed\":\n            confirmed.add((str(probe[\"path\"]), int(probe[\"line\"]), str(probe[\"side\"])))\n\n    if decision == \"approve\" and confirmed:",
        "        if outcome == \"confirmed\":\n            confirmed.add(location)\n\n    if require_observed_taxonomy and len(probe_kinds) < required_probes:\n        raise NoemaModelOutputError(\n            f\"Noema adversarial validation requires at least {required_probes} distinct probe_kind values\"\n        )\n\n    if decision == \"approve\" and confirmed:",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "                                    **location_example,\n                                    \"hypothesis\": \"...\",",
        "                                    **location_example,\n                                    \"probe_kind\": \"mutable_alias|time_of_check_time_of_use|execution_identity|coercion_boundary|test_oracle|cross_contract|authority_boundary|dependency_context|state_machine_race\",\n                                    \"class_evidence\": {\n                                        \"CLASS_FIELD_1\": \"concrete observed fact\",\n                                        \"CLASS_FIELD_2\": \"second distinct observed fact\",\n                                        \"CLASS_FIELD_3\": \"third distinct observed fact\",\n                                    },\n                                    \"hypothesis\": \"...\",",
    )
    replace_once(
        "scripts/ci/noema_review_gate.py",
        "                \"Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.\",\n                \"Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.\",",
        "                \"Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.\",\n                \"Classify every adversarial probe with one observed defect class and use distinct classes when multiple probes are required: mutable_alias, time_of_check_time_of_use, execution_identity, coercion_boundary, test_oracle, cross_contract, authority_boundary, dependency_context, state_machine_race.\",\n                \"A probe_kind label or repeated source coordinate is not evidence. class_evidence must use exactly the class-specific fields in this schema: \" + json.dumps(OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS, separators=(\",\", \":\")) + \". Give every field a distinct concrete observation and repeat it verbatim in evidence as field=<observation>.\",\n                \"Actively attack caller-owned mutable aliases and readonly illusions; changing getters or Proxies between validation and use; execution/tenant/request identity confusion; coercion at enum, key, digest, and identity boundaries; weak substring or vacuous test oracles; contradictions across PRD/ADR/architecture/changelog/API/schema contracts; component-vs-host authority overreach; omitted causal dependency context; and cancellation/retry/publication state-machine races.\",\n                \"Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.\",",
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

    # OpenCode prompts actively attack externally observed classes instead of generic prose only.
    observed_prompt = (
        " Every probe must also declare one `probe_kind` from `mutable_alias`, "
        "`time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, "
        "`test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, or "
        "`state_machine_race`; material changes must use at least two distinct classes. "
        "For the chosen class, fill exactly its three named `class_evidence` fields with "
        "distinct concrete observations and repeat each observation verbatim in the probe "
        "evidence as `field=<observation>`; a label, repeated path/line, or generic safety "
        "statement is not evidence. Actively try caller-owned alias mutation, changing "
        "getter/Proxy TOCTOU, execution/tenant/request identity mismatch, coercion and "
        "canonicalization edges, substring/vacuous negative controls, cross-file and "
        "cross-document contradictions, component-vs-host authority overreach, missing "
        "causal dependency context, and cancellation/retry/publication state-machine races."
    )
    for path in (
        "scripts/ci/opencode_review_prompt_template.md",
        "ci-review-prompt.md",
        "code-reviewer-prompt.md",
    ):
        insert_after_first(
            path,
            (
                "Adversarial validation is mandatory before every verdict.",
                "Perform an explicit adversarial phase before every verdict.",
                "Run a dedicated adversarial phase before the verdict.",
            ),
            observed_prompt,
        )

    replace_once(
        "scripts/ci/run_opencode_review_model_pool.sh",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n\t\tprintf 'Every probe must retain a supported observed-defect probe_kind plus its exact class_evidence semantic witness fields; each witness must also appear verbatim in evidence as field=<observation>, material changes require distinct probe_kind values, and schema repair must not erase or fabricate that evidence.\\n'\n",
    )

    # Architecture and traceability.
    replace_once(
        "ARCHITECTURE.md",
        "- OpenCode remains the review reasoner. Deterministic code may repair only\n  trusted `path:line` source-line digest bindings on LLM probes; it never\n  invents a hypothesis, observed result, or verdict.\n",
        "- OpenCode remains the review reasoner. Deterministic code may repair only\n  trusted `path:line` source-line digest bindings on LLM probes; it never\n  invents a hypothesis, observed result, or verdict.\n- Noema and OpenCode share a deterministic observed-defect probe taxonomy. Production\n  publication requires field-specific semantic observations bound into independently\n  validated probe evidence and distinct classes for material changes, so arbitrary\n  relabeling or repeated source coordinates cannot satisfy adversarial diversity.\n",
    )
    baseline = read("docs/product-technical-gap-baseline.md")
    marker = "# Product and Technical Gap Baseline\n"
    if marker not in baseline:
        raise SystemExit("baseline title anchor missing")
    baseline_entry = '''\n## 2026-09-02 — Shared Noema/OpenCode observed-defect review corpus\n\n**Closed gap:** both production reviewer publication paths now turn independently demonstrated defect shapes into a deterministic adversarial corpus. The taxonomy covers mutable aliases, changing-getter/Proxy TOCTOU, execution identity, coercion boundaries, weak/vacuous test oracles, cross-contract contradictions, authority boundaries, omitted causal dependency context, and state-machine races. Material changes require at least two distinct classes. Each class requires three distinct semantic observations quoted into the probe's independently validated evidence; repeated path/line objects no longer count as class proof. Noema also rejects JSON boolean line aliases before exact changed-line membership. This extends existing exact-head, current-source-line receipt, unresolved-thread, CodeGraph/dependency, and stale-evidence protections without claiming proprietary benchmark superiority. Regression provenance is the concrete CodeRabbitAI/Devin finding set on `ContextualWisdomLab/noema#528` plus central review incidents; executable coverage lives in `tests/test_review_observed_defect_probe_taxonomy.py` and `.github/workflows/review-observed-defect-corpus-quality-ci.yml`.\n\n'''
    write("docs/product-technical-gap-baseline.md", baseline.replace(marker, marker + baseline_entry, 1))

    changelog = read("CHANGELOG.md")
    change_anchor = "## [Unreleased]\n"
    if change_anchor not in changelog:
        raise SystemExit("CHANGELOG Unreleased anchor missing")
    change = '''- **Require semantic observed defect classes in both Noema and OpenCode reviews.**\n  Production review publication now rejects missing/unknown `probe_kind`, coordinate-only\n  or vacuous class witnesses, witnesses not quoted into parent evidence, JSON boolean Noema\n  line aliases, and material verdicts whose required probes all exercise the same defect\n  class. Reviewer and repair prompts explicitly attack mutable aliases, TOCTOU/getter races,\n  identity confusion, coercion boundaries, weak test oracles, cross-contract contradictions,\n  authority boundaries, missing dependency context, and state-machine races. A focused\n  read-only CI workflow keeps the shared false-negative corpus executable.\n'''
    write("CHANGELOG.md", changelog.replace(change_anchor, change_anchor + change, 1))


if __name__ == "__main__":
    main()
