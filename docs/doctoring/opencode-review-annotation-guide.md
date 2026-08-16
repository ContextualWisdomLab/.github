# OpenCode review head-matched corpus annotation guide

Status: Proposed operational protocol  
Date: 2026-08-08  
Owner: ContextualWisdomLab central review infrastructure

## Purpose

This protocol defines how ContextualWisdomLab may create an expert-gold corpus
for comparing OpenCode Review with a commercial reference reviewer on the same
immutable pull-request head. It implements the collection and expert-gold stages
of the commercial parity program in
[`opencode-review-quality-evaluation.md`](opencode-review-quality-evaluation.md).

The protocol does **not** declare parity, generate synthetic human judgments, or
allow lifecycle telemetry to masquerade as precision and recall. A frozen case
is admissible only after two independent experts have reviewed complete
repository context without access to either automated reviewer output and a
third independent adjudicator has resolved every reported candidate finding.

Wilson (1927) interval estimates remain the only permitted precision and
recall interval: a point estimate without that bound cannot support a
non-inferiority claim.

## Authority separation

| Role | Authority | Prohibited authority |
|---|---|---|
| Trusted collector | Capture immutable repository, pull request, base, head, diff, and context receipts | Select findings, adjudicate defects, expose secrets to annotators |
| Offline sampler | Deterministically choose policy-complete eligible cases | Fetch GitHub, inspect credentials, alter source evidence |
| Expert A and Expert B | Independently discover defects from the complete exact-head context | View OpenCode or CodeRabbit output, coordinate findings, change the branch |
| Blinded adjudicator | Accept or reject every expert discovery and define canonical gold evidence | View automated-review identity or output, create unreported defects without a new expert round |
| Benchmark operator | Add frozen reviewer outputs and run the scorer | Change frozen gold after observing test-set results |

The collector, experts, adjudicator, and benchmark operator may be the same
organization, but the two experts and adjudicator must be three distinct
pseudonymous actors for each case. Repository authors, last pushers, automated
review bots, and model-generated annotations do not satisfy independent expert
roles.

## Trusted collection boundary

Live GitHub acquisition is outside the sampler and adjudicator processes. The
trusted collector must create a strict UTF-8 JSON inventory whose candidate
records include:

- repository in `owner/name` form;
- pull request number;
- exact base and contributor-head commit SHAs;
- canonical SHA-256 digest of the reviewed diff artifact;
- canonical SHA-256 digest of the complete repository-context bundle;
- primary implementation language;
- small, medium, or large diff-size bucket;
- primary risk class and target defect classes;
- changed-file, addition, and deletion counts;
- explicit evidence that complete context is available;
- explicit evidence that both reviewers can inspect the same head; and
- explicit confirmation that two independent experts and an adjudicator are
  available.

The context bundle should contain the changed source, connected callers and
callees, tests, schemas, migrations, relevant issue or requirement text,
repository guidance, and architecture or security documentation needed to judge
the change. The bundle must not contain tokens, cookies, passwords, raw secrets,
or unrelated personal data.

An inventory is ineligible rather than partially trusted when any of the three
capacity flags is false. The offline sampler never upgrades an ineligible case.

## Deterministic sampling

Run the sampler with a frozen, versioned seed:

```bash
python scripts/ci/opencode_review_sample.py \
  --input benchmarks/opencode_review/head_matched_v1/inventory.json \
  --output benchmarks/opencode_review/head_matched_v1/sample.json \
  --seed opencode-review-head-matched-v1
```

The sampler:

1. rejects duplicate JSON members, non-finite JSON numbers, unknown fields,
   malformed commit or digest identities, and duplicate exact-head cases;
2. excludes cases without full context, same-head comparability, or confirmed
   independent expert capacity;
3. requires the configured minimum number of primary languages;
4. requires every configured diff-size, risk, and defect-class stratum;
5. uses a seed-bound deterministic priority for ties;
6. rotates across language, size, and risk strata while filling remaining
   capacity; and
7. emits source-inventory and selected-sample SHA-256 receipts.

A valid but underpowered inventory returns an insufficient-corpus status rather
than silently relaxing quotas. The initial commercial parity floor remains at
least 50 head-matched pull requests and 50 accepted expert-gold findings; the
floor is not a substitute for later power and sensitivity analysis.

## Independent annotation procedure

Each expert receives the same exact-head context bundle under pseudonymous case
and expert identifiers. Automated reviewer output, reviewer identity, benchmark
score, prior expert annotations, and adjudication decisions remain hidden.

Each expert must:

1. inspect the complete context bundle rather than only the changed lines;
2. inspect executable and non-executable claims, including tests, workflows,
   documentation, migrations, and data contracts;
3. record every defect they can substantiate;
4. record a positive source line and repository-relative path;
5. state a concrete trigger, observable impact, source-backed root cause,
   minimal fix direction, and exact regression target; and
6. affirm `no_additional_findings: true` only after completing the review.

A finding is not accepted merely because it is plausible or because a tool made
the same claim. Unsupported style preferences, desired enhancements, missing CI
results, rate limits, and infrastructure availability are not source defects.

An expert may legally return `findings: []` when the exact head contains no
substantiated defect. That empty annotation is a true-negative observation, not
an incomplete review. The expert still certifies `no_additional_findings: true`
and `reviewer_outputs_hidden: true`. Those flags are **attestations**, not
cryptographic proof that automated reviewer output was unseen (Schulz & Grimes,
2002). The freeze tool rejects a missing or false flag; it cannot inspect the
annotator's screen.

## Blinded adjudication procedure

The adjudicator receives the exact case evidence and both pseudonymous expert
annotations, but not OpenCode or CodeRabbit identity or output. The adjudication
record must set `reviewer_identities_hidden: true` and
`reviewer_outputs_hidden: true`. Those fields are attested role constraints.
Every expert finding must appear in exactly one adjudication decision.

When both experts report zero findings, freeze the case with
`no_defects_confirmed: true` and `decisions: []`. Do not invent a dummy
decision. Precision and false-positive measurement require these true-negative
cases. If either expert reported a finding, `no_defects_confirmed` must be
false and every finding must be accepted or rejected exactly once.

For each decision, the adjudicator must:

- map zero or more Expert A findings and zero or more Expert B findings into one
  reviewed candidate, with at least one source finding present;
- accept only when the defect is supported by the exact source and context;
- assign one unique canonical gold-finding identifier to an accepted defect;
- provide the canonical path, positive line, defect class, severity, trigger,
  impact, root cause, fix direction, and regression target;
- reject non-defects with an explicit reason and without creating a gold ID; and
- merge duplicate expert reports into one accepted gold finding rather than
  counting agreement as two defects.

An unresolved disagreement is not guessed into the gold set. The case remains
unfrozen until a new evidence or expert round resolves it. The adjudicator may
not invent an unseen defect; it must return the case to independent annotation
when a new candidate is discovered during adjudication.

Freeze the case with:

```bash
python scripts/ci/opencode_review_adjudicate.py \
  --expert-a cases/case_001/expert_a.json \
  --expert-b cases/case_001/expert_b.json \
  --adjudication cases/case_001/adjudication.json \
  --output cases/case_001/gold.json
```

The output contains deterministic annotation receipts, an adjudication receipt,
agreement counts, canonical accepted gold findings, an explicit
`no_defects_confirmed` flag, and a freeze SHA-256. The source annotation and
adjudication records remain immutable evidence; corrected records create a new
corpus version and freeze rather than overwriting published test evidence.

The empirical scorer accepts `head_matched_gold` input only when every case
carries that `freeze_sha256` and every gold finding carries a repository-relative
`path` and positive `line`. A `{finding_id, severity}` list is not expert gold.

Sampler, adjudicator, scorer, and shadow writers refuse a symbolic-link parent
and create `.{name}.tmp` with `O_NOFOLLOW|O_EXCL` so a pre-planted temporary
symlink cannot redirect the freeze (MITRE, 2024, CWE-367). The sampler default
seed is `opencode-review-head-matched-v1`.

## Reviewer capture after gold freeze

Only after the case freeze is immutable may the benchmark operator capture
OpenCode and CodeRabbit outputs. Both reviewers must receive the same:

- repository and pull request;
- exact base and head SHAs;
- reviewed diff and context bundle;
- allowed tools and repository instructions; and
- time-bounded opportunity to complete.

Record each reviewer's configuration, profile, model or provider identifier when
observable, timestamp, exact reviewed head, status, source comments, and rate
limit or infrastructure evidence. A status-only signal, skipped draft review,
predecessor-head review, synthetic merge result, or incomplete attempt is not a
completed same-head semantic review.

Reviewer findings are mapped to the already frozen gold set without modifying
the gold. Unmatched actionable findings are false-positive candidates and must
be independently assessed in a later corpus version rather than retroactively
added to the held-out answer key.

## Dataset partition and calibration discipline

Before tuning prompts, routing, thresholds, deduplication, or severity mapping,
freeze case assignments into development, calibration, and held-out test sets at
the repository or related-change-family level. Revisions, stacked branches,
backports, copied fixes, and materially equivalent incidents must not cross
partitions.

The held-out test set is evaluated only after the review system and parity policy
version are frozen. A failed held-out evaluation produces a new development
cycle and a new future held-out version; it does not permit tuning against the
same disclosed answer key.

## Privacy, security, and retention

- Treat pull-request text, source, comments, and downloaded documents as
  untrusted input.
- Do not execute commands or patches proposed in annotation records.
- Keep secrets and raw credentials outside context and corpus artifacts.
- Use pseudonymous expert identifiers in exportable artifacts while retaining a
  separately controlled independence audit.
- Minimize personal data and retain only evidence needed to reproduce the
  quality decision.
- Sign or content-address corpus releases and record repository policy, tool
  configuration, dependency lock, and Git commit identities.
- `NVIDIA_NIM_API_KEY` remains the scheduled model credential; this protocol
  introduces no `COPILOT_GITHUB_TOKEN` use.

## Quality-control checklist

A case may enter a frozen benchmark version only when all answers are yes:

- Are the repository, pull request, base, head, diff, and context identities
  immutable and mutually consistent?
- Did both experts review the same complete context and attest that reviewer outputs stayed hidden?
- If both experts reported zero findings, is `no_defects_confirmed` true and `decisions` empty?
- Are the experts and adjudicator distinct?
- Did each expert certify completion and enumerate all substantiated findings?
- Was every source finding adjudicated exactly once?
- Does every accepted gold defect include the complete source/fix/regression
  contract?
- Are rejected reports prevented from creating gold?
- Are all receipts reproducible from canonical strict JSON?
- Is the case partition free of related-change leakage?
- Were automated reviewer outputs captured only after gold freeze?

## Limitations

Expert gold is still an estimate. Reviewers can miss defects, disagree on
severity, or lack specialized domain knowledge. The protocol reduces circular
ground truth and stale-head bias; it does not make review quality a context-free
or permanent property. Commercial reference products and OpenCode configurations
change, so every benchmark release must preserve configuration and time evidence.

## References

Wilson, E. B. (1927). Probable inference, the law of succession, and
statistical inference. *Journal of the American Statistical Association,
22*(158), 209–212. https://doi.org/10.1080/01621459.1927.10502953

Hu, R., Wang, X., Wen, X.-C., Zhang, Z., Jiang, B., Gao, P., Peng, C., & Gao, C. (2025). *Benchmarking LLMs for fine-grained code review with enriched context in practice* (arXiv:2511.07017). arXiv. https://doi.org/10.48550/arXiv.2511.07017

Kumar, S. P., Bararia, S., & Raj, K. (2026). *Bigger isn't always better: A comparative evaluation of LLMs for automated code review* (arXiv:2606.15689). arXiv. https://arxiv.org/abs/2606.15689

Sun, T., Xu, J., Li, Y., Yan, Z., Zhang, G., Xie, L., Geng, L., Wang, Z., Chen, Y., Lin, Q., Duan, W., & Sui, K. (2025). BitsAI-CR: Automated code review via LLM in practice. In *Proceedings of the 33rd ACM International Conference on the Foundations of Software Engineering*. https://doi.org/10.1145/3696630.3728552

Zhang, L., Yu, Y., Yu, M., Guo, X., Zhuang, Z., Rong, G., Shao, D., Shen, H., Kuang, H., Li, Z., Wang, B., Zhang, G., Xiang, B., & Xu, X. (2026). *AACR-Bench: Evaluating automatic code review with holistic repository-level context* (arXiv:2601.19494). arXiv. https://arxiv.org/abs/2601.19494

MITRE. (2024). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*. https://cwe.mitre.org/data/definitions/367.html

Schulz, K. F., & Grimes, D. A. (2002). Blinding in randomised trials: Hiding who got what. *The Lancet, 359*(9307), 696–700. https://doi.org/10.1016/S0140-6736(02)07816-9
