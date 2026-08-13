# Trusted-uv transient download retry

## Incident and buyer impact

Every organization pull request runs `coverage-evidence`, which downloads one
pinned `uv` archive from `releases.astral.sh`. A single transient `HTTPError`
on that shared origin failed the gate and produced a false-negative
OpenCode `REQUEST_CHANGES` on otherwise healthy heads
(`ContextualWisdomLab/naruon#1293`, `ContextualWisdomLab/naruon#1300`).

## Decision

Retry only `OSError` (including `HTTPError` / `URLError`) a bounded three
times with linear backoff. Trust-boundary violations (`RuntimeError` for
redirect, host/port, or oversized payload) fail on the first attempt and are
never retried. Each attempt still pins scheme, host, port, size, checksum,
and archive member.

This follows the HTTP retry discipline for transient server/network failures
and does not retry client-side policy failures (Fielding et al., 2022,
§15.5).

## References

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://doi.org/10.17487/RFC9110
