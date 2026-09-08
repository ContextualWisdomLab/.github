# CodeQL wake credential fallback boundary

## Symptom

The trusted handler could finish exact PR, head, base, run, job, receipt, gate,
SARIF, and handler-source validation but still fail to wake the required run.
The wake job selected the first nonempty credential in the workflow expression;
if that credential returned HTTP 403 for the target repository, a later valid
credential was never attempted.

## Root cause

Credential presence was treated as evidence of repository-scoped Actions
authority. That assumption is false for central workflows serving multiple
repositories. It also made the fallback decision before the only operation
that can establish whether the credential is admitted.

## Reproduction and repair evidence

- Owner: `ContextualWisdomLab/.github` PR #1902.
- Successor delta source: PR #2040, retained in the canonical run-wide
  settlement rather than copying its earlier per-matrix wake structure.
- RED: commit `da1cbe544757fab64d64bdd05a489f2e25648aa1` records two POST attempts only after the primary is
  made to return HTTP 403; the predecessor emitted one failed POST.
- GREEN: commit `8cb0a283dbf4c00e4c50111dcece418108916433` tries the bounded credential chain and succeeds on
  the second credential against the identical exact-run endpoint.
- Contract evidence: the focused fallback fixture and all 63 dispatch workflow
  contracts pass locally. Hosted exact-head evidence is still required.

## Invariants and failure scenes

The wake remains owned by one non-matrix settlement job. Every credential is
subject to the same exact endpoint and the same revalidated PR, head, base,
workflow path, run, job map, receipt, SARIF, and producer provenance. If all
eligible credentials are absent or denied, the handler fails closed. A bare
HTTP 403 never counts as a concurrent wake; only exact newer attempts for every
required language can prove that race. The scan job's repository-scoped App
token remains local to that matrix job and is not serialized or transferred.

For an operator, the actionable distinction is now explicit: a denied primary
credential advances to the next bounded credential, while total exhaustion
leaves the required Check red with no broadened authority. For a reviewer, the
fixture proves both POSTs target the same run and mode, so fallback cannot be
used to rerun a different workflow or commit.
