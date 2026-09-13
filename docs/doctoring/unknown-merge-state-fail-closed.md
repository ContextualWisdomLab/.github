# Unknown merge state does not authorize change-request automation

검토 기준일: **2026-09-07**

## Problem

GitHub can temporarily report an unresolved mergeability state after a push.
The REST fallback normalizes that condition to an empty value. Treating the
empty value as clean allows automatic change-request handling without positive
mergeability evidence.

## Decision

The shared gate accepts only `CLEAN` and `HAS_HOOKS`. Missing, empty, or
unknown values return no clean review body, so neither autofix nor RCA dispatch
is authorized. Known dirty states retain the same behavior.

## Verification contract

`test_change_request_gates_fail_closed_on_unknown_merge_state` covers empty,
unknown, and absent values across the normalized body, autofix, and RCA entry
points. Hosted exact-head checks remain mandatory.

## Status

**Proposed** in ContextualWisdomLab/.github#1492. Protected `main` remains the
release authority.

## Reference

GitHub. (n.d.). *REST API endpoints for pull requests*. GitHub Docs. Retrieved
September 7, 2026, from
https://docs.github.com/en/rest/pulls/pulls
