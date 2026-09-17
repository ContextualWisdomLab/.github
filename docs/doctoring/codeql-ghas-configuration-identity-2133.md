# GHAS CodeQL configuration identity continuity (#2133)

## Symptom

Wardnet PR `ContextualWisdomLab/wardnet#129` at exact head
`2cedf7098723cd12f59125e72f4354226165a112` completed its central current-head
CodeQL dispatch successfully while the GitHub Advanced Security CodeQL
comparison check was still terminal **neutral** with:

> Code scanning cannot determine the alerts introduced by this pull request,
> because 1 configuration present on `refs/heads/main` was not found.
> Missing: `Default setup /language:rust`.

Dispatch completion alone is therefore incomplete differential-analysis
evidence.

## Root cause

Protected bases that use GitHub CodeQL Default setup publish identities of the
form:

```text
(analysis_key=dynamic/github-code-scanning/codeql:analyze, category=/language:<lang>)
```

GHAS pairs each such base identity with the same tuple on the PR head. Default
setup often finishes a fast language (for example `actions`) minutes before a
slower one (for example `rust`). The GHAS comparison can settle after the first
language lands and report `configuration not found` for every base language not
yet present on the head — even though the slower analysis later appears under
the correct identity on the same exact SHA.

The central `#2106` handler stack correctly keeps `github/codeql-action/analyze`
at `upload: false` while Default setup owns code-scanning uploads (Default setup
blocks advanced CodeQL API uploads). Advanced uploads also use a different
`analysis_key`, so they cannot satisfy a Default setup base identity. The
central producer therefore cannot "impersonate" Default setup; it must prove
continuity of the identities Default setup already publishes.

## Repair

`scripts/ci/codeql_ghas_configuration_identity.py` is the executable pairing
contract:

- positive: exact base/head SHAs sharing Default setup `/language:<lang>` pair;
- negative: base Default setup rust with only actions on the head fails closed;
- advanced-setup analysis keys are not interchangeable with Default setup.

`.github/workflows/codeql-scan-dispatch.yml` fetches that script beside the
SARIF gate and, after the Medium+ gate, waits (bounded poll) until the scanned
language's base identity is present on the exact head before publishing the
`codeql-dispatch/<language>` status. Least privilege stays `security-events:
read` for this verification; no leaf Default setup disablement and no synthetic
GHAS status.

## Ownership boundary

Cross-repository CodeQL evidence identity remains owned by the organization
central producer/handler/settlement layer (`codeql-pr.yml` →
`codeql-scan-dispatch.yml`, coordinated with `#2106` / `#2040` / `#1929`). Do
not copy CodeQL workflows into consumer repositories or reinterpret a transient
neutral GHAS comparison as GREEN.
