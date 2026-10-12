# LiteLLM credential-exfiltration and SSRF lock repair

## Decision status

Proposed on `ContextualWisdomLab/.github#2040`. This record does not authorize
merge or release; fresh exact-head hosted Checks and qualifying independent
review remain mandatory.

## Problem and exact evidence

Python Security run `36779036029`, job `110104335583`, audited the current
Strix hash lock and found `litellm==1.94.1` affected by CVE-2026-84377. The
published advisory states that an authenticated proxy user can override nested
routing or credential parameters, redirect an outbound provider request, and
exfiltrate operator provider credentials or reach internal services. The audit
lists 1.94.3 as the first patched release within the selected 1.94 line.

## Constraints and alternatives

- Suppressing the advisory or excluding the lock would hide a real credential
  and SSRF boundary failure and was rejected.
- Depending on the transitive LiteLLM range would leave the selected artifact
  resolver-dependent and was rejected.
- Jumping to a newer feature line would widen compatibility risk without a
  demonstrated need and was rejected.

## Selected repair

Pin `litellm==1.94.3` in `requirements-strix-ci.txt`, regenerate
`requirements-strix-ci-hashes.txt` with the documented `uv pip compile`
command, and bind source/lock parity in an executable test. This keeps Strix as
the consuming boundary and changes no audit threshold, provider route, model,
or paid fallback.

## Verification and residual risk

The source/lock contract passes six tests. `pip-audit==2.10.1` against the
regenerated hash lock with `--disable-pip --no-deps` reports no known
vulnerabilities. This is local evidence only; a fresh hosted Python Security
run must repeat the audit on the exact published head. Upstream behavior and
future advisory data can change, so the immutable lock and hard gate remain.

## Concrete failure scene

Without this repair, a user holding a valid LiteLLM proxy key could submit a
nested provider base URL or credential override. The proxy could then send its
stored upstream provider secret to the caller-controlled endpoint or connect
to an internal service. After this repair, the affected version is absent from
the installed Strix lock; application authorization and outbound controls are
still required as independent defenses.

## APA 7th references

CVE Program. (2026). *CVE-2026-84377*. https://www.cve.org/CVERecord?id=CVE-2026-84377

Python Packaging Authority. (2026). *LiteLLM 1.94.3*. Python Package Index.
https://pypi.org/project/litellm/1.94.3/

Trail of Bits. (2026). *pip-audit 2.10.1*. GitHub.
https://github.com/pypa/pip-audit/releases/tag/v2.10.1
