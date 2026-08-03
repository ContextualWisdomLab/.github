# Naruon Hourly Commercial Readiness Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a policy-preserving Naruon review→fix→verify→merge loop every hour and create exactly one validated buyer-gap PR whenever the open PR queue reaches zero.

**Architecture:** A fixed-target hourly orchestrator dispatches the existing central PR fix and merge schedulers. A separate default-branch-only development worker revalidates an empty queue, runs a bounded OpenCode edit against `develop`, executes deterministic backend/frontend validation, and opens one normal PR without ever writing directly to `develop`.

**Tech Stack:** GitHub Actions, GitHub CLI/API, Bash, Python 3.14, OpenCode CLI, GitHub Models, FastAPI/Pytest/Ruff, Next.js/pnpm/Vitest/TypeScript.

## Global Constraints

- Target repository is exactly `ContextualWisdomLab/naruon`.
- Base branch is exactly `develop`.
- The hourly cron is `7 * * * *`.
- Privileged workflows expose `repository_dispatch`, never `workflow_dispatch`.
- No direct commit or force-push to `develop`.
- Product development runs only when the live open PR count is zero.
- At most one `autonomous/commercial-readiness-*` branch or PR may be active.
- One development run selects exactly one buyer-visible gap.
- Naruon remains an email workspace, not groupware, HRIS, ERP, or an approval engine.
- New database objects use two-or-more-word names and `snake_case` by default.
- Public identifiers are opaque and non-sequential.
- Changed public Python behavior has docstrings and focused regression tests.
- Product code changes update `CHANGELOG.md`.
- Merges remain subject to current-head required checks and independent approval.

---

### Task 1: Add workflow contract tests first

**Files:**
- Create: `tests/test_naruon_commercial_readiness_hourly_contract.py`
- Test: `tests/test_naruon_commercial_readiness_hourly_contract.py`

**Interfaces:**
- Consumes: central workflow source text under `.github/workflows/`.
- Produces: static trust-boundary and orchestration contract tests for both workflows.

- [ ] **Step 1: Write tests that require the hourly orchestrator contract**

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_hourly_loop_has_fixed_schedule_and_no_branch_selected_dispatch() -> None:
    workflow = workflow_text("naruon-commercial-readiness-hourly.yml")
    trigger = workflow.split("concurrency:", 1)[0]

    assert 'cron: "7 * * * *"' in trigger
    assert "repository_dispatch:" in trigger
    assert "types: [naruon-commercial-readiness-hourly]" in trigger
    assert "workflow_dispatch:" not in trigger
    assert "TARGET_REPOSITORY: ContextualWisdomLab/naruon" in workflow
    assert "TARGET_BASE_BRANCH: develop" in workflow
```

- [ ] **Step 2: Require fix, merge, and zero-queue development dispatches**

```python
def test_hourly_loop_dispatches_fix_merge_and_zero_queue_development() -> None:
    workflow = workflow_text("naruon-commercial-readiness-hourly.yml")

    assert '"event_type": "pr-review-fix-scheduler"' in workflow
    assert '"event_type": "merge-scheduler"' in workflow
    assert '"event_type": "naruon-commercial-readiness-development"' in workflow
    assert 'if [ "$OPEN_PR_COUNT" -ne 0 ]; then' in workflow
    assert 'review_dispatch_limit: "-1"' in workflow
    assert 'stale_opencode_minutes: "60"' in workflow
```

- [ ] **Step 3: Require development worker safety and validation gates**

```python
def test_development_worker_is_bounded_and_opens_only_a_pr() -> None:
    workflow = workflow_text("naruon-commercial-readiness-development.yml")
    trigger = workflow.split("concurrency:", 1)[0]

    assert "repository_dispatch:" in trigger
    assert "types: [naruon-commercial-readiness-development]" in trigger
    assert "workflow_dispatch:" not in trigger
    assert 'TARGET_REPOSITORY: "ContextualWisdomLab/naruon"' in workflow
    assert 'TARGET_BASE_BRANCH: "develop"' in workflow
    assert 'open_pr_count="$(gh api --paginate' in workflow
    assert 'if [ "$open_pr_count" -ne 0 ]; then' in workflow
    assert "autonomous/commercial-readiness-" in workflow
    assert "git push origin \"HEAD:${DEVELOPMENT_BRANCH}\"" in workflow
    assert "gh pr create" in workflow
    assert "git push origin HEAD:develop" not in workflow


def test_development_worker_blocks_sensitive_and_unreviewable_changes() -> None:
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "^\\.github/workflows/" in workflow
    assert "^\\.env" in workflow
    assert "BEGIN.*PRIVATE KEY" in workflow
    assert "MAX_CHANGED_FILES=12" in workflow
    assert "MAX_CHANGED_LINES=1200" in workflow
    assert 'grep -Eq "(^|/)test[^/]*\\.|(^|/)tests?/"' in workflow
    assert 'grep -Fxq "CHANGELOG.md"' in workflow


def test_development_worker_runs_repository_validation() -> None:
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "python -m ruff check ." in workflow
    assert "python -m pytest -q" in workflow
    assert "pnpm install --frozen-lockfile" in workflow
    assert "pnpm run lint" in workflow
    assert "pnpm run typecheck" in workflow
    assert "pnpm test" in workflow
    assert "pnpm run build" in workflow
```

- [ ] **Step 4: Run the tests and verify they fail because workflows do not exist**

Run:

```bash
python -m pytest -q tests/test_naruon_commercial_readiness_hourly_contract.py
```

Expected: FAIL with `FileNotFoundError` for one or both workflow files.

- [ ] **Step 5: Commit the failing contracts**

```bash
git add tests/test_naruon_commercial_readiness_hourly_contract.py
git commit -m "test: define naruon hourly commercial readiness contracts"
```

### Task 2: Implement the fixed-target hourly orchestrator

**Files:**
- Create: `.github/workflows/naruon-commercial-readiness-hourly.yml`
- Test: `tests/test_naruon_commercial_readiness_hourly_contract.py`

**Interfaces:**
- Consumes: central repository-dispatch entrypoints `pr-review-fix-scheduler`, `merge-scheduler`, and `naruon-commercial-readiness-development`.
- Produces: one hourly orchestration run and structured `client_payload` values.

- [ ] **Step 1: Create a default-branch-only scheduled trigger**

```yaml
name: Naruon Commercial Readiness Hourly Loop

on:
  schedule:
    - cron: "7 * * * *"
  repository_dispatch:
    types: [naruon-commercial-readiness-hourly]

concurrency:
  group: naruon-commercial-readiness-hourly
  cancel-in-progress: false

permissions:
  contents: read
```

- [ ] **Step 2: Add fixed target variables and least-privilege job permissions**

```yaml
jobs:
  orchestrate:
    runs-on: ubuntu-latest
    permissions:
      actions: write
      contents: write
      pull-requests: read
    env:
      GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
      TARGET_REPOSITORY: ContextualWisdomLab/naruon
      TARGET_BASE_BRANCH: develop
      DISPATCH_REPOSITORY: ContextualWisdomLab/.github
```

- [ ] **Step 3: Fetch the live PR queue and expose it to later steps**

```bash
open_pr_json="$(
  gh api --paginate \
    -H "Accept: application/vnd.github+json" \
    "repos/${TARGET_REPOSITORY}/pulls?state=open&base=${TARGET_BASE_BRANCH}&per_page=100" \
  | jq -s 'add'
)"
open_pr_count="$(jq 'length' <<<"$open_pr_json")"
open_pr_numbers="$(jq -r 'map(.number | tostring) | join(",")' <<<"$open_pr_json")"
{
  printf 'count=%s\n' "$open_pr_count"
  printf 'numbers=%s\n' "$open_pr_numbers"
} >>"$GITHUB_OUTPUT"
```

- [ ] **Step 4: Dispatch review fixes and merge processing**

Use one helper that posts typed payloads to the central default branch:

```bash
dispatch() {
  local event_type="$1"
  local payload_file="$2"
  jq -n \
    --arg event_type "$event_type" \
    --slurpfile client_payload "$payload_file" \
    '{event_type: $event_type, client_payload: $client_payload[0]}' \
  | gh api -X POST "repos/${DISPATCH_REPOSITORY}/dispatches" --input -
}
```

Fix scheduler payload:

```json
{
  "target_repository": "ContextualWisdomLab/naruon",
  "base_branch": "develop",
  "max_prs": "100",
  "max_dispatches": "10",
  "retry_hours": "1",
  "dry_run": false
}
```

Merge scheduler payload:

```json
{
  "target_repository": "ContextualWisdomLab/naruon",
  "base_branch": "develop",
  "max_prs": "100",
  "trigger_reviews": true,
  "review_dispatch_limit": "-1",
  "branch_update_limit": "10",
  "enable_auto_merge": true,
  "merge_mode": "direct_or_auto",
  "update_branches": true,
  "stale_opencode_minutes": "60"
}
```

- [ ] **Step 5: Dispatch product development only at zero live PRs**

```bash
if [ "$OPEN_PR_COUNT" -ne 0 ]; then
  echo "Development suppressed because ${OPEN_PR_COUNT} PR(s) remain open."
  exit 0
fi

autonomous_count="$(
  gh api --paginate \
    "repos/${TARGET_REPOSITORY}/branches?per_page=100" \
  | jq -s '[add[] | select(.name | startswith("autonomous/commercial-readiness-"))] | length'
)"
if [ "$autonomous_count" -ne 0 ]; then
  echo "Development suppressed because an autonomous branch already exists."
  exit 0
fi
```

Then dispatch:

```json
{
  "target_repository": "ContextualWisdomLab/naruon",
  "base_branch": "develop"
}
```

- [ ] **Step 6: Emit a job summary**

```bash
{
  echo "## Naruon commercial readiness loop"
  echo "- Repository: ${TARGET_REPOSITORY}"
  echo "- Base: ${TARGET_BASE_BRANCH}"
  echo "- Open PRs: ${OPEN_PR_COUNT} (${OPEN_PR_NUMBERS:-none})"
  echo "- Review-fix dispatch: submitted"
  echo "- Review/merge dispatch: submitted"
  echo "- Development dispatch: ${DEVELOPMENT_DECISION}"
} >>"$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 7: Run the focused contract test**

Run:

```bash
python -m pytest -q tests/test_naruon_commercial_readiness_hourly_contract.py \
  -k hourly_loop
```

Expected: PASS.

- [ ] **Step 8: Commit the orchestrator**

```bash
git add .github/workflows/naruon-commercial-readiness-hourly.yml
git commit -m "feat(automation): schedule naruon commercial readiness hourly"
```

### Task 3: Implement the bounded commercial-readiness development worker

**Files:**
- Create: `.github/workflows/naruon-commercial-readiness-development.yml`
- Test: `tests/test_naruon_commercial_readiness_hourly_contract.py`

**Interfaces:**
- Consumes: `repository_dispatch` payload with fixed target/base, OIDC OpenCode token exchange, Naruon issues and source tree.
- Produces: zero changes or one branch `autonomous/commercial-readiness-<run-id>` and one PR to `develop`.

- [ ] **Step 1: Add the trusted trigger, concurrency, and permissions**

```yaml
name: Naruon Commercial Readiness Development

on:
  repository_dispatch:
    types: [naruon-commercial-readiness-development]

concurrency:
  group: naruon-commercial-readiness-development
  cancel-in-progress: false

permissions:
  contents: read
  id-token: write
```

- [ ] **Step 2: Validate exact target metadata and an empty PR queue**

```bash
if [ "$TARGET_REPOSITORY" != "ContextualWisdomLab/naruon" ]; then
  echo "::error::Unexpected target repository: $TARGET_REPOSITORY"
  exit 1
fi
if [ "$TARGET_BASE_BRANCH" != "develop" ]; then
  echo "::error::Unexpected target base branch: $TARGET_BASE_BRANCH"
  exit 1
fi
open_pr_count="$(gh api --paginate \
  "repos/${TARGET_REPOSITORY}/pulls?state=open&base=${TARGET_BASE_BRANCH}&per_page=100" \
  | jq -s 'add | length')"
if [ "$open_pr_count" -ne 0 ]; then
  echo "Open PRs appeared after dispatch; development is a no-op."
  exit 0
fi
```

- [ ] **Step 3: Exchange OIDC for the scoped OpenCode GitHub App token**

Copy the fail-closed token-exchange pattern from `.github/workflows/pr-review-autofix.yml`:

```bash
oidc_response="$(curl -fsS \
  -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=opencode-github-action")"
oidc_token="$(jq -r '.value // empty' <<<"$oidc_response")"
token_response="$(curl -fsS -X POST \
  -H "Authorization: Bearer ${oidc_token}" \
  "https://api.opencode.ai/exchange_github_app_token")"
app_token="$(jq -r '.token // empty' <<<"$token_response")"
test -n "$app_token"
```

- [ ] **Step 4: Clone the live base and create a unique branch**

```bash
base_sha="$(gh api "repos/${TARGET_REPOSITORY}/git/ref/heads/${TARGET_BASE_BRANCH}" --jq '.object.sha')"
[[ "$base_sha" =~ ^[0-9a-f]{40}$ ]]
workspace="$RUNNER_TEMP/naruon-commercial-readiness"
git init -q "$workspace"
git -C "$workspace" remote add origin "${GITHUB_SERVER_URL}/${TARGET_REPOSITORY}.git"
git -C "$workspace" fetch --no-tags origin "$base_sha"
git -C "$workspace" switch --detach "$base_sha"
development_branch="autonomous/commercial-readiness-${GITHUB_RUN_ID}"
git -C "$workspace" switch -c "$development_branch"
```

- [ ] **Step 5: Collect trusted product context and untrusted issue evidence**

Write `RUNNER_TEMP/commercial-readiness-context.md` with:

- central `docs/CWL-MASTER-CONTEXT.md` excerpts;
- target `AGENTS.md` and product-spec paths;
- live open issues (`number`, `title`, `labels`, bounded body);
- recent merged PRs;
- current version and changelog header;
- explicit delimiters marking issue and PR text as untrusted.

- [ ] **Step 6: Configure a bounded OpenCode editor**

Use GitHub Models `openai/gpt-5`, high reasoning, at most 20 steps, with:

```json
{
  "edit": "allow",
  "bash": "deny",
  "read": "allow",
  "grep": "allow",
  "glob": "allow",
  "list": "allow",
  "task": "deny",
  "webfetch": "deny",
  "websearch": "deny",
  "external_directory": "deny"
}
```

The prompt requires exactly one gap, tests first, minimal scope, no new dependency, no workflow edits, no direct release, no groupware drift, and a final concise summary.

- [ ] **Step 7: Run OpenCode and restore temporary configuration**

```bash
cd "$TARGET_WORKSPACE"
timeout 18000 opencode run "$(cat "$RUNNER_TEMP/commercial-readiness-prompt.md")" \
  --pure \
  --agent commercial-readiness \
  --model github-models/openai/gpt-5 \
  --title "Naruon commercial readiness ${GITHUB_RUN_ID}"
```

Restore or remove `opencode.jsonc` and temporary prompts before inspecting the diff.

- [ ] **Step 8: Enforce changed-file, test, changelog, and secret gates**

```bash
MAX_CHANGED_FILES=12
MAX_CHANGED_LINES=1200
mapfile -t changed_files < <({ git diff --name-only; git ls-files --others --exclude-standard; } | sort -u)
changed_file_count="${#changed_files[@]}"
changed_lines="$(git diff --numstat | awk '{added += $1; deleted += $2} END {print added + deleted + 0}')"
```

Reject when:

- `changed_file_count > 12`;
- `changed_lines > 1200`;
- a changed path matches `^\.github/workflows/`, `^\.env`, private-key or credential paths, or agent-control files;
- product code changed without a path matching `(^|/)test[^/]*\.|(^|/)tests?/`;
- product code changed without `CHANGELOG.md`;
- the diff contains `BEGIN.*PRIVATE KEY`, token-like assignments, or conflict markers.

- [ ] **Step 9: Run backend validation when backend files changed**

```bash
python -m pip install --disable-pip-version-check --require-hashes \
  -r backend/requirements-hashes.txt
cd backend
python -m ruff check .
PYTHONWARNINGS=error DISABLE_BACKGROUND_WORKERS=1 python -m pytest -q
```

- [ ] **Step 10: Run frontend validation when frontend files changed**

```bash
corepack enable pnpm
cd frontend
pnpm install --frozen-lockfile
pnpm run lint
pnpm run typecheck
pnpm test
pnpm run build
```

- [ ] **Step 11: Revalidate the race boundary before publishing**

```bash
live_base_sha="$(gh api "repos/${TARGET_REPOSITORY}/git/ref/heads/${TARGET_BASE_BRANCH}" --jq '.object.sha')"
if [ "$live_base_sha" != "$BASE_SHA" ]; then
  echo "::error::Base branch moved during development."
  exit 1
fi
open_pr_count="$(gh api --paginate \
  "repos/${TARGET_REPOSITORY}/pulls?state=open&base=${TARGET_BASE_BRANCH}&per_page=100" \
  | jq -s 'add | length')"
if [ "$open_pr_count" -ne 0 ]; then
  echo "::error::Another PR appeared during development."
  exit 1
fi
```

- [ ] **Step 12: Commit, push, and open one normal PR**

```bash
git add -A
git commit -m "feat(commercial-readiness): close buyer-visible product gap"
git push origin "HEAD:${DEVELOPMENT_BRANCH}"
pr_url="$(gh pr create \
  --repo "$TARGET_REPOSITORY" \
  --base "$TARGET_BASE_BRANCH" \
  --head "$DEVELOPMENT_BRANCH" \
  --title "feat(commercial-readiness): close buyer-visible product gap" \
  --body-file "$RUNNER_TEMP/commercial-readiness-pr.md")"
```

- [ ] **Step 13: Dispatch current-head review and merge processing for the new PR**

Read the PR number from `pr_url`, then send `merge-scheduler` with `pr_number`, `trigger_reviews=true`, `review_dispatch_limit=-1`, `enable_auto_merge=true`, and `merge_mode=direct_or_auto`.

- [ ] **Step 14: Run the full contract test file**

Run:

```bash
python -m pytest -q tests/test_naruon_commercial_readiness_hourly_contract.py
```

Expected: PASS.

- [ ] **Step 15: Commit the development worker**

```bash
git add .github/workflows/naruon-commercial-readiness-development.yml
git commit -m "feat(automation): develop one naruon buyer gap at zero PRs"
```

### Task 4: Verify central governance and publish the automation PR

**Files:**
- Modify only if tests expose a contract conflict: the two new workflow files and their new test file.
- Review: `docs/superpowers/specs/2026-08-03-naruon-hourly-commercial-readiness-loop-design.md`
- Review: `docs/superpowers/plans/2026-08-03-naruon-hourly-commercial-readiness-loop.md`

**Interfaces:**
- Consumes: all central repository test and lint contracts.
- Produces: one reviewable PR to `ContextualWisdomLab/.github:main`.

- [ ] **Step 1: Run focused tests**

```bash
python -m pytest -q \
  tests/test_naruon_commercial_readiness_hourly_contract.py \
  tests/test_required_workflow_queue_contract.py
```

Expected: PASS.

- [ ] **Step 2: Run the central repository test suite**

```bash
python -m pytest -q
```

Expected: PASS with no warnings promoted to errors.

- [ ] **Step 3: Run workflow and Python static checks**

```bash
actionlint \
  .github/workflows/naruon-commercial-readiness-hourly.yml \
  .github/workflows/naruon-commercial-readiness-development.yml
python -m compileall -q tests
```

Expected: PASS.

- [ ] **Step 4: Review the branch diff for scope and secrets**

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git grep -nE 'BEGIN .*PRIVATE KEY|ghp_[A-Za-z0-9]+|github_pat_' main...HEAD -- . ':!docs/superpowers/**'
```

Expected: no whitespace errors, no credentials, and only the design, plan, two workflows, and one contract-test file.

- [ ] **Step 5: Commit any final test-only corrections**

```bash
git add .
git commit -m "test(automation): enforce naruon hourly loop boundaries"
```

Skip the commit when the tree is already clean.

- [ ] **Step 6: Push and open the central PR**

```bash
git push -u origin ops/naruon-hourly-commercial-readiness-20260803
gh pr create \
  --repo ContextualWisdomLab/.github \
  --base main \
  --head ops/naruon-hourly-commercial-readiness-20260803 \
  --title "feat(automation): run naruon commercial readiness hourly" \
  --body-file /tmp/naruon-hourly-loop-pr.md
```

- [ ] **Step 7: Inspect every review thread and required check**

Use current-head metadata, fix all valid findings, rerun failed checks, resolve addressed threads, and do not merge while any required evidence is missing.

- [ ] **Step 8: Merge with the repository-permitted method**

Use the current immutable head SHA and the repository's allowed merge method. After merge, confirm the workflow exists on `main` and the next `7 * * * *` schedule is enabled.

## Plan self-review

- Spec coverage: all design acceptance criteria map to Tasks 1–4.
- Placeholder scan: no `TBD`, deferred implementation instruction, or unspecified validation step remains.
- Type consistency: event types, repository names, base branch, branch prefix, limits, and workflow filenames are identical across tasks.
- Scope: the plan changes central orchestration only and creates product changes exclusively through normal Naruon PRs.
