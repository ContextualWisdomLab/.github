# Strix `orchestrator/free` model-boundary doctoring — 2026-09-02

## Exact failing evidence

Protected `main@23df081c36c93da019c89c474351002afb014daa` already hard-pins the central Strix workflow to `contextual-orchestrator/orchestrator/free`, provisions contextual-orchestrator with `CONTEXTUAL_ORCHESTRATOR_POOL: free`, passes all five bootstrap credentials, and sets `STRIX_FALLBACK_MODELS: ""`. The shared Strix gate nevertheless retained direct-provider normalization and direct-OpenAI/OpenRouter/GitHub Models/Vertex fallback machinery. That created a second provider-routing surface beneath a workflow whose accepted owner contract delegates provider selection and failover to contextual-orchestrator.

## Causal owner

The reusable owner is `ContextualWisdomLab/.github/scripts/ci/strix_model_utils.sh` together with `strix_quick_gate.sh`, not downstream repositories. The first repair is placed at model normalization so a concrete provider identifier cannot cross into any later credential/base/fallback branch.

## Test-first repair

Commit `2083a72dccaa1d96ea423a51af537240fde8a210` adds the regression contract before the production change. It requires exactly the two governed `orchestrator/free` spellings to be admitted and representative direct-provider identifiers to fail closed. Commit `10c1ddf822f1e6336b73a9093a56680fea8f4f54` changes the production normalizer accordingly.

No arbitrary rank, weight, score, threshold, retry preference, or provider order replaces the removed routing surface. The accepted identifier is a categorical authority boundary; contextual-orchestrator owns all downstream model choice.

## Credential and privacy correction retained

This repair intentionally does **not** remove `OPENAI_API_KEY` from central workflow bootstrap. All five credential sources may be registered and globally discovered. The `orchestrator/free` candidate-admission owner remains contextual-orchestrator, where OpenAI-derived candidates are excluded while BYTEZ, NVIDIA NIM primary/subaccount, and OpenRouter sources may be considered subject to explicit free/privacy/capability evidence.

Private-target ZDR remains enforced by the central workflow and sidecar. A direct provider route is rejected before it could bypass that boundary.

## Verification status

Fresh hosted exact-head tests are required before merge. Queued, pending, stale, predecessor-head, or synthetic evidence is non-passing. Historical direct-provider fallback code is now unreachable through the accepted model normalizer but remains cleanup debt until a subsequent exact-head change removes it without losing unrelated Strix scanner behavior.

## Retry and severity decision repair

Fresh protected-main evidence showed that the required Strix workflow still allocated two same-model gate retries plus a second outer three-attempt retry loop with fixed backoff values, while the reusable gate classified retryability through hand-authored provider/error regex families. The same path converted Strix severity labels to numeric ranks and used the repository-selected `MEDIUM` cutoff as a merge admission rule. Neither retry allocation nor the severity cutoff had an identified statistical model, authoritative standard, or executable experimental calibration.

The repair therefore does not substitute different retry counts, backoff constants, severity weights, or cutoffs. The central Strix path executes the governed `orchestrator/free` request once; contextual-orchestrator retains provider discovery/failover authority. Any execution that fails to produce authoritative scan evidence fails closed. Any current vulnerability report artifact also fails closed without a repository-authored severity threshold. Severity labels may remain descriptive evidence, but they are not converted into a local admission score.

**2026-09-05 addendum: applied by hand, not by the one-shot driver.** `main` had moved substantially since this doctoring entry and the `2083a72d`/`10c1ddf8` commits were authored: `run_current_target_scan` had grown a full cross-model fallback loop (`FALLBACK_MODELS_RAW`, per-candidate retry, `PR_FINDINGS_DECISION`-gated blocking, a `severity_rank`/`STRIX_MAX_SEVERITY_RANK` threshold check) that the driver script's own `simple_scan` template did not anticipate matching text for. Reconciled by hand: replaced the entire function with the single-governed-request form the driver always intended, confirmed the fallback-model system was already present at this PR's own base commit (not a later regression), and fixed the resulting ripple in six tests across four files that exercised the now-removed `is_transient_same_model_retry_error`/`github_models_rate_limit_should_skip_same_model_retry`/`run_strix_with_transient_retry` orchestration directly — three were rewritten to assert only that each underlying signal classifier (Caido bootstrap timing, ModelBehaviorError, NVIDIA NIM 404) still feeds `has_detected_infrastructure_error`, and three multi-attempt-specific assertions were removed as testing behavior that no longer exists. `scripts/ci/source_fix_strix_no_heuristic_retry_severity.py` and its companion workflow are removed here, matching the driver's own documented one-shot lifecycle, since the repair they existed to apply is now complete.
