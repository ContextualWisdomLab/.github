#!/usr/bin/env python3
"""Strict public entrypoint for Noema's independent pull-request reviewer.

The implementation core is kept in :mod:`scripts.ci._noema_review_core` so this
small admission layer can make review-completion semantics explicit.  Every
published verdict, including a GitHub ``COMMENT`` review, must carry the same
exact changed-line and adversarial evidence required of an approval.  A comment
is therefore non-blocking presentation, not an escape hatch from review proof.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

from scripts.ci import _noema_review_core as _core


_core_validate_substantive_verdict = _core.validate_substantive_verdict


def validate_substantive_verdict(
    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()
) -> None:
    """Validate every completed verdict, treating comments as non-blocking approvals.

    ``_noema_review_core`` historically returned before evidence validation for
    ``decision=comment``.  That let a model publish a completed review without a
    reviewed changed line or an observed-defect probe.  Comments are allowed as
    presentation semantics, but for admission they must prove the same
    falsification evidence as ``approve``.  A confirmed defect must therefore be
    expressed as ``request_changes`` rather than hidden inside a comment.
    """
    decision = str(verdict.get("decision") or "").strip().lower()
    if decision != "comment":
        _core_validate_substantive_verdict(verdict, diff, changed_paths)
        return

    evidence_verdict = dict(verdict)
    evidence_verdict["decision"] = "approve"
    _core_validate_substantive_verdict(evidence_verdict, diff, changed_paths)


# Production functions in the core resolve this global at call time.  Patch it
# once before exposing the module so call_llm(), direct validator callers, and
# CLI execution all share the same fail-closed admission contract.
_core.validate_substantive_verdict = validate_substantive_verdict


def main(argv: list[str]) -> int:
    """Run the Noema review core with strict completed-verdict admission."""
    return _core.main(argv)


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
else:
    # Preserve the long-standing public module surface and monkeypatch seams for
    # repository tests and callers.  The core already points at the strict
    # validator above, so returning that module object does not re-open the
    # historical comment bypass.
    sys.modules[__name__] = _core
