# OpenCode shadow review orchestration

Status: Active pull-request implementation
Date: 2026-08-11
Owner: ContextualWisdomLab central review infrastructure

## Purpose and maturity

This implementation provides a production-independent detector–verifier pool for exact-head OpenCode review experiments. It allocates a bounded review topology from trusted pull-request metadata, runs detectors before independent verifiers, and emits validated `shadow_findings` for evaluation.

The capability is `active_pr`, not `implemented_on_protected_main`. It cannot publish a GitHub comment, review, check, approval, merge, branch update, or release. CWE-345 forbids treating unverified or evaluation-only output as authenticity evidence (MITRE, 2026). Shadow findings therefore cannot authorize merge. A later integration must preserve that authority separation and earn protected-main operational evidence before the capability is described as deployed.

## Components

| Component | Responsibility |
|---|---|
| `opencode_review_shadow_primitives.py` | Strict JSON parsing, schema validation, canonical serialization, digests, safe paths, and atomic output writes. |
| `opencode_review_shadow.py` | Deterministic routing plans and bounded OpenCode attempt execution. |
| `opencode_review_verify.py` | Exact-head receipt validation, independent verification, semantic deduplication, and shadow-only reporting. |
| `run_opencode_semantic_review_pool.sh` | Thin plan-only command wrapper with no GitHub mutation path. |

The modules are deliberately standalone. They do not import or modify the production dispatch workflow, reviewer identities, merge policy, or release controls.

## Deterministic routing

The plan command accepts one strict request document containing the repository identity, pull-request number, `base_sha`, `head_sha`, changed-file metadata, bounded model pools, and the detector budget. Unknown fields, malformed SHA values, duplicate JSON keys, non-finite numbers, unsafe paths, invalid model entries, or an impossible role budget fail closed.

Routing classifies the change into small, medium, or large diff buckets and low, standard, high, or critical risk. The resulting roles are selected only when material:

- a general semantic detector for ordinary source changes;
- security, workflow, data-model, numerical, experience, or documentation specialists for corresponding evidence;
- an independent verifier for every executable topology; and
- bounded recursive verification for high-risk disagreement when the supplied budget permits it.

The canonical plan contains no credential. Its `plan_sha256` binds the complete normalized request and selected attempts, so a caller can prove which exact plan it executed.

## Execution boundary

The run command validates the plan, executable, evidence files, worktree, and output location before starting a child process. Each attempt uses a fixed argument vector rather than a shell:

```text
opencode run --agent <role> --model <model> --variant <variant> --format json <prompt>
```

Detectors run before verifiers. A verifier receives the successful detector evidence selected by the plan; it is marked `dependency_failed` when its detector dependency did not produce trusted evidence. Timeouts and non-zero exits are recorded per attempt, allowing one failure to remain isolated without converting infrastructure failure into a semantic source finding.

The execution environment is intentionally minimal. `NVIDIA_NIM_API_KEY` is read by the trusted parent and mapped only to the child process as `NVIDIA_API_KEY`. It is never placed in the plan or process arguments. Exact secret echoes in child stdout or stderr are replaced with `[REDACTED_NVIDIA_API_KEY]` before evidence is persisted or hashed.

The output directory must be absent or an empty private directory. Symlinks, non-directories, group/world-writable directories, and non-empty directories are rejected. A newly created output directory uses mode `0700`. Evidence is written atomically through a temporary sibling file and replacement.

## Evidence and verification

The verifier accepts strict execution and source-receipt bundles bound to one repository, pull request, base SHA, and head SHA. It rejects stale heads, failed attempts presented as findings, unsupported source paths or lines, infrastructure-only claims rendered as source defects, detector self-verification, insufficient verifier count, and required model-diversity violations.

Candidate findings must have trusted source-line evidence and a successful independent verifier receipt. Normalization and semantic deduplication are deterministic. The report contains:

```json
{
  "publication_enabled": false,
  "published_findings": [],
  "shadow_findings": []
}
```

`shadow_findings` are evaluation evidence only. They are not formal GitHub reviews, qualifying human approvals, merge decisions, or release authorization.

## Operator procedure

Generate a content-addressed plan:

```bash
scripts/ci/run_opencode_semantic_review_pool.sh plan \
  --request request.json \
  --output plan.json
```

Run the validated attempts from a trusted worktree:

```bash
python3 scripts/ci/opencode_review_shadow.py run \
  --plan plan.json \
  --worktree /trusted/exact-head-worktree \
  --evidence-dir /trusted/evidence \
  --output-dir /private/empty/output \
  --opencode /trusted/bin/opencode
```

Verify the exact-head attempt bundle without publishing:

```bash
python3 scripts/ci/opencode_review_verify.py \
  --request verification-request.json \
  --output shadow-report.json
```

The trusted caller must independently resolve the live base tip. A pull-request event's base snapshot is historical evidence and must not be substituted for the current protected base.

## Verification contract

The permanent tests cover routing determinism, strict schemas, adversarial JSON, unsafe paths, immutable digests, budget exhaustion, model diversity, partial failures, timeouts, dependency ordering, credential minimization and redaction, executable/worktree/output boundaries, source receipt authority, deduplication, and publication denial.

Acceptance for the owned production modules requires:

- all focused behavioral and adversarial tests passing;
- exactly 100% production statement and branch coverage;
- exactly 100% production callable docstring coverage;
- successful Python compilation and Bash syntax checks; and
- a clean exact-head diff and hosted Python 3.14 workflow result.

Local evidence does not replace hosted exact-head evidence. A successful pull-request workflow does not establish protected-main operational acceptance, reviewer independence, or commercial review parity.

## Recovery and rollback

Malformed input, a changed executable or evidence digest, an unsafe worktree/output boundary, missing credentials, timeout, model failure, stale head, or verification-policy failure stops only the affected plan or attempt and produces no published finding. Operators should preserve the immutable inputs and attempt receipts, correct the first failing boundary, and generate a new content-addressed plan rather than editing evidence in place.

Rollback is removal of this standalone pool and its caller integration. Because this slice has no GitHub publication or merge authority and no persistent database, rollback does not require data migration. Evaluation artifacts should be retained only under the repository's scoped evidence-retention policy.

## References

MITRE. (2026). *CWE-345: Insufficient verification of data authenticity*.
https://cwe.mitre.org/data/definitions/345.html
