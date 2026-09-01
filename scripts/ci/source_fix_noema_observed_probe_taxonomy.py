#!/usr/bin/env python3
"""One-shot source transform for the Noema observed-probe taxonomy repair."""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail closed on branch drift."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label}, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    """Apply the production, changelog, and baseline repair."""
    path = Path("scripts/ci/noema_review_gate.py")
    text = path.read_text(encoding="utf-8")

    anchor = 'DIFF_HUNK_RE = re.compile(r"^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@")\n'
    taxonomy = '''DIFF_HUNK_RE = re.compile(r"^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@")
OBSERVED_REVIEW_PROBE_KINDS = frozenset(
    {
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    }
)
'''
    text = replace_once(text, anchor, taxonomy, "diff-hunk anchor")

    old_validation = '''    confirmed: set[tuple[str, int, str]] = set()
    identities: set[tuple[Any, ...]] = set()
    for index, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            raise RuntimeError(f"Noema adversarial probe {index} must be an object")
        location = (probe.get("path"), probe.get("line"), probe.get("side"))
'''
    new_validation = '''    confirmed: set[tuple[str, int, str]] = set()
    identities: set[tuple[Any, ...]] = set()
    probe_kinds: set[str] = set()
    for index, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            raise RuntimeError(f"Noema adversarial probe {index} must be an object")
        probe_kind = probe.get("probe_kind")
        if probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:
            raise RuntimeError(
                f"Noema adversarial probe {index} requires probe_kind from the observed defect taxonomy"
            )
        probe_kinds.add(str(probe_kind))
        location = (probe.get("path"), probe.get("line"), probe.get("side"))
'''
    text = replace_once(text, old_validation, new_validation, "validation block")

    old_post_loop = '''        if outcome == "confirmed":
            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))

    if decision == "approve" and confirmed:
'''
    new_post_loop = '''        if outcome == "confirmed":
            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))

    if len(probe_kinds) < required_probes:
        raise RuntimeError(
            f"Noema {decision} requires at least {required_probes} distinct probe_kind values"
        )

    if decision == "approve" and confirmed:
'''
    text = replace_once(text, old_post_loop, new_post_loop, "post-probe block")

    old_schema = '''                                    **location_example,
                                    "hypothesis": "...",
'''
    new_schema = '''                                    **location_example,
                                    "probe_kind": "mutable_alias|time_of_check_time_of_use|execution_identity|coercion_boundary|test_oracle|cross_contract|authority_boundary|dependency_context|state_machine_race",
                                    "hypothesis": "...",
'''
    text = replace_once(text, old_schema, new_schema, "probe schema block")

    old_prompt = '''                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",
                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",
'''
    new_prompt = '''                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",
                "Classify every adversarial probe with one observed defect class and use distinct classes when multiple probes are required: mutable_alias, time_of_check_time_of_use, execution_identity, coercion_boundary, test_oracle, cross_contract, authority_boundary, dependency_context, state_machine_race.",
                "Actively attack caller-owned mutable aliases and readonly illusions; changing getters or Proxies between validation and use; execution/tenant/request identity confusion; JavaScript or serialization coercion at enum, key, digest, and identity boundaries; weak substring or vacuous test oracles; contradictions across PRD/ADR/architecture/changelog/contracts; component-vs-host authority overreach; omitted causal dependency context; and cancellation/retry/publication state-machine races.",
                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",
'''
    text = replace_once(text, old_prompt, new_prompt, "review prompt block")

    old_render = '''            lines.append(
                f"- `{probe.get('path')}:{probe.get('line')} ({probe.get('side')})` "
                f"{probe.get('outcome')}: {str(probe.get('hypothesis') or '').strip()} — "
                f"{str(probe.get('evidence') or '').strip()}"
            )
'''
    new_render = '''            lines.append(
                f"- `{probe.get('path')}:{probe.get('line')} ({probe.get('side')})` "
                f"[{probe.get('probe_kind')}] {probe.get('outcome')}: "
                f"{str(probe.get('hypothesis') or '').strip()} — "
                f"{str(probe.get('evidence') or '').strip()}"
            )
'''
    text = replace_once(text, old_render, new_render, "evidence-render block")
    path.write_text(text, encoding="utf-8")

    changelog = Path("CHANGELOG.md")
    changelog_text = changelog.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n"
    entry = (
        "- Noema formal reviews now classify adversarial probes against an executable corpus of observed "
        "reviewer defect classes (mutable aliases, TOCTOU, identity/coercion boundaries, weak oracles, "
        "cross-contract and authority contradictions, dependency context, and state-machine races), and "
        "material changes require distinct probe classes before approval.\n"
    )
    if entry not in changelog_text:
        changelog_text = replace_once(changelog_text, marker, marker + entry, "Unreleased heading")
        changelog.write_text(changelog_text, encoding="utf-8")

    baseline = Path("docs/product-technical-gap-baseline.md")
    baseline_text = baseline.read_text(encoding="utf-8")
    note_heading = "## 2026-09-01 — Noema observed-defect adversarial-probe corpus"
    if note_heading not in baseline_text:
        heading_end = baseline_text.find("\n")
        if heading_end < 0:
            raise SystemExit("product gap baseline has no heading line")
        note = f'''\n\n{note_heading}\n\nLive review evidence from `ContextualWisdomLab/noema#528` demonstrated several defect classes that an independent reviewer must actively attack rather than relying on generic correctness prose: Devin found caller-owned mutable checkpoint aliases, changing-getter/Proxy TOCTOU across validation and snapshot, and cross-execution identity confusion; CodeRabbit separately found a vacuous `toContain("released")` oracle and cross-document contract contradictions. The central Noema validator now requires every formal adversarial probe to carry an executable `probe_kind` from the observed corpus (`mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, `state_machine_race`). Material source/test changes already require two probes; they now must cover distinct classes so duplicated generic attacks cannot satisfy the gate. The prompt explicitly attacks these failure shapes and the published review evidence renders the class for auditability. This strengthens review evidence without claiming parity or superiority over proprietary reviewers; the corpus is grounded only in concrete, independently observed PR findings.\n'''
        baseline.write_text(
            baseline_text[: heading_end + 1] + note + baseline_text[heading_end + 1 :],
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
