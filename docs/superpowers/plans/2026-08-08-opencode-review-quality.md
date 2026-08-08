# OpenCode Review quality implementation plan

> Execute in protected, exact-head slices. Do not edit the central dispatch concurrently with another active writer.

**Goal:** Establish a defensible empirical quality gate, then use it to evolve OpenCode Review toward commercial non-inferiority with CodeRabbit.

**Architecture:** A deterministic benchmark and scorer measure reviewer operations and expert-gold defect quality. The production reviewer is subsequently split into semantic review and merge-readiness channels, with detector, verifier, source-contract, deduplication, and publication stages. Model compute is allocated by PR risk and disagreement rather than a fixed topology.

**Technology:** Python 3.14 standard library, pytest, coverage.py, GitHub Actions, OpenCode, NVIDIA NIM, GitHub review APIs.

---

## Task 1: Record a fail-first empirical contract

**Files:**
- Create: `benchmarks/opencode_review/pilot_baseline_v1.json`
- Create: `tests/test_opencode_review_quality_score.py`
- Create: `.github/workflows/opencode-review-quality-ci.yml`

**Steps:**
1. Encode only directly observed review lifecycle records.
2. Mark every case as not head-matched and include explicit limitations.
3. Write a test that imports the not-yet-created scorer and asserts `INSUFFICIENT_EVIDENCE` plus the pilot operational metrics.
4. Open a Draft PR at the exact head.
5. Run the pinned workflow and capture the expected missing-scorer failure.
6. Do not count a predecessor-head failure as the RED receipt.

**Exit evidence:** exact-head workflow failure at the missing production scorer.

## Task 2: Implement the scorer test-first

**Files:**
- Create: `scripts/ci/opencode_review_quality_score.py`
- Expand: `tests/test_opencode_review_quality_score.py`

**Steps:**
1. Validate schema version, evaluation mode, case identifiers, repository coordinates, counts, rates, severities, and evidence links.
2. Reject stale-head gold mappings and duplicate case/finding identifiers.
3. Compute lifecycle availability, infrastructure-only, duplicate, actionable-yield, source-anchor, fix-direction, and regression-direction metrics.
4. Compute head-matched true positives, false positives, false negatives, precision, recall, F1, and critical/high recall.
5. Add Wilson 95% intervals and the five-point non-inferiority decision.
6. Return `INSUFFICIENT_EVIDENCE` for lifecycle, underpowered, missing-reviewer, and zero-denominator cases.
7. Add deterministic Markdown/JSON output and atomic file replacement.
8. Exercise every production branch and enforce all production callable docstrings.

**Verification:**
```bash
python -m coverage run --branch --source=scripts/ci \
  -m pytest tests/test_opencode_review_quality_score.py -q
python -m coverage report \
  --include='scripts/ci/opencode_review_quality_score.py' \
  --fail-under=100 --show-missing
python scripts/ci/opencode_review_quality_score.py \
  --input benchmarks/opencode_review/pilot_baseline_v1.json \
  --json-output /tmp/opencode-review-quality.json \
  --markdown-output /tmp/opencode-review-quality.md
```

## Task 3: Doctor the decision and benchmark limitations

**Files:**
- Create: `docs/doctoring/opencode-review-quality-evaluation.md`
- Create: `docs/superpowers/specs/2026-08-08-opencode-review-quality.md`
- Modify: `CHANGELOG.md`

**Steps:**
1. Document the purposive sampling method and exact observed metrics.
2. State that different lifecycle heads prevent precision, recall, and parity inference.
3. Document the central coverage-to-source-review coupling defect.
4. Specify detector/verifier separation and semantic/merge-readiness separation.
5. Reference real-PR code-review evaluation, industrial filtering, contextual benchmarks, overcorrection, Fugu, Conductor, and TRINITY in APA 7th form.
6. Record the CI, scorer, and baseline in the changelog.

## Task 4: Build a head-matched expert-gold corpus

**Files:**
- Create: `benchmarks/opencode_review/head_matched_v1/*.json`
- Create: `docs/doctoring/opencode-review-annotation-guide.md`
- Create: `scripts/ci/opencode_review_sample.py`
- Create: `scripts/ci/opencode_review_adjudicate.py`
- Create tests for each production script.

**Steps:**
1. Stratify at least 50 PR heads by language, diff size, risk, and defect class.
2. Pin exact base and head SHAs before either reviewer runs.
3. Run OpenCode and CodeRabbit with recorded configurations against identical heads.
4. Have two independent experts label defects from full repository context.
5. Adjudicate disagreements without showing reviewer identity.
6. Freeze the gold set and hash every record.
7. Keep the final held-out set unavailable to routing and prompt calibration.

## Task 5: Separate semantic verdict from merge readiness

**Files:**
- Modify only after lease clearance: `.github/workflows/opencode-review-dispatch.yml`
- Create: `scripts/ci/opencode_review_decision.py`
- Create: `tests/test_opencode_review_decision.py`

**Steps:**
1. Write failing tests proving coverage failure cannot create a source finding.
2. Define a versioned decision envelope with `review_verdict` and `merge_readiness` as independent fields.
3. Move coverage/check/approval logic into merge readiness.
4. Keep semantic review active whenever exact-head bounded source evidence is available.
5. Publish infrastructure blockers as check summaries, never line-level source defects.
6. Preserve fail-closed approval and branch protection.
7. Verify the exact current dispatch head before every write.

## Task 6: Add detector–verifier orchestration in shadow mode

**Files:**
- Create: `scripts/ci/run_opencode_semantic_review_pool.sh`
- Create: `scripts/ci/opencode_review_verify.py`
- Modify after lease clearance: `.github/workflows/opencode-review-dispatch.yml`
- Add complete contract, fuzz, and adversarial tests.

**Steps:**
1. Classify PR risk, languages, paths, and diff-size bucket deterministically.
2. Route low-risk PRs to a single detector and high-risk PRs to diverse specialist detectors.
3. Use independent verifier calls for every publication candidate.
4. Require path, positive line, trigger, impact, root cause, fix direction, and regression direction.
5. Suppress stale, duplicate, unsupported, and infrastructure-only findings.
6. Record model, provider, role, prompt hash, reasoning effort, and evidence hash.
7. Use `NVIDIA_NIM_API_KEY`; do not add or repurpose `COPILOT_GITHUB_TOKEN`.
8. Publish metrics only; do not publish GitHub blockers during shadow mode.

## Task 7: Calibrate and run the held-out comparison

**Steps:**
1. Tune routing and verifier thresholds only on the development split.
2. Run ablations for one detector, detector+verifier, parallel detectors, role-specific effort, and bounded recursion.
3. Evaluate once on the frozen held-out set.
4. Require the scorer's eligibility and commercial gates.
5. Publish per-language, per-size, and per-defect-class failures, not only aggregate F1.
6. Preserve failed evidence and negative results in doctoring.

## Task 8: Limited production rollout

**Steps:**
1. Publish non-required OpenCode comments to a bounded repository cohort.
2. Track developer resolution, rejection, duplicate, and time-to-resolution metrics.
3. Compare reviewer utility and cycle time with the reference cohort.
4. Roll back automatically on critical/high miss, source-contract failure, or false-blocker spike.
5. Make OpenCode required only after two consecutive frozen benchmark versions pass and independent approval is obtained.

## Completion definition

The program is complete only when the exact-head held-out gate passes, critical/high recall is 100%, infrastructure-only source findings are zero, duplicate publication is below 5%, protected-branch integration is green, and independent human reviewers approve the transition. Until then, the correct status is **improving, not CodeRabbit-equivalent**.
