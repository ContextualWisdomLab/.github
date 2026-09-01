#!/usr/bin/env python3
"""One-shot current-main repair for OpenCode observed-defect probe admission."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, block: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + "\n" + block.rstrip() + "\n")


FIELDS = {
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


def main() -> None:
    helper = '''"""Deterministic semantic admission for observed reviewer defect probes."""
from __future__ import annotations

import os
from typing import Any

OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS = {
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
VACUOUS_OBSERVATIONS = frozenset({
    "works as expected", "looks correct", "seems correct", "appears correct",
    "no issue found", "no issues found", "safe", "valid", "passed", "falsified",
})


def observed_probe_taxonomy_required(env_name: str) -> bool:
    """Return whether the production caller enabled observed-defect admission."""
    return os.environ.get(env_name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _normalized(value: str) -> str:
    return " ".join(value.split()).strip()


def observed_probe_class_evidence_error(probe: dict[str, Any], *, label: str) -> str:
    """Return why one probe lacks class-specific semantic observations."""
    kind = probe.get("probe_kind")
    if not isinstance(kind, str) or kind not in OBSERVED_REVIEW_PROBE_KINDS:
        return f"{label} requires probe_kind from the observed defect taxonomy"
    class_evidence = probe.get("class_evidence")
    if not isinstance(class_evidence, dict):
        return f"{label} class_evidence must be an object"
    expected = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]
    if set(class_evidence) != set(expected):
        return f"{label} class_evidence must contain exactly: {', '.join(expected)}"
    parent_evidence = str(probe.get("evidence") or "")
    normalized_parent = _normalized(parent_evidence)
    hypothesis = _normalized(str(probe.get("hypothesis") or "")).casefold()
    attack = _normalized(str(probe.get("attack_or_counterexample") or "")).casefold()
    seen: set[str] = set()
    for field in expected:
        raw = class_evidence.get(field)
        if not isinstance(raw, str):
            return f"{label} class_evidence.{field} requires a concrete observation"
        observation = _normalized(raw)
        folded = observation.casefold()
        if len(observation) < 16 or len(observation.split()) < 4:
            return f"{label} class_evidence.{field} is vacuous"
        if folded in VACUOUS_OBSERVATIONS or folded in {hypothesis, attack}:
            return f"{label} class_evidence.{field} is vacuous"
        if folded in seen:
            return f"{label} class_evidence observations must be distinct"
        seen.add(folded)
        witness = _normalized(f"{field}={observation}")
        if witness not in normalized_parent:
            return f"{label} class_evidence.{field} must be quoted in probe evidence"
    return ""
'''
    write("scripts/ci/review_probe_taxonomy.py", helper)

    corpus = {
        "version": 1,
        "purpose": "Observable reviewer regression cases; no proprietary benchmark wording.",
        "cases": [
            {
                "id": "noema-533-readiness-entrypoint",
                "source": "ContextualWisdomLab/noema#533",
                "disposition": "false_positive",
                "probe_kind": "dependency_context",
                "observation": "A reviewer inferred that /ready was absent from src/index.ts while the public worker entrypoint src/runtime-entrypoint.ts routed /ready to runtimeReadinessResponse and route tests covered GET/HEAD success and failure states.",
                "expected_behavior": "Inspect the actual public entrypoint and causal routing chain before claiming a missing route.",
            },
            {
                "id": "noema-533-evaluator-contract",
                "source": "ContextualWisdomLab/noema#533",
                "disposition": "true_positive",
                "probe_kind": "cross_contract",
                "observation": "A production caller still consumed evaluator fields after the evaluator contract removed them, producing a nonzero audit path.",
                "expected_behavior": "Trace caller and callee contracts across files and require a regression proving the removed fields are not read.",
            },
            {
                "id": "noema-533-reporter-schema",
                "source": "ContextualWisdomLab/noema#533",
                "disposition": "true_positive",
                "probe_kind": "cross_contract",
                "observation": "The reporter shape drifted from the stable code/pass/detail contract and required restoration with executable coverage.",
                "expected_behavior": "Check producer/consumer schemas and stable external report contracts together.",
            },
            {
                "id": "appguardrail-1080-dns-toctou",
                "source": "ContextualWisdomLab/AppGuardrail#1080",
                "disposition": "true_positive",
                "probe_kind": "time_of_check_time_of_use",
                "observation": "DNS-derived authority could change between validation and use, so validation evidence alone did not bind the later network operation.",
                "expected_behavior": "Attack changing resolution/getter state between check and use and demand a binding invariant.",
            },
            {
                "id": "github-1623-authority-split",
                "source": "ContextualWisdomLab/.github#1623",
                "disposition": "false_positive",
                "probe_kind": "authority_boundary",
                "observation": "Dispatch authority and target-repository authority were intentionally split; collapsing them into one credential would widen privilege rather than repair a defect.",
                "expected_behavior": "Distinguish component authority from host/target authority before recommending permission widening.",
            },
            {
                "id": "bandscope-proxy-state",
                "source": "ContextualWisdomLab/BandScope observed review corpus",
                "disposition": "true_positive",
                "probe_kind": "mutable_alias",
                "observation": "Proxy or getter-backed state could change after a shallow validation read, escaping a readonly or snapshot assumption.",
                "expected_behavior": "Mutate caller-owned aliases or change getter results after validation and observe the actual consumed state.",
            },
            {
                "id": "bandscope-media-state-race",
                "source": "ContextualWisdomLab/BandScope observed review corpus",
                "disposition": "true_positive",
                "probe_kind": "state_machine_race",
                "observation": "Cancellation, retry, and publication ordering could produce a state transition that unit happy paths did not cover.",
                "expected_behavior": "Enumerate event orderings and assert the invariant after cancellation/retry/publication races.",
            },
        ],
    }
    write("tests/fixtures/review_observed_defect_cases.json", json.dumps(corpus, indent=2, ensure_ascii=False) + "\n")

    # Wire the semantic taxonomy into the OpenCode publication gate.
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "except ModuleNotFoundError:  # pragma: no cover - package import path\n    from scripts.ci.adversarial_evidence import (\n        SOURCE_LINE_RECEIPT_RE,\n        adversarial_evidence_rejection_reason,\n    )\n\nSTRUCTURAL_FAILURE_PHRASES = (",
        "except ModuleNotFoundError:  # pragma: no cover - package import path\n    from scripts.ci.adversarial_evidence import (\n        SOURCE_LINE_RECEIPT_RE,\n        adversarial_evidence_rejection_reason,\n    )\n\ntry:\n    from review_probe_taxonomy import (\n        observed_probe_class_evidence_error,\n        observed_probe_taxonomy_required,\n    )\nexcept ModuleNotFoundError:  # pragma: no cover - package import path\n    from scripts.ci.review_probe_taxonomy import (\n        observed_probe_class_evidence_error,\n        observed_probe_taxonomy_required,\n    )\n\nSTRUCTURAL_FAILURE_PHRASES = (",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "    changed_files = current_changed_files()\n    confirmed_locations: set[tuple[str, int]] = set()\n    probe_identities: set[tuple[str, int, str, str, str, str]] = set()",
        "    changed_files = current_changed_files()\n    confirmed_locations: set[tuple[str, int]] = set()\n    probe_identities: set[tuple[str, int, str, str, str, str]] = set()\n    require_observed_taxonomy = observed_probe_taxonomy_required(\n        \"OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY\"\n    )\n    probe_kinds: set[str] = set()",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "        location_error = adversarial_probe_location_error(path, line)\n        if location_error:\n            return f\"adversarial probe {index} {location_error}\"\n        for field in (\"hypothesis\", \"attack_or_counterexample\", \"evidence\"):",
        "        location_error = adversarial_probe_location_error(path, line)\n        if location_error:\n            return f\"adversarial probe {index} {location_error}\"\n        if require_observed_taxonomy:\n            class_error = observed_probe_class_evidence_error(\n                probe, label=f\"adversarial probe {index}\"\n            )\n            if class_error:\n                return class_error\n            probe_kinds.add(str(probe[\"probe_kind\"]))\n        for field in (\"hypothesis\", \"attack_or_counterexample\", \"evidence\"):",
    )
    replace_once(
        "scripts/ci/opencode_review_normalize_output.py",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if result == \"APPROVE\":",
        "        if outcome == \"confirmed\":\n            confirmed_locations.add((path, line))\n\n    if require_observed_taxonomy and len(probe_kinds) < minimum_probes:\n        return (\n            \"adversarial_validation requires at least \"\n            f\"{minimum_probes} distinct probe_kind values\"\n        )\n\n    if result == \"APPROVE\":",
    )

    # Enable the contract only on the privileged production review path.
    replace_once(
        ".github/workflows/opencode-review-dispatch.yml",
        "permissions:\n  contents: read\n\njobs:",
        "permissions:\n  contents: read\n\nenv:\n  OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY: \"true\"\n\njobs:",
    )

    prompt_contract = '''\n\n## Observed-defect adversarial corpus\nEvery adversarial probe must declare exactly one `probe_kind` from `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, or `state_machine_race`. For material source/test changes, use at least two distinct classes. Add `class_evidence` containing exactly the three class-specific observations required by `scripts/ci/review_probe_taxonomy.py`; each observation must be a distinct concrete fact and must also appear verbatim in the parent probe `evidence` as `field=<observation>`. A class label, repeated coordinate, generic safety statement, or implementation restatement is not evidence. Actively attack caller-owned mutable aliases and readonly illusions, changing getter/Proxy state between validation and use, execution/tenant/request identity confusion, enum/key/digest/identity coercion boundaries, substring/vacuous test oracles, contradictions across source/API/schema/PRD/ADR/architecture/changelog contracts, component-vs-host authority overreach, omitted causal dependency context, and cancellation/retry/publication state-machine races. Distinguish confirmed defects from false positives by tracing the actual public entrypoint and authority/dependency chain before publishing a finding.\n'''
    for path in ("scripts/ci/opencode_review_prompt_template.md", "ci-review-prompt.md", "code-reviewer-prompt.md"):
        append_once(path, "## Observed-defect adversarial corpus", prompt_contract)

    # Update the canonical control-block illustration so valid output is easy to produce.
    template = read("scripts/ci/opencode_review_prompt_template.md")
    old_probe = '\"line\":1,\"hypothesis\":\"concrete failure hypothesis\"'
    if old_probe in template:
        new_probe = ('\"line\":1,\"probe_kind\":\"dependency_context\",'
                     '\"class_evidence\":{\"dependency\":\"public entrypoint routes into the changed dependency\",'
                     '\"omitted_or_included_context\":\"review included the public entrypoint and downstream handler\",'
                     '\"causal_effect\":\"the traced dependency preserves the changed behavior at this line\"},'
                     '\"hypothesis\":\"concrete failure hypothesis\"')
        write("scripts/ci/opencode_review_prompt_template.md", template.replace(old_probe, new_probe, 1))
    else:
        raise SystemExit("OpenCode prompt control-block probe anchor missing")

    # Keep schema-repair attempts from erasing the newly required semantic witness.
    replace_once(
        "scripts/ci/run_opencode_review_model_pool.sh",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n",
        "\t\tprintf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection claims, implementation restatements, or a digest borrowed from another line remain invalid.\\n'\n\t\tprintf 'Preserve probe_kind and its exact class_evidence semantic witness fields during schema repair; every witness must also appear verbatim in evidence as field=<observation>, and material reviews require distinct probe_kind values.\\n'\n",
    )

    # Add corpus structure checks to the RED regression file after production repair is applied.
    test_path = "tests/test_opencode_observed_defect_probe_taxonomy.py"
    tests = read(test_path)
    fixture_test = '''\n\ndef test_durable_corpus_contains_true_and_false_observed_cases():\n    import json\n    from pathlib import Path\n\n    payload = json.loads(Path("tests/fixtures/review_observed_defect_cases.json").read_text(encoding="utf-8"))\n    cases = payload["cases"]\n    assert {case["disposition"] for case in cases} == {"true_positive", "false_positive"}\n    assert {"dependency_context", "authority_boundary", "time_of_check_time_of_use", "mutable_alias", "state_machine_race"}.issubset(\n        {case["probe_kind"] for case in cases}\n    )\n    assert all(case["observation"].strip() and case["expected_behavior"].strip() for case in cases)\n\n\ndef test_production_dispatch_and_prompts_require_observed_taxonomy():\n    from pathlib import Path\n\n    dispatch = Path(".github/workflows/opencode-review-dispatch.yml").read_text(encoding="utf-8")\n    prompt = Path("scripts/ci/opencode_review_prompt_template.md").read_text(encoding="utf-8")\n    pool = Path("scripts/ci/run_opencode_review_model_pool.sh").read_text(encoding="utf-8")\n    assert 'OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY: "true"' in dispatch\n    assert "## Observed-defect adversarial corpus" in prompt\n    assert "mutable_alias" in prompt and "dependency_context" in prompt and "state_machine_race" in prompt\n    assert "Preserve probe_kind" in pool\n'''
    if "test_durable_corpus_contains_true_and_false_observed_cases" not in tests:
        write(test_path, tests.rstrip() + fixture_test + "\n")

    quality_workflow = '''name: Review observed-defect corpus quality\n\non:\n  pull_request:\n    paths:\n      - scripts/ci/opencode_review_normalize_output.py\n      - scripts/ci/review_probe_taxonomy.py\n      - scripts/ci/opencode_review_prompt_template.md\n      - scripts/ci/run_opencode_review_model_pool.sh\n      - ci-review-prompt.md\n      - code-reviewer-prompt.md\n      - tests/test_opencode_observed_defect_probe_taxonomy.py\n      - tests/fixtures/review_observed_defect_cases.json\n      - .github/workflows/review-observed-defect-corpus-quality-ci.yml\n\npermissions:\n  contents: read\n\njobs:\n  observed-defect-corpus:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 15\n    steps:\n      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065\n        with:\n          python-version: '3.12'\n      - name: Install hash-locked review test dependencies\n        run: python -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-opencode-review-ci-hashes.txt\n      - name: Verify observed-defect admission and adjacent OpenCode contracts\n        env:\n          PYTHONPATH: .\n        run: python -m pytest -q tests/test_opencode_observed_defect_probe_taxonomy.py tests/test_opencode_review_normalize_output.py tests/test_opencode_existing_approval_gate.py tests/test_opencode_agent_contract.py\n'''
    write(".github/workflows/review-observed-defect-corpus-quality-ci.yml", quality_workflow)

    doctor = '''# Observed review defect probe taxonomy\n\nOpenCode review publication uses a deterministic semantic taxonomy to turn demonstrated review misses and false positives into executable regressions. The closed classes are `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, and `state_machine_race`.\n\nA label alone is never proof. Each class has exactly three named semantic witness fields in `scripts/ci/review_probe_taxonomy.py`; every witness must be concrete, distinct, and quoted verbatim into the independently source-receipted probe evidence. Material reviews require distinct probe classes. This prevents two differently worded generic probes or repeated coordinates from satisfying adversarial diversity.\n\nThe durable observable-case corpus is `tests/fixtures/review_observed_defect_cases.json`. It deliberately contains both confirmed defects and false-positive corrections so reviewer quality is evaluated on finding real defects without inventing defects when an omitted entrypoint, dependency, or authority boundary explains the code. The corpus records observable ContextualWisdomLab cases rather than proprietary reviewer wording and makes no benchmark-superiority claim.\n'''
    write("docs/doctoring/observed-review-defect-probe-taxonomy.md", doctor)

    append_once(
        "ARCHITECTURE.md",
        "## Observed-defect review admission (2026-09-02)",
        '''## Observed-defect review admission (2026-09-02)\nOpenCode remains the review reasoner; deterministic code does not invent findings. Before publication, the control plane now admits adversarial probes only when they carry a supported observed-defect class, class-specific semantic observations, exact current-head changed-line/source receipts, and distinct classes for material reviews. This composes with CodeGraph/dependency context, exact-head identity, stale-evidence rejection, and existing review-thread gates. The false-positive side of the corpus is equally important: dependency and authority context must be traced before a blocker is published.''',
    )
    append_once(
        "docs/product-technical-gap-baseline.md",
        "## 2026-09-02 — OpenCode observed-defect false-negative/false-positive corpus",
        '''## 2026-09-02 — OpenCode observed-defect false-negative/false-positive corpus\n\n**Closed gap:** production OpenCode review admission no longer accepts two merely different generic adversarial prose objects as evidence of material review diversity. The privileged dispatch enables a closed observed-defect taxonomy; class-specific semantic witnesses must be distinct, concrete, quoted into the independently current-source-receipted probe, and material changes require distinct classes. Reviewer prompts actively attack mutable aliases, getter/Proxy TOCTOU, identity and coercion boundaries, weak test oracles, cross-contract contradictions, authority overreach, missing dependency context, and state-machine races. The durable corpus also records false-positive corrections such as the noema#533 `/ready` public-entrypoint case and `.github#1623` split-authority case, so higher defect recall is not purchased by context-blind findings. Executable regression coverage lives in `tests/test_opencode_observed_defect_probe_taxonomy.py` and the focused read-only corpus CI workflow. No proprietary wording or unsupported benchmark-superiority claim is used.''',
    )
    changelog = read("CHANGELOG.md")
    marker = "## [Unreleased]\n"
    entry = '''- **Require observed-defect semantic witnesses in production OpenCode reviews.** Material verdicts now need distinct adversarial defect classes, each with class-specific concrete observations bound into exact current-head source evidence. The regression corpus covers both externally demonstrated true positives and false-positive corrections, including dependency-context and authority-boundary mistakes. Reviewer prompts and schema-repair guidance now actively preserve these witnesses.\n'''
    if entry not in changelog:
        if marker not in changelog:
            raise SystemExit("CHANGELOG Unreleased anchor missing")
        write("CHANGELOG.md", changelog.replace(marker, marker + entry, 1))


if __name__ == "__main__":
    main()
