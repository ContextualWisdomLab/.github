#!/usr/bin/env python3
"""Repair PR #1682's directive routing provenance and 2026-09-02 doctoring trail."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTIVE = ROOT / "docs/product-goal-directive.md"
DOCTORING = ROOT / "docs/doctoring/product-goal-directive.md"
SELF = Path(__file__).resolve()
WORKFLOW = ROOT / ".github/workflows/_temp_pr1682_goal_directive_review_repair.yml"

OLD_ROUTING = """`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` and its doctoring records — `OpenCode` and
`Noema` use the fail-closed, ZDR-prioritized `orchestrator/free` pool; only `Strix` security analysis
uses the provider-diverse `orchestrator/auto` pool; private/internal review targets require an attested
ZDR-only catalog and never fall back to a non-ZDR provider. Do not loosen any CI consumer's pool or
credential scope on the strength of this section's general wording alone.
"""

NEW_ROUTING = """`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`, the merged workflow source, and executable
contract coverage — `OpenCode` and `Noema` use the fail-closed, ZDR-prioritized `orchestrator/free`
pool, and `Strix` is likewise hard-pinned to `orchestrator/free`. Private/internal review targets
still require an attested ZDR-only catalog and never fall back to a non-ZDR provider. Do not loosen
any CI consumer's pool or credential scope on the strength of this section's general wording alone.
"""

OLD_PIN = """true: `.github/workflows/strix.yml` now hardcodes `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL` to
`orchestrator/free` and fails closed on any other value — confirmed by the owner on 2026-09-02 (see
[[project-orchestrator-free-pin-confirmed]] in this repo's agent-memory record and ADR-0003's own
Decision section). `free_account_diversity`
"""

NEW_PIN = """true: `.github/workflows/strix.yml` now hardcodes `STRIX_MODEL`/`CONTEXTUAL_ORCHESTRATOR_POOL` to
`orchestrator/free` and fails closed on any other value. This is established by merged repository
source, its executable contract coverage, the CHANGELOG, and ADR-0003; it is an implementation fact,
not a claim that the owner accepted the remaining availability trade-off. `free_account_diversity`
"""

OLD_DOCTORING_ROUTE = """   exclusively by `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`:
   `OpenCode`/`Noema` → fail-closed `orchestrator/free`; `Strix` →
   `orchestrator/auto`; private/internal targets require an attested
   ZDR-only catalog.
"""

NEW_DOCTORING_ROUTE = """   exclusively by `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
   plus the merged workflow/contract source: `OpenCode`/`Noema` → fail-closed
   `orchestrator/free`; `Strix` → hard-pinned `orchestrator/free`;
   private/internal targets require an attested ZDR-only catalog. The older
   `Strix` → `orchestrator/auto` sentence is superseded by the merged pin flip.
"""

DOCTORING_APPEND = """

## 2026-09-02 directive sync and review reconciliation

The owner-authored nine-section directive changed materially on 2026-09-02. PR #1682 syncs that
text in place rather than creating a second copy. The durable changes include canonical-owner-first
core development, DB-backed/versioned i18n management, unified ontology ownership boundaries,
a narrow evidence-backed Python exception to the Rust-default computation rule, admin-configurable
unlimited-by-default model timeouts, and the new core-foundation ownership taxonomy.

Devin Review on exact head `ca6bd249b080c80493533c5cfd287fa7ac646c68` identified three valid
traceability/policy defects in the first sync commit, all repaired before merge:

1. A retained explanatory note still said Strix used `orchestrator/auto`, contradicting the merged
   `.github/workflows/strix.yml` and executable contract that hard-pin Strix to `orchestrator/free`.
   The note now reflects the merged source of truth.
2. A second note attributed that pin to an owner confirmation that the binding ADR did not record.
   The replacement cites repository evidence only and explicitly does not convert the remaining
   availability trade-off into accepted owner risk.
3. This doctoring record itself had not been advanced from 2026-08-30. This section records the
   2026-09-02 policy rewrite and its exact-head review reconciliation so future agents can reconstruct
   why the durable directive changed.

Evidence hierarchy for the routing statement is executable merged workflow/contract source first,
then the binding ADR and CHANGELOG. Private agent memory is not publication authority.
"""


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one reviewed fragment, failing closed on drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact fragment, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    """Apply all three reviewed fixes and delete one-shot repair artifacts."""
    directive = DIRECTIVE.read_text(encoding="utf-8")
    directive = replace_exact(directive, OLD_ROUTING, NEW_ROUTING, "routing policy")
    directive = replace_exact(directive, OLD_PIN, NEW_PIN, "pin provenance")
    if "only `Strix` security analysis\nuses the provider-diverse `orchestrator/auto` pool" in directive:
        raise RuntimeError("contradictory Strix auto-routing text remains")
    if "confirmed by the owner on 2026-09-02" in directive:
        raise RuntimeError("unrecorded owner-acceptance claim remains")
    DIRECTIVE.write_text(directive, encoding="utf-8")

    doctoring = DOCTORING.read_text(encoding="utf-8")
    doctoring = replace_exact(
        doctoring,
        OLD_DOCTORING_ROUTE,
        NEW_DOCTORING_ROUTE,
        "stale 2026-08-30 doctoring route",
    )
    marker = "## 2026-09-02 directive sync and review reconciliation"
    if marker not in doctoring:
        doctoring = doctoring.rstrip() + DOCTORING_APPEND + "\n"
    DOCTORING.write_text(doctoring, encoding="utf-8")

    WORKFLOW.unlink()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
