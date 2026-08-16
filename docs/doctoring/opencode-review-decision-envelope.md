# OpenCode review semantic and merge-readiness decision envelope

Status: Proposed operational architecture  
Date: 2026-08-08  
Owner: ContextualWisdomLab central review infrastructure

## Decision summary

OpenCode Review must represent two independent decisions:

1. **Semantic review verdict** — whether exact-head source and connected context contain a substantiated defect.
2. **Merge readiness** — whether exact-head checks, coverage, independent approval, branch protection, and repository policy permit integration.

Infrastructure or policy failure may block integration. It must never be converted into a source finding, severity, path, or line number. A failed coverage collector is evidence that coverage has not been proven, not evidence that the pull-request implementation contains a high-severity defect.

CWE-841 forbids collapsing two required behaviors into one action
(MITRE, 2026). Semantic source judgment and merge-readiness checks are
therefore independent outputs.

This change introduces an offline, deterministic decision-composition module. It does not yet modify the production OpenCode dispatch because other active branches own that large workflow. Production integration requires a later test-first slice after the writer lease clears.

## Problem

The current central review workflow can construct a synthetic `REQUEST_CHANGES` finding when coverage evidence acquisition fails. That behavior combines two different questions:

```text
Does the changed source contain a defect?
                    ≠
May this exact head merge under repository policy?
```

The conflation creates several operational failure modes:

- repeated infrastructure-only reviews that provide no semantic source value;
- fabricated source anchors such as a workflow line that did not cause the product defect;
- inability to distinguish reviewer abstention from a negative code judgment;
- false defect counts in quality evaluation;
- developer confusion about whether to repair code or review infrastructure; and
- stale-head evidence accidentally appearing authoritative after a new commit.

The empirical lifecycle pilot in `benchmarks/opencode_review/pilot_baseline_v1.json` directly observed eight completed OpenCode attempts that produced only infrastructure review output and no source findings. That pilot is not a head-matched precision or recall study, but it establishes that the decision-channel conflation is operationally material.

## Versioned input contract

The decision module accepts one strict JSON object:

```json
{
  "schema_version": "1.0",
  "decision_id": "decision_001",
  "quality_policy_version": "opencode-review-quality-v1",
  "repository": "ContextualWisdomLab/example",
  "pull_request_number": 42,
  "base_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "semantic_review": {
    "status": "complete",
    "reviewed_head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "findings": []
  },
  "merge_evidence": {
    "evidence_head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "coverage_state": "success",
    "independent_approval_state": "success",
    "branch_protection_state": "success",
    "required_checks": []
  }
}
```

### Semantic review input

`semantic_review.status` is one of:

- `complete` — semantic review finished on the exact current head;
- `unavailable` — no trusted semantic review result was available; or
- `failed` — the semantic review process failed before producing a valid result.

A complete review must bind `reviewed_head_sha` to the decision's exact head. An unavailable or failed review must use a null reviewed head and must contain no findings. This prevents a partial or failed process from publishing synthetic source claims.

Each semantic finding must contain:

- stable finding identifier;
- defect class and calibrated severity;
- explicit blocking classification;
- repository-relative changed or connected source path;
- positive source line;
- trigger condition;
- observable impact;
- source-backed root cause;
- minimal fix direction; and
- exact regression target.

### Merge-evidence input

The merge channel carries only policy evidence:

- coverage state;
- independent-approval state;
- branch-protection state; and
- named required or advisory checks.

Every record must bind to the same exact head. A trusted composition root determines which checks are required according to repository policy; the pure decision module does not infer branch protection or fetch GitHub state itself.

The accepted evidence states are:

```text
success
failure
pending
queued
absent
cancelled
skipped
neutral
```

This vocabulary deliberately distinguishes hard negative evidence, latency, and absence. It does not reinterpret GitHub conclusions as product defects.

## Versioned output contract

The output preserves both decisions and both evidence classes:

```json
{
  "schema_version": "1.0",
  "review_verdict": "APPROVE",
  "merge_readiness": "BLOCKED",
  "semantic_status": "complete",
  "findings": [],
  "infrastructure_blockers": [
    {
      "blocker_code": "coverage_not_successful",
      "evidence_name": "coverage",
      "state": "failure",
      "check_name": null
    }
  ],
  "evidence_manifest": {},
  "decision_sha256": "sha256:..."
}
```

Infrastructure blockers have no `path`, `line`, `severity`, `trigger`, `root_cause`, or fix authority. They identify the evidence surface and state only.

## Semantic verdict rules

| Semantic status and findings | `review_verdict` |
|---|---|
| Complete, no finding | `APPROVE` |
| Complete, only non-blocking findings | `COMMENT` |
| Complete, one or more blocking findings | `REQUEST_CHANGES` |
| Unavailable or failed | `ABSTAIN` |

The semantic verdict never reads coverage, checks, approval, or branch-protection state.

`APPROVE` in this envelope means that the semantic channel found no blocking source defect. It is not a formal GitHub approval and must not be submitted as a review by the change author or any non-independent identity.

## Merge-readiness rules

| Evidence | `merge_readiness` |
|---|---|
| Semantic review complete without blocking findings; all required policy evidence successful | `READY` |
| Blocking semantic finding | `BLOCKED` |
| Required evidence `failure`, `cancelled`, `skipped`, or `neutral` | `BLOCKED` |
| Required evidence `pending`, `queued`, or `absent` | `UNKNOWN` |
| Semantic review unavailable or failed, with no hard policy failure | `UNKNOWN` |

Advisory-check failure is recorded in the evidence manifest but does not block unless repository policy marks that check required.

A hard policy failure takes precedence over latency. For example, one failed required check and one pending check produce `BLOCKED`, not `UNKNOWN`.

## Exact-head and evidence-integrity rules

The module rejects:

- a semantic review for another head;
- coverage, approval, protection, or check evidence for another head;
- duplicate case-insensitive finding identifiers;
- duplicate case-insensitive check names;
- unsafe or parent-traversing source paths;
- zero or negative line numbers;
- Boolean values passed as integers;
- unknown fields at every governed schema layer;
- duplicate JSON member names;
- Python's non-standard `NaN`, `Infinity`, and `-Infinity` JSON extensions; and
- incomplete semantic reviews that claim findings or an exact reviewed head.

Canonical strict JSON produces an input SHA-256 receipt. The normalized decision, excluding its own digest, produces a separate decision SHA-256 receipt. JSON and Markdown outputs use temporary sibling files followed by atomic replacement.

## Markdown presentation

The human-readable output has physically separate sections:

```text
Semantic findings

Infrastructure and policy blockers
```

Only semantic findings may render `path:line`. Infrastructure blockers display the evidence name, state, stable blocker code, and optional check name. This presentation rule prevents a later renderer from reintroducing a synthetic source defect even when the underlying JSON remains separated.

## Security and privacy boundary

The decision module:

- runs offline;
- does not execute repository code, model output, commands, or patches;
- does not call GitHub or another network service;
- does not read a secret, cookie, token, environment credential, or model credential;
- accepts only policy-normalized evidence from a trusted caller;
- records no source body or personal data beyond bounded finding text and repository identity; and
- introduces no `COPILOT_GITHUB_TOKEN` use.

Scheduled OpenCode model execution, when used elsewhere, continues to use the existing `NVIDIA_NIM_API_KEY` credential boundary. This pure module neither selects nor invokes a model.

## Production integration boundary

This pull request does not edit `.github/workflows/opencode-review-dispatch.yml`. At the time of implementation, active central branches `#789`, `#812`, `#816`, and `#827` modify that workflow. A competing edit would violate the one-writer lease and could discard exact-head coverage and toolchain repairs.

After those branches integrate or relinquish the file, a separate implementation must begin with a failing production contract that requires the dispatch to:

1. continue bounded semantic review whenever safe exact-head source evidence exists;
2. emit `ABSTAIN` rather than a source finding when semantic review cannot complete;
3. place coverage and check failures only in merge-readiness evidence;
4. pass the versioned decision envelope to publication;
5. publish source comments only from validated semantic findings;
6. expose infrastructure blockers through check summary or a non-source status surface;
7. preserve reviewer identity and credential chains; and
8. keep merge, auto-merge, branch update, and release authority separately controlled.

No predecessor-head result from this pure module authorizes that later production integration.

## Verification

The exact-head quality workflow runs on Python 3.14 with immutable action pins, read-only repository permission, persisted checkout credentials disabled, and hash-verified test dependencies. It requires:

- behavior and adversarial schema tests;
- exact-head checkout verification;
- production statement coverage 100%;
- production branch coverage 100%;
- public production callable docstrings 100%;
- `compileall`; and
- a clean Git worktree.

Regression cases cover the exact operational failure: coverage failure with a complete defect-free semantic review yields `APPROVE` plus `BLOCKED`, with no source finding.

## Monitoring after integration

When the envelope reaches the production dispatch, monitor at least:

- semantic completion, failure, and abstention rates;
- infrastructure-only blocker rate;
- source findings per completed semantic review;
- current-head duplicate publication rate;
- stale-head evidence rejection count;
- blocked versus unknown readiness rates;
- time to first useful semantic comment;
- developer dismissal and resolution rates; and
- any occurrence of a path or line in an infrastructure blocker.

The last metric must remain zero.

## Rollback

The pure decision module can be removed from a caller without changing reviewer credentials, model selection, or GitHub branch protection. Rollback must not restore the old synthetic source-finding path. If the envelope cannot be consumed safely, the caller should fail closed with:

- semantic verdict `ABSTAIN`; and
- merge readiness `UNKNOWN` or `BLOCKED` according to independently available policy evidence.

## Limitations

- The module does not discover which GitHub checks are required; a trusted policy collector must supply that classification.
- It does not prove that a formal independent approval is valid; it validates only normalized approval state and exact-head identity supplied by a trusted caller.
- It does not itself collect coverage or branch-protection evidence.
- It does not calibrate semantic severity or verify model findings; detector-verifier orchestration and expert-gold evaluation remain separate work.
- A `READY` output is a deterministic policy composition result, not authority to bypass GitHub rulesets or merge administratively.

## References

MITRE. (2026). *CWE-841: Improper enforcement of behavioral workflow*.
https://cwe.mitre.org/data/definitions/841.html

Booth, H., Souppaya, M., Vassilev, A., Ogata, M., Stanley, M., Scarfone, K., & Dodson, D. (2024). *Secure software development practices for generative AI and dual-use foundation models: An SSDF community profile* (NIST Special Publication 800-218A). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218A

GitHub. (n.d.). *About protected branches*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Approving a pull request with required reviews*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews

GitHub. (n.d.). *Status checks*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/pull-requests/committing-changes-to-your-project/troubleshooting-commits/status-checks

GitHub. (n.d.). *Troubleshooting required status checks*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/troubleshooting-required-status-checks

SLSA Community. (2025). *SLSA specification, version 1.2*. https://slsa.dev/spec/v1.2/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development Framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Sun, T., Xu, J., Li, Y., Yan, Z., Zhang, G., Xie, L., Geng, L., Wang, Z., Chen, Y., Lin, Q., Duan, W., & Sui, K. (2025). BitsAI-CR: Automated code review via LLM in practice. In *Proceedings of the 33rd ACM International Conference on the Foundations of Software Engineering*. https://doi.org/10.1145/3696630.3728552
