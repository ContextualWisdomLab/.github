#!/usr/bin/env python3
"""One-shot source repair for PR #1644; the workflow removes this file after validation."""

from pathlib import Path

PATH = Path("scripts/ci/reconcile_ruleset_governance.py")
text = PATH.read_text(encoding="utf-8")

replacements = [
    (
        '''class RulesetMutationNotVisibleError(RulesetGovernanceError):
    """Raised while an ambiguous PUT has not yet appeared in immutable history."""
''',
        '''class RulesetMutationNotVisibleError(RulesetGovernanceError):
    """Raised while an ambiguous PUT has not yet appeared in immutable history."""


class RulesetMutationStillSettlingError(RulesetGovernanceError):
    """Raised when history changed but the ambiguous reviewed PUT is not visible yet."""
''',
        "mutation settlement error class",
    ),
    (
        '''def _settle_ambiguous_recovery_history(
    target: RulesetTarget,
    *,
    current_version: int,
) -> list[Any]:
    """Wait one bounded client horizon for an ambiguous recovery PUT to appear."""

    for poll_index in range(AMBIGUOUS_WRITE_SETTLEMENT_POLLS):
        history = _gh_api_list("GET", f"{target.history_endpoint}?per_page=2")
        if not history:
            raise RulesetGovernanceError(
                "ambiguous ruleset recovery PUT exposed no history"
            )
        if _history_version_id(history[0]) != current_version:
            return history
        if poll_index < AMBIGUOUS_WRITE_SETTLEMENT_POLLS - 1:
            time.sleep(AMBIGUOUS_WRITE_SETTLEMENT_INTERVAL_SECONDS)
    raise RulesetGovernanceError(
        "ambiguous ruleset recovery PUT outcome remains unresolved after settlement window"
    )
''',
        '''def _settle_ambiguous_recovery_history(
    target: RulesetTarget,
    *,
    current_version: int,
    expected_payload: dict[str, Any],
) -> list[Any]:
    """Observe the full bounded horizon until the ambiguous recovery PUT appears.

    An administrator version can become visible before a delayed recovery request.
    That intervening version is evidence of concurrency, not evidence that the
    delayed request was rejected. Settlement therefore waits for the exact restore
    payload and lets the caller recover its actual immutable predecessor.
    """

    for poll_index in range(AMBIGUOUS_WRITE_SETTLEMENT_POLLS):
        history = _gh_api_list("GET", f"{target.history_endpoint}?per_page=2")
        if not history:
            raise RulesetGovernanceError(
                "ambiguous ruleset recovery PUT exposed no history"
            )
        newest_version = _history_version_id(history[0])
        if newest_version != current_version:
            newest_state = _history_version_state(target, newest_version)
            if _editable_projection(newest_state) == expected_payload:
                return history
        if poll_index < AMBIGUOUS_WRITE_SETTLEMENT_POLLS - 1:
            time.sleep(AMBIGUOUS_WRITE_SETTLEMENT_INTERVAL_SECONDS)
    raise RulesetGovernanceError(
        "ambiguous ruleset recovery PUT outcome remains unresolved after settlement window"
    )
''',
        "ambiguous recovery settlement",
    ),
    (
        '''            history = _settle_ambiguous_recovery_history(
                target,
                current_version=current_version,
            )
''',
        '''            history = _settle_ambiguous_recovery_history(
                target,
                current_version=current_version,
                expected_payload=displaced_payload,
            )
''',
        "recovery settlement call",
    ),
    (
        '''    newest_state = _history_version_state(target, newest_id)
    if _editable_projection(newest_state) != desired:
        raise RulesetGovernanceError("latest ruleset history does not match reviewed mutation")
''',
        '''    newest_state = _history_version_state(target, newest_id)
    if _editable_projection(newest_state) != desired:
        raise RulesetMutationStillSettlingError(
            "latest ruleset history changed before the reviewed mutation became visible"
        )
''',
        "initial ambiguous history mismatch",
    ),
    (
        '''        except RulesetMutationNotVisibleError:
            live = _gh_api("GET", target.endpoint)
''',
        '''        except (RulesetMutationNotVisibleError, RulesetMutationStillSettlingError):
            live = _gh_api("GET", target.endpoint)
''',
        "initial ambiguous settlement catch",
    ),
    (
        '''    response can occur after GitHub accepted the update. Three observations span
    one additional full client timeout horizon: start, midpoint, and end. A
    baseline-only first observation is therefore never represented as rejection.
    Acceptance must become visible in immutable history and live state; collision
''',
        '''    response can occur after GitHub accepted the update. Three observations span
    one additional full client timeout horizon: start, midpoint, and end. Neither
    a baseline-only observation nor an intervening administrator version proves
    rejection of the delayed reviewed PUT. Acceptance must become visible as the
    exact reviewed payload in immutable history and live state; collision
''',
        "initial ambiguous settlement documentation",
    ),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    text = text.replace(old, new, 1)

PATH.write_text(text, encoding="utf-8")
