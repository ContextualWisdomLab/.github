# CodeQL GHAS analysis credential routing — 2026-09-19

## Symptom

OriginWeave PR #229 dispatch run `35303205858` reached the central scan jobs after `validate-dispatch` succeeded. The `actions` job `105600898203`, `javascript-typescript` job `105600898234`, and Python job `105600898461` all completed CodeQL analysis and the Medium+ SARIF gate successfully, then failed specifically at `Verify GHAS base/head CodeQL configuration identity`.

The identity step failed in about one second in all three shards. That is materially different from the bounded identity-continuity wait: `codeql_ghas_configuration_identity.py` polls up to 30 times with a 20-second interval when a legitimate base identity is merely not present on the exact head yet. An immediate failure therefore indicates that the analyses API could not be read, rather than that the intended continuity poll exhausted its budget.

This supersedes the earlier runner-queue diagnosis and the interim observation that the Python shard was still queued.

## Root cause

The scan job exchanges an OpenCode GitHub App token for target repository **content reads** and uses it successfully for live pull-request metadata and head materialization. The GHAS identity step reused this precedence expression:

```text
steps.target_app_token.outputs.token || PR_REVIEW_MERGE_TOKEN || OPENCODE_APPROVE_TOKEN || github.token
```

GitHub expression fallback is based on token presence, not API capability. A non-empty content-capable target token therefore masked every later credential even when it could not read the target repository's `code-scanning/analyses` endpoint. The job-level `security-events: read` permission applies to the workflow repository's `github.token`; it does not by itself grant that token cross-repository GHAS access.

This is a credential-capability selection defect, not a CodeQL analysis defect: all three failed shards had successful `Perform CodeQL Analysis`, successful Medium+ SARIF gates, and preserved SARIF evidence before the identity-read failure.

## Ownership and stacking

The canonical repair is central because cross-repository CodeQL evidence identity is owned by `ContextualWisdomLab/.github`. It is intentionally stacked on PR #2271 (`fix/codeql-dispatch-repository-identity`) because #2271 already changes `codeql-scan-dispatch.yml`; the successor preserves that admission repair instead of opening a conflicting parallel writer against `main`.

OriginWeave must not copy this workflow or synthesize a success status.

## RED

Commit `8e93ae226b52a4d0456137ae36191241d5c58fe7` adds an executable shell contract that requires:

- a content-only first credential to fall through when the target analyses endpoint rejects it;
- the next credential with proven target CodeQL analysis-read access to be selected;
- all configured candidates failing to read the endpoint to remain a hard failure;
- the GHAS identity step to consume only the credential that passed the capability probe, rather than repeating the presence-only precedence chain.

The test executes the workflow's real selector `run:` block with a fake `gh` boundary; it does not duplicate the production selection algorithm in Python.

## Repair

Commit `4c4fff284e6bb58fe738389a647e2a7d1031dd54` adds one preflight step immediately after the Medium+ SARIF gate. It probes the exact target repository's CodeQL analyses endpoint with the already-configured credentials in existing precedence order:

1. exchanged target app token;
2. `PR_REVIEW_MERGE_TOKEN`;
3. `OPENCODE_APPROVE_TOKEN`;
4. workflow token.

The first credential that **actually succeeds** against `repos/<target>/code-scanning/analyses` is masked and passed as a step output to the identity verifier. If no configured credential can read that endpoint, the job fails closed with an explicit capability diagnostic. No permission is broadened, no secret is printed, and the GHAS identity proof itself is unchanged.

Compared with #2271 exact `2b849c874122961e025c29f7fa0bb697863c3d68`, the repair generation is ordinary-forward and changes only the CodeQL dispatch workflow, focused credential-routing contract, and this doctoring record.

## Review finding and correction

CodeRabbit correctly found that the failure-closed contract initially inspected `result.stderr` even though the selector emits the `::error::no configured credential can read target CodeQL analyses...` diagnostic with plain `echo`, which `subprocess.run(..., capture_output=True)` captures on stdout. Commit `a900ec17f1e4a7db384e3052c23d3cf7440f0651` changes only that assertion to inspect `result.stdout`; the review thread was answered and resolved after verifying the production selector.

A focused local execution of the exact selector semantics confirms both branches: a rejected `content-token` falls through to `security-token`, writes `token=security-token` / `source=pr-review-merge-token`, and returns zero; when every configured credential is rejected, all four candidates are attempted in order, the failure diagnostic appears on stdout, and the selector exits non-zero. This is local contract evidence only and does not replace exact-head hosted checks or the required end-to-end dispatch.

## Alternatives rejected

Using the first non-empty token remained rejected because that is the defect reproduced by the live run.

Skipping GHAS identity verification when the analyses API is unreadable was rejected because dispatch SARIF cannot impersonate GitHub Default setup configuration identity. The existing #2133 invariant remains mandatory.

Granting broader permissions blindly to the exchanged token was not assumed. The exchange endpoint currently returns an installation token without a workflow-side permission request contract. Capability is therefore proven at the target endpoint rather than inferred from the token's provenance or label.

Retrying the failed OriginWeave head before the central owner repair is accepted was rejected: it would repeat the same deterministic credential selection and create noise rather than new evidence.

## Acceptance

Before merge, the stacked successor needs:

- focused RED→GREEN contract execution;
- existing CodeQL dispatch workflow/shell contracts;
- exact-head hosted security/quality checks;
- independent review;
- an end-to-end dispatch proving that the selected credential can read target GHAS analyses and that the existing base/head identity proof reaches its normal terminal verdict.

Only after the central repair is accepted should OriginWeave #229 receive a normal exact-head CodeQL rerun. No predecessor run, SARIF artifact, review, or status is transferable to a changed successor head.
