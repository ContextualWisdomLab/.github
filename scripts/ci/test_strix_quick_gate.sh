Warning: truncated output (original token count: 161965)
Total output lines: 13123

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(
	CDPATH=''
	cd -P -- "$(dirname -- "$0")"
	pwd -P
)"
REPO_ROOT="$(
	CDPATH=''
	cd -P -- "$SCRIPT_DIR/../.."
	pwd -P
)"
GATE_SCRIPT="$REPO_ROOT/scripts/ci/strix_quick_gate.sh"

FAILURES=0
TIMEOUT_TEST_PROCESS_SECONDS="${STRIX_TEST_PROCESS_TIMEOUT_SECONDS:-30}"
TIMEOUT_TEST_FAKE_SLEEP_SECONDS="${STRIX_TEST_FAKE_SLEEP_SECONDS:-60}"

if ! [[ "$TIMEOUT_TEST_PROCESS_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
	! [[ "$TIMEOUT_TEST_FAKE_SLEEP_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
	[ "$TIMEOUT_TEST_FAKE_SLEEP_SECONDS" -le "$TIMEOUT_TEST_PROCESS_SECONDS" ]; then
	printf 'STRIX_TEST_FAKE_SLEEP_SECONDS must be a positive integer greater than STRIX_TEST_PROCESS_TIMEOUT_SECONDS.\n' >&2
	exit 2
fi

# Keep local developer/provider secrets from changing fake Strix model routing.
unset STRIX_LLM
unset LLM_API_KEY
unset LLM_API_BASE
unset OPENAI_API_KEY
unset STRIX_GITHUB_MODELS_TOKEN
unset LITELLM_API_KEY
unset LITELLM_MASTER_KEY
unset GEMINI_API_KEY
unset GOOGLE_APPLICATION_CREDENTIALS
if ! python3 -c 'import pathlib' >/dev/null 2>&1; then
	export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"
fi

record_failure() {
	echo "FAIL: $1" >&2
	FAILURES=$((FAILURES + 1))
}

assert_equals() {
	local expected="$1"
	local actual="$2"
	local message="$3"

	if [ "$expected" != "$actual" ]; then
		record_failure "$message (expected='$expected' actual='$actual')"
	fi
}

print_assertion_source() {
	local file_path="$1"

	echo "Assertion source (first 240 lines): $file_path" >&2
	if [ ! -f "$file_path" ]; then
		echo "  | <missing file>" >&2
		return
	fi
	sed -n '1,240p' "$file_path" | sed 's/^/  | /' >&2
}

assert_file_contains() {
	local file_path="$1"
	local needle="$2"
	local message="$3"

	if [ ! -f "$file_path" ] || ! grep -Fq -- "$needle" "$file_path"; then
		record_failure "$message (missing '$needle')"
		print_assertion_source "$file_path"
	fi
}

assert_file_matches() {
	local file_path="$1"
	local pattern="$2"
	local message="$3"

	if [ ! -f "$file_path" ] || ! grep -Eq -- "$pattern" "$file_path"; then
		record_failure "$message (missing pattern '$pattern')"
		print_assertion_source "$file_path"
	fi
}

assert_file_not_contains() {
	local file_path="$1"
	local needle="$2"
	local message="$3"

	if [ -f "$file_path" ] && grep -Fq -- "$needle" "$file_path"; then
		record_failure "$message (unexpected '$needle')"
	fi
}

seal_opencode_test_artifacts() {
	local runner_temp="$1"
	local head_sha="$2"
	local run_id="$3"
	local run_attempt="$4"
	shift 4

	OPENCODE_ARTIFACT_MANIFEST_SHA256="$(
		python3 - "$runner_temp" "$head_sha" "$run_id" "$run_attempt" "$@" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

runner_temp = Path(sys.argv[1]).resolve(strict=True)
artifact_paths = [Path(value) for value in sys.argv[5:]]
digests = {}
for path in artifact_paths:
    resolved = path.resolve(strict=True)
    if resolved.parent != runner_temp or not resolved.is_file() or resolved.stat().st_size <= 0:
        raise SystemExit(f"unsafe OpenCode test artifact: {path.name}")
    resolved.chmod(0o600)
    digests[resolved.name] = hashlib.sha256(resolved.read_bytes()).hexdigest()

manifest = runner_temp / "opencode-artifact-manifest.json"
manifest.write_text(
    json.dumps(
        {
            "schema": 1,
            "head_sha": sys.argv[2],
            "run_id": sys.argv[3],
            "run_attempt": sys.argv[4],
            "artifacts": digests,
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
manifest.chmod(0o600)
print(hashlib.sha256(manifest.read_bytes()).hexdigest())
PY
	)"
	export OPENCODE_ARTIFACT_MANIFEST_SHA256
}

assert_workflow_uses_are_sha_pinned() {
	local workflow_file="$1"
	local message="$2"
	local line_number
	local line_text
	local uses_ref

	while IFS=: read -r line_number line_text; do
		uses_ref="$(
			printf '%s\n' "$line_text" |
				sed -E 's/^[[:space:]]*uses:[[:space:]]*([^[:space:]#]+).*/\1/'
		)"
		if ! printf '%s\n' "$line_text" |
			grep -Eq '^[[:space:]]*uses:[[:space:]]+[^[:space:]#]+@[0-9a-fA-F]{40}[[:space:]]+# v[0-9]+([.][0-9]+)*([[:space:]]|$)'; then
			record_failure "$message must pin uses refs to full commit SHAs with trailing version comments at line $line_number: $uses_ref"
		fi
	done < <(grep -nE '^[[:space:]]+uses:[[:space:]]+' "$workflow_file" || true)
}

assert_strix_pr_scope_includes_deployment_context() {
	assert_file_contains "$GATE_SCRIPT" "needs_deployment_context=0" "strix gate tracks deployment-context scoped PRs"
	assert_file_contains "$GATE_SCRIPT" ".github/workflows/* | Dockerfile | Dockerfile.* | frontend/Dockerfile | frontend/next.config.ts | docker-compose*.yml | render.yaml" "strix gate recognizes deployment and CI files"
	assert_file_contains "$GATE_SCRIPT" "Dockerfile.test" "strix gate includes test-image Dockerfiles with workflow scan context"
	assert_file_contains "$GATE_SCRIPT" "Dockerfile | */Dockerfile | Dockerfile.* | */Dockerfile.* | Containerfile | */Containerfile | Makefile | */Makefile" "strix gate treats deployment files as source files"
	assert_file_contains "$GATE_SCRIPT" "backend/scripts/docker_entrypoint.sh" "strix gate includes the combined Docker image entrypoint with deployment context"
	assert_file_contains "$GATE_SCRIPT" "backend/api/auth.py" "strix gate includes backend auth context for deployment scans"
	assert_file_contains "$GATE_SCRIPT" "backend/app/auth.py" "strix gate includes app-package auth context for backend scans"
	assert_file_contains "$GATE_SCRIPT" "frontend/package-lock.json" "strix gate includes frontend dependency lock context"
	assert_file_contains "$GATE_SCRIPT" "frontend/postcss.config.mjs" "strix gate includes frontend build config context"
	assert_file_contains "$GATE_SCRIPT" "VERSION" "strix gate includes release version context for workflow scans"
	assert_file_contains "$GATE_SCRIPT" "*.rs" "strix gate recognizes Rust source files"
	assert_file_contains "$GATE_SCRIPT" "Cargo.toml | */Cargo.toml | Cargo.lock | */Cargo.lock" "strix gate recognizes Rust dependency manifests"
	assert_file_contains "$GATE_SCRIPT" 'if [ -f "$REPO_ROOT/Cargo.toml" ]; then' "strix gate detects Rust workspaces for workflow scan context"
	assert_file_contains "$GATE_SCRIPT" "rust-toolchain.toml" "strix gate includes Rust toolchain context for workflow scans"
	assert_file_contains "$GATE_SCRIPT" "deny.toml" "strix gate includes Rust dependency policy context for workflow scans"
	assert_file_contains "$GATE_SCRIPT" "scripts/ci/test_*.sh" "strix gate excludes large CI self-test harnesses from PR scan targets"
}

assert_strix_pr_scope_includes_contextual_orchestrator_context() {
	assert_file_contains "$GATE_SCRIPT" "needs_contextual_orchestrator_python=0" "strix gate tracks contextual-orchestrator package context"
	assert_file_contains "$GATE_SCRIPT" 'contextual_orchestrator/*.py)' "strix gate detects contextual-orchestrator Python changes"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false ls-tree -rz --name-only "$contextual_orchestrator_head_sha" -- contextual_orchestrator' "strix gate enumerates contextual-orchestrator context from the exact PR head"
	assert_file_contains "$GATE_SCRIPT" 'contextual_orchestrator_tree_file="$(mktemp' "strix gate bounds contextual-orchestrator context enumeration in a private file"
	assert_file_contains "$GATE_SCRIPT" 'rm -f -- "$contextual_orchestrator_tree_file"' "strix gate cleans contextual-orchestrator context enumeration evidence"
}

assert_strix_workflow_pr_trigger_hardened() {
	local workflow_file="$REPO_ROOT/.github/workflows/strix.yml"

	assert_file_contains "$workflow_file" "branches: [main, develop, master]" "strix workflow scans GitHub Flow and Git Flow protected branches"
	assert_file_contains "$workflow_file" "pull_request_target:" "strix workflow uses trusted PR trigger"
	assert_file_contains "$workflow_file" 'strix-${{ github.event_name }}-' "strix workflow isolates manual evidence runs from required PR contexts"
	assert_file_contains "$workflow_file" "format('pr-{0}', github.event.pull_request.number)" "strix workflow scopes pull_request_target concurrency to the active pull request"
	assert_file_contains "$workflow_file" "github.event.client_payload.target_repository ||" "strix manual dispatch concurrency scopes to the target repository when provided"
	assert_file_contains "$workflow_file" "github.event.client_payload.pr_number != '' && format('pr-{0}', github.event.client_payload.pr_number)" "strix workflow retains a manual PR fallback group when no head SHA is provided"
	assert_file_contains "$workflow_file" "github.ref }}" "strix workflow scopes non-PR concurrency to the current ref"
	assert_file_not_contains "$workflow_file" "format('pr-{0}-{1}'" "strix workflow does not keep stale head-specific concurrency groups"
	assert_file_contains "$workflow_file" "cancel-in-progress: true" "strix workflow cancels stale PR evidence runs when a newer PR event arrives"
	assert_file_contains "$workflow_file" "default-branch repository_dispatch evidence cannot cancel" "strix workflow documents manual evidence isolation from branch protection contexts"
	assert_file_contains "$workflow_file" "PR-number scope keeps the queue on the current HEAD" "strix workflow documents current-head queue management"
	assert_file_contains "$workflow_file" "refs/pull/<n>/head has already advanced before this queued run starts" "strix workflow documents stale scan queue avoidance"
	status_token_count="$(grep -c '^[[:space:]]*GITHUB_STATUS_TOKEN:' "$workflow_file" || true)"
	assert_equals "0" "$status_token_count" "strix scan job never receives a status-capable GitHub token"
	local status_permission_count status_publish_step_count
	status_permission_count="$(grep -c '^[[:space:]]*statuses: write' "$workflow_file")"
	assert_equals "1" "$status_permission_count" "strix workflow grants exactly one status-write scope, pinned to the scan job by main's required-workflow smoke"
	status_publish_step_count="$(grep -c '^[[:space:]]*- name: Publish same-head manual Strix status' "$workflow_file")"
	assert_equals "1" "$status_publish_step_count" "strix workflow publishes status only from the isolated publication job"
	assert_file_contains "$workflow_file" 'dispatch_metadata_validated: ${{ steps.dispatch_metadata.outputs.validated }}' "strix scan job exports live dispatch validation evidence"
	assert_file_contains "$workflow_file" 'id: dispatch_metadata' "strix repository dispatch validation has a stable output identity"
	assert_file_contains "$workflow_file" 'echo "validated=true" >>"$GITHUB_OUTPUT"' "strix repository dispatch validation records success only after live metadata validation"
	assert_file_contains "$workflow_file" "needs.strix.outputs.dispatch_metadata_validated == 'true'" "strix status publication requires live dispatch metadata validation"
	assert_file_not_contains "$workflow_file" "github.event.pull_request.number == 240" "strix workflow must not hard-code repository-specific PR bypasses"
	assert_file_contains "$workflow_file" "models: read" "strix workflow grants only the GitHub Models read permission needed for Strix"
	assert_file_contains "$workflow_file" "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0" "strix workflow pins actions/setup-python"
	assert_file_contains "$workflow_file" 'python-version: "3.13"' "strix workflow runs Python steps on Python 3.13"
	assert_file_contains "$workflow_file" "Resolve trusted Strix source ref" "strix workflow resolves the central trusted Strix source ref"
	assert_file_contains "$workflow_file" "toJSON(job)" "strix workflow derives the trusted source from the job workflow context"
	assert_file_contains "$workflow_file" "workflow_repository" "strix workflow derives the trusted source repository from the job workflow identity"
	assert_file_contains "$workflow_file" "workflow_sha" "strix workflow pins trusted source checkout to the job workflow commit SHA when available"
	assert_file_contains "$workflow_file" "workflow_ref" "strix workflow falls back to the required-workflow source ref when the SHA is unavailable"
	assert_file_contains "$workflow_file" "Checkout trusted Strix source" "strix workflow checks out the central Strix source"
	assert_file_contains "$workflow_file" 'repository: ${{ steps.trusted_source.outputs.repository }}' "strix workflow checks out central Strix scripts instead of target-repo copies"
	assert_file_contains "$workflow_file" 'ref: ${{ steps.trusted_source.outputs.ref }}' "strix workflow checks out the exact trusted Strix source ref"
	assert_file_not_contains "$workflow_file" "      - name: Materialize central Strix dependency lock from PR head" "strix workflow never installs dependencies selected by a PR head"
	assert_file_not_contains "$workflow_file" 'show "$PR_HEAD_SHA:requirements-strix-ci-hashes.txt"' "strix workflow never copies a PR-controlled executable dependency lock"
	assert_file_contains "$workflow_file" 'trusted_lock_blob="$(git rev-parse "HEAD:$trusted_lock")"' "strix workflow binds its dependency lock to the trusted workflow commit"
	assert_file_contains "$workflow_file" 'working_lock_blob="$(git hash-object --no-filters -- "$trusted_lock")"' "strix workflow hashes exact on-disk trusted dependency-lock bytes immediately before install"
	assert_file_contains "$workflow_file" '--only-binary=:all:' "strix workflow installs only hash-verified wheels"
	assert_file_contains "$workflow_file" 'Verify Strix sandbox credential boundary' "strix workflow verifies the installed scanner keeps target commands inside Docker"
	assert_file_contains "$workflow_file" 'sandbox_environment - allowed_sandbox_environment' "strix workflow rejects unreviewed host environment keys in the target-command sandbox"
	assert_file_contains "$workflow_file" 'TRUSTED_STRIX_SOURCE=$trusted_strix_source' "strix workflow exports the central Strix source path"
	assert_file_contains "$workflow_file" 'TRUSTED_STRIX_GATE=$trusted_strix_source/scripts/ci/strix_quick_gate.sh' "strix workflow executes the central Strix gate script"
	assert_file_contains "$workflow_file" "Materialize target workspace" "strix workflow materializes target repository data separately from trusted scripts"
	assert_file_contains "$workflow_file" "types: [strix-scan]" "strix repository dispatch accepts only its dedicated default-branch event type"
	assert_file_contains "$workflow_file" 'REPOSITORY: ${{ github.event.client_payload.target_repository }}' "strix repository dispatch binds the requested target repository before fetching data"
	assert_file_contains "$workflow_file" "Validate repository dispatch against live pull request metadata" "strix repository dispatch validates its supplied PR metadata"
	assert_file_contains "$workflow_file" '[ "$live_base_sha" != "$SUPPLIED_BASE_SHA" ]' "strix repository dispatch verifies the target repository base SHA against the live PR"
	assert_file_contains "$workflow_file" 'GH_TOKEN: ${{ steps.target_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || github.token }}' "strix manual dispatch can use the OpenCode app token or cross-repo approval token to read private target repositories"
	assert_file_contains "$workflow_file" "TARGET_WORKSPACE_SHA" "strix workflow pins target workspace SHA"
	assert_file_contains "$workflow_file" "TRUSTED_WORKSPACE=\$trusted_workspace" "strix workflow exports a trusted workspace path"
	assert_file_contains "$workflow_file" "git -C \"\$TRUSTED_WORKSPACE\"" "strix workflow runs git only inside trusted workspace"
	assert_file_contains "$workflow_file" 'working-directory: ${{ runner.temp }}/trusted-workspace' "strix workflow executes privileged steps from the trusted workspace"
	assert_file_contains "$workflow_file" 'mkdir -p "$TRUSTED_WORKSPACE/scripts/ci"' "strix workflow creates the scheduler policy directory before materializing PR-head scheduler policy"
	assert_file_contains "$workflow_file" 'git -C "$TRUSTED_WORKSPACE" show "$PR_HEAD_SHA:.github/workflows/strix.yml" > "$TRUSTED_WORKSPACE/.github/workflows/strix.yml"' "strix workflow materializes the PR-head workflow for required-path self-test"
	assert_file_contains "$workflow_file" "STRIX_REPO_ROOT:" "strix workflow passes target repository root to the central Strix gate"
	assert_file_contains "$workflow_file" "bash \"\$TRUSTED_STRIX_REQUIRED_SMOKE\"" "strix workflow self-test executes bounded trusted smoke script"
	assert_file_contains "$REPO_ROOT/scripts/ci/strix_required_workflow_smoke.sh" 'TRUSTED_WORKSPACE' "strix required-workflow smoke validates the fetched PR head workflow when available"
	assert_file_not_contains "$workflow_file" "bash \"\$TRUSTED_STRIX_GATE_TEST\"" "strix required path does not execute the full long-form gate harness"
	assert_file_contains "$workflow_file" "bash \"\$TRUSTED_STRIX_GATE\"" "strix workflow executes trusted temp gate script"
	local run_strix_block
	run_strix_block="$(
		awk '
			/- name: Run Strix \(quick\)/ { in_block = 1 }
			in_block && /- name: Collect Strix reports for artifact upload/ { exit }
			in_block { print }
		' "$workflow_file"
	)"
	if [[ "$run_strix_block" == *'GH_TOKEN:'* ]]; then
		record_failure "strix scan step must not inherit a GitHub token"
	fi
	assert_file_contains "$workflow_file" 'find -P "$candidate_dir" -mindepth 1 -type l -print -quit' "strix artifact collection rejects symlinked scanner output"
	assert_file_contains "$workflow_file" "Collect Strix reports for artifact upload" "strix workflow preserves reports from trusted workspace"
	assert_file_contains "$workflow_file" "scan-summary.txt" "strix workflow creates a fallback artifact when Strix emits no report files"
	local checkout_count
	checkout_count="$(grep -Fc "uses: actions/checkout@" "$workflow_file")"
	assert_equals "1" "$checkout_count" "strix workflow uses actions/checkout exactly once for the central trusted source"
	assert_file_not_contains "$workflow_file" 'repository: ${{ github.repository }}' "strix workflow must not checkout target repository code with actions/checkout in privileged context"
	assert_file_not_contains "$workflow_file" "run: bash ./scripts/ci/test_strix_quick_gate.sh" "strix workflow avoids direct repo self-test execution on privileged trigger"
	assert_file_not_contains "$workflow_file" "run: bash ./scripts/ci/strix_quick_gate.sh" "strix workflow avoids direct repo gate execution on privileged trigger"
	assert_file_contains "$workflow_file" "Fetch pull request head for trusted scan" "strix workflow fetches PR head without checkout"
	assert_file_contains "$workflow_file" "github.event.client_payload.pr_number" "strix workflow consumes default-branch PR-scope evidence payloads"
	assert_file_contains "$workflow_file" "github.event.client_payload.strix_llm" "strix workflow accepts only repository-dispatch Strix model overrides"
	assert_file_contains "$workflow_file" "Resolve target repository visibility" "strix workflow resolves target privacy before selecting hosted trial providers"
	assert_file_contains "$workflow_file" "NVIDIA NIM hosted trial scans are limited to public repositories" "strix workflow blocks NVIDIA hosted trial scans for private repositories"
	assert_file_contains "$workflow_file" "github.event.client_payload.pr_number" "strix workflow can run PR-scoped repository_dispatch evidence"
	assert_file_contains "$workflow_file" "PR number and head SHA are required for trusted PR-scope Strix evidence" "strix workflow fails closed when manual PR-scope metadata is incomplete"
	assert_file_contains "$workflow_file" '[[ "$PR_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]]' "strix workflow validates PR head SHA before trusted fetch"
	assert_file_contains "$workflow_file" '[[ "$PR_BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]]' "strix workflow validates PR base SHA before trusted fetch"
	assert_file_contains "$workflow_file" 'fetch --no-tags --depth=1 origin "$PR_BASE_SHA"' "strix workflow fetches manual PR-scope base commit for diffing"
	assert_file_not_contains "$workflow_file" 'show "$PR_HEAD_SHA:opencode.jsonc" > "$TRUSTED_WORKSPACE/opencode.jsonc"' "strix workflow never materializes PR-controlled agent configuration into the privileged scan workspace"
	assert_file_contains "$workflow_file" 'cat-file -e "$PR_HEAD_SHA:scripts/ci/pr_review_merge_scheduler.py"' "strix workflow checks for PR-head scheduler policy without executing it"
	assert_file_contains "$workflow_file" 'show "$PR_HEAD_SHA:scripts/ci/pr_review_merge_scheduler.py" > "$TRUSTED_WORKSPACE/scripts/ci/pr_review_merge_scheduler.py"' "strix workflow materializes PR-head scheduler policy as data for self-test assertions"
	assert_file_contains "$workflow_file" "refs/remotes/pull" "strix workflow verifies fetched PR head ref"
	local pr_head_fetch_block
	pr_head_fetch_block="$(
		awk '
			/- name: Fetch pull request head for trusted scan/ { in_block = 1 }
			in_block && /- name: Self-test Strix gate script/ { exit }
			in_block { print }
		' "$workflow_file"
	)"
	if [[ "$pr_head_fetch_block" != *'GH_TOKEN: ${{ steps.target_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || github.token }}'* ]]; then
		record_failure "strix workflow passes GH_TOKEN to PR head fetch step"
	fi
	if [[ "$pr_head_fetch_block" != *"gh auth setup-git"* ]]; then
		record_failure "strix workflow configures git credentials in PR head fetch step"
	fi
	case "$pr_head_fetch_block" in
		*'fetch --no-tags --depth=1 origin "$PR_HEAD_SHA"'*'show "$PR_HEAD_SHA:scripts/ci/pr_review_merge_scheduler.py" > "$TRUSTED_WORKSPACE/scripts/ci/pr_review_merge_scheduler.py"'*) ;;
		*) record_failure "strix workflow materializes PR-head review policy files only after fetching the PR head commit" ;;
	esac
	assert_file_contains "$workflow_file" "for pr_head_fetch_attempt in 1 2 3 4 5 6" "strix workflow retries stale PR head ref propagation"
	assert_file_contains "$workflow_file" "PR head ref did not resolve to expected commit" "strix workflow fails closed when PR head ref remains stale"
	assert_file_contains "$workflow_file" "sleep 10" "strix workflow waits between stale PR head ref retries"
	assert_file_contains "$workflow_file" "github.event_name == 'pull_request_target'" "strix workflow gates PR context on pull_request_target"
	assert_file_contains "$workflow_file" "GCP_SA_KEY" "strix workflow uses organization Vertex AI credentials when STRIX_LLM selects vertex_ai"
	assert_file_not_contains "$workflow_file" "google-github-actions/auth" "strix workflow must not authenticate to Google Cloud for direct OpenAI scans"
	assert_file_contains "$workflow_file" "provider_mode=vertex_ai" "strix workflow supports Vertex AI provider mode"
	assert_file_contains "$workflow_file" "GOOGLE_APPLICATION_CREDENTIALS" "strix workflow exports Vertex AI credentials only for Vertex provider mode"
	assert_file_contains "$workflow_file" "VERTEXAI_PROJECT" "strix workflow exports LiteLLM Vertex project env"
	assert_file_contains "$workflow_file" "VERTEXAI_LOCATION" "strix workflow exports LiteLLM Vertex location env"
	assert_file_contains "$workflow_file" "timeout-minutes: 120" "strix workflow job budget preserves full-hour scans and artifact publication margin"
	assert_file_contains "$workflow_file" "timeout-minutes: 100" "strix workflow scan step permits legitimate 90-minute repository reviews"
	assert_file_contains "$workflow_file" 'budget_suffix="TIME""OUT"' "strix workflow builds budget env keys without visible timeout signal text"
	assert_file_contains "$workflow_file" 'export "STRIX_TOTAL_${budget_suffix}_SECONDS=5700"' "strix workflow preserves a 95-minute bounded total Strix budget"
	assert_file_contains "$workflow_file" 'process_budget_seconds="5400"' "strix workflow gives a legitimate scan up to 90 minutes"
	assert_file_contains "$workflow_file" 'strix_gate_console.log" "$GITHUB_WORKSPACE/strix_runs/gate-console.log' "strix workflow preserves partial console output after failures and timeouts"
	assert_file_contains "$REPO_ROOT/scripts/ci/strix_quick_gate.sh" "gate-last-attempt.log" "strix gate preserves the last partial attempt before runtime cleanup"
	assert_file_contains "$workflow_file" 'IS_PR_EVIDENCE_RUN: ${{ (github.event_name == '"'"'pull_request_target'"'"' || github.event.client_payload.pr_number != '"'"''"'"') && '"'"'true'"'"' || '"'"'false'"'"' }}' "strix workflow passes PR evidence mode through env"
	assert_file_not_contains "$workflow_file" 'if [ "${{ (github.event_name == '"'"'pull_request_target'"'"' || github.event.client_payload.pr_number != '"'"''"'"') && '"'"'true'"'"' || '"'"'false'"'"' }}" = "true" ]; then' "strix workflow does not interpolate GitHub context inside shell condition"
	assert_file_not_contains "$workflow_file" "LLM_TIMEOUT:" "strix workflow must not expose LLM timeout env names in GitHub logs"
	assert_file_not_contains "$workflow_file" "STRIX_MEMORY_COMPRESSOR_TIMEOUT:" "strix workflow must not expose compressor timeout env names in GitHub logs"
	assert_file_not_contains "$workflow_file" "STRIX_PROCESS_TIMEOUT_SECONDS:" "strix workflow must not expose process timeout env names in GitHub logs"
	assert_file_not_contains "$workflow_file" "STRIX_TOTAL_TIMEOUT_SECONDS:" "strix workflow must not expose total timeout env names in GitHub logs"
	assert_file_not_contains "$workflow_file" "STRIX_PR_SCOPE_MAX_FILES_PER_BATCH" "strix workflow must not split Strix PR evidence into separate scanner runs"
	assert_file_not_contains "$workflow_file" "secrets.STRIX_LLM == 'vertex_ai/gemini-3.1-pro-preview-customtools' && 'vertex_ai/gemini-2.5-flash'" "strix workflow must not quarantine the approved Vertex preview model after organization secret visibility is fixed"
	assert_file_contains "$workflow_file" "steps.target_visibility.outputs.is_private == 'false' && 'nvidia_nim/nvidia/nemotron-3-super-120b-a12b' || 'gpt-5.6-luna'" "strix workflow defaults public scans to NVIDIA NIM and keeps private scans on the contracted provider"
	assert_file_contains "$workflow_file" 'if [ -z "$STRIX_MODEL_REQUESTED" ] && [ "$strix_model" = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b" ] && [ -z "${STRIX_NVIDIA_NIM_API_KEY:-}" ]' "strix workflow falls back to the contracted provider when the NVIDIA secret is absent"
	assert_file_contains "$workflow_file" 'STRIX_MODEL: ${{ steps.gate.outputs.strix_model }}' "strix workflow propagates the gate-selected fallback model to the scanner"
	assert_file_not_contains "$workflow_file" "secrets.STRIX_LLM ||" "strix workflow must not let the legacy STRIX_LLM secret override PR defaults"
	assert_file_contains "$workflow_file" "STRIX_LLM must select NVIDIA NIM Nemotron, GitHub Models openai/gpt-5 or newer, direct OpenAI GPT-5.4 or newer, OpenRouter openrouter/free, or an approved organization Vertex AI model" "strix workflow rejects unsupported model inputs"
	assert_file_contains "$workflow_file" "vertex_ai/gemini-3.1-pro-preview-customtools | vertex_ai/gemini-2.5-flash)" "strix workflow accepts only exact approved organization Vertex AI models"
	assert_file_contains "$workflow_file" 'STRIX_VERTEX_FALLBACK_MODELS: ""' "strix workflow disables silent Vertex fallbacks so timeout-class failures fail closed"
	assert_file_contains "$workflow_file" 'STRIX_FAIL_ON_PROVIDER_SIGNAL: "1"' "strix workflow fails closed on timeout, fatal, warning, denied, or provider failure signals"
	assert_file_contains "$workflow_file" 'NPM_CONFIG_IGNORE_SCRIPTS: "true"' "strix workflow disables npm lifecycle scripts for untrusted PR scan data"
	assert_file_contains "$workflow_file" 'PNPM_CONFIG_IGNORE_SCRIPTS: "true"' "strix workflow disables pnpm lifecycle scripts for untrusted PR scan data"
	assert_file_contains "$workflow_file" 'YARN_ENABLE_SCRIPTS: "false"' "strix workflow disables yarn lifecycle scripts for untrusted PR scan data"
	assert_file_not_contains "$workflow_file" "PYTHONWARNINGS:" "strix workflow must not expose warning-filter env names in GitHub logs"
	assert_file_contains "$workflow_file" "temporary scope with execute bits stripped" "strix workflow documents PR-head blobs as non-executable scan data"
	assert_file_contains "$workflow_file" "__PR_SCOPE__" "strix workflow uses explicit PR-scope target sentinel for PR evidence"
	assert_file_contains "$GATE_SCRIPT" 'child_env["NPM_CONFIG_IGNORE_SCRIPTS"] = "true"' "strix gate child process disables npm lifecycle scripts"
	assert_file_contains "$GATE_SCRIPT" 'child_env["PNPM_CONFIG_IGNORE_SCRIPTS"] = "true"' "strix gate child process disables pnpm lifecycle scripts"
	assert_file_contains "$GATE_SCRIPT" 'child_env["YARN_ENABLE_SCRIPTS"] = "false"' "strix gate child process disables yarn lifecycle scripts"
	assert_file_contains "$GATE_SCRIPT" 'child_env["PYTHONWARNINGS"] = "ignore:Pydantic serializer warnings:UserWarning:pydantic.main"' "strix gate child env narrowly filters the known third-party Pydantic serializer warning"
	assert_file_contains "$GATE_SCRIPT" '[[ "$normalized_changed_file" =~ ^backend/.+\.py$ ]]' "strix gate detects nested backend Python files for PR-scoped import context"
	assert_file_contains "$GATE_SCRIPT" '[[ "$normalized_changed_file" == scripts/ci/test_*.sh || "$normalized_changed_file" == scripts/ci/*_test.sh ]]' "strix gate excludes large CI test harness scripts from model scan input"
	assert_file_contains "$GATE_SCRIPT" "Materialized PR-head changed-file scope for Strix scan" "strix gate avoids copying the full PR head tree into privileged scan targets by default"
	assert_file_contains "$GATE_SCRIPT" "sanitize_known_strix_report_warnings" "strix gate sanitizes only known internal Strix report warnings"
	assert_file_contains "$GATE_SCRIPT" "vulnerability_file_reports_documented_opencode_env_api_key_reference" "strix gate fact-checks documented OpenCode env apiKey references before accepting secret-templating reports"
	assert_file_contains "$GATE_SCRIPT" "iter_report_logs" "strix gate enumerates report logs through a safe walker"
	assert_file_contains "$GATE_SCRIPT" "os.walk(root, topdown=True, followlinks=False)" "strix gate does not recurse into symlinked report directories"
	assert_file_not_contains "$GATE_SCRIPT" 'root.rglob("*.log")' "strix gate avoids recursive pathlib glob traversal for report logs"
	assert_file_contains "$GATE_SCRIPT" "has_strix_report_failure_signal" "strix gate fails closed on warning-class Strix report artifacts"
	assert_file_not_contains "$workflow_file" "ignore::UserWarning" "strix workflow must not blanket-suppress all UserWarning output"
	assert_file_contains "$GATE_SCRIPT" "vulnerability_file_reports_generic_github_actions_workflow_insecurity" "strix gate fact-checks generic GitHub Actions workflow security reports before accepting whole-file claims"
	assert_file_not_contains "$workflow_file" "vertex_ai/* | vertex_ai_beta/*" "strix workflow must not accept arbitrary Vertex models"
	assert_file_contains "$workflow_file" "provider_mode=openai_direct" "strix workflow requires direct OpenAI GPT-5 credentials"
	assert_file_contains "$workflow_file" "provider_mode=github_models" "strix workflow supports GitHub Models provider mode"
	assert_file_contains "$workflow_file" "provider_mode=openrouter" "strix workflow supports OpenRouter provider mode"
	assert_file_contains "$workflow_file" "provider_mode=nvidia_nim" "strix workflow supports NVIDIA NIM provider mode"
	assert_file_contains "$workflow_file" 'STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}' "strix workflow prefers the organization GitHub Models token secret and falls back to GITHUB_TOKEN"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'github_models' && (secrets.STRIX_GITHUB_MODELS_TOKEN || github.token)" "strix workflow keeps GitHub Models key routing in provider-scoped key material"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'openai_direct' && (secrets.STRIX_OPENAI_API_KEY || secrets.OPENAI_API_KEY)" "strix workflow keeps direct OpenAI key routing in provider-scoped key material"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'openrouter' && secrets.OPENROUTER_API_KEY" "strix workflow includes OpenRouter key routing in provider-scoped key material"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'nvidia_nim' && secrets.NVIDIA_NIM_API_KEY" "strix workflow includes NVIDIA NIM key routing in provider-scoped key material"
	assert_file_not_contains "$workflow_file" "secrets.LLM_API_KEY" "strix workflow must not expose generic LLM_API_KEY for Vertex scans"
	assert_file_contains "$workflow_file" "STRIX_GITHUB_MODELS_TOKEN is required for GitHub Models Strix scans" "strix workflow fails closed when GitHub Models credentials are absent"
	assert_file_contains "$workflow_file" "STRIX_OPENAI_API_KEY is required for Strix OpenAI Platform scans" "strix workflow fails closed when direct credentials are absent"
	assert_file_contains "$workflow_file" "OPENROUTER_API_KEY is required for Strix OpenRouter scans" "strix workflow fails closed when OpenRouter credentials are absent"
	assert_file_contains "$workflow_file" "NVIDIA_NIM_API_KEY is required for Strix NVIDIA NIM scans" "strix workflow fails closed when NVIDIA credentials are absent"
	assert_file_contains "$workflow_file" 'PROVIDER_MODE: ${{ steps.gate.outputs.provider_mode }}' "strix workflow passes provider mode through env"
	assert_file_not_contains "$workflow_file" '[ "${{ steps.gate.outputs.provider_mode }}" = "openai_direct" ]' "strix workflow does not interpolate provider mode inside shell condition"
	assert_file_contains "$workflow_file" "STRIX_REASONING_EFFORT: high" "strix workflow uses high reasoning effort when the selected provider/model supports it"
	assert_file_contains "$workflow_file" 'trimmed_openai_key="$(printf '"'"'%s'"'"' "$sanitized_openai_key" | sed '"'"'s/^[[:space:]]*//;s/[[:space:]]*$//'"'"')"' "strix workflow trims whitespace-only OpenAI keys before gate validation"
	assert_file_contains "$workflow_file" 'printf '"'"'%s'"'"' "$trimmed" > "$llm_api_key_file"' "strix workflow writes trimmed provider API keys into the trusted input file"
	assert_file_contains "$workflow_file" 'STRIX_LLM_DEFAULT_PROVIDER: ${{ steps.gate.outputs.provider_mode == '"'"'vertex_ai'"'"' && '"'"'vertex_ai'"'"' || steps.gate.outputs.provider_mode == '"'"'nvidia_nim'"'"' && '"'"'nvidia_nim'"'"' || '"'"'openai'"'"' }}' "strix workflow selects the correct default provider"
	assert_file_contains "$workflow_file" "Prepare GitHub Models API base" "strix workflow prepares the GitHub Models API base only for GitHub Models mode"
	assert_file_contains "$workflow_file" "https://models.github.ai/inference" "strix workflow routes GitHub Models scans to the inference endpoint"
	assert_file_contains "$workflow_file" "Prepare OpenRouter API base" "strix workflow prepares the OpenRouter API base when OpenRouter mode is selected"
	assert_file_contains "$workflow_file" "https://openrouter.ai/api/v1" "strix workflow routes OpenRouter scans to the OpenRouter API endpoint"
	assert_file_contains "$workflow_file" "https://integrate.api.nvidia.com/v1" "strix workflow routes NVIDIA NIM scans to the hosted endpoint"
	assert_file_contains "$workflow_file" "LLM_API_BASE_FILE" "strix workflow passes the GitHub Models API base through a trusted input file"
	assert_file_not_contains "$workflow_file" '${{ secrets.STRIX_OPENAI_API_KEY || github.token }}' "strix workflow must not use fallback-secret syntax for LLM API keys"
	assert_file_contains "$workflow_file" "openai-direct/gpt-5.6-luna" "strix workflow keeps a direct-OpenAI fallback on a tool-capable, Strix-recommended model without GPT-4.1 downgrade"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'openai_direct' && 'openai-direct/gpt-5.6-luna'" "strix workflow gives direct-OpenAI scans a same-provider fallback so transient errors degrade instead of skipping"
	assert_file_contains "$workflow_file" "steps.gate.outputs.provider_mode == 'nvidia_nim' && 'nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 openai-direct/gpt-5.6-luna'" "strix workflow gives NVIDIA NIM scans contracted fallbacks"
	assert_file_not_contains "$workflow_file" "STRIX_FALLBACK_MODELS: \${{ steps.gate.outputs.provider_mode == 'github_models' && 'github_models/openai/o3" "strix workflow fallback list must not depend on GitHub Models, which is in platform-wide retirement"
	assert_file_not_contains "$workflow_file" "- name: Prepare GitHub Models fallback credentials" "strix workflow does not define a GitHub Models fallback credential step (a compatibility comment for main's retired smoke needle is allowed)"
	assert_file_contains "$GATE_SCRIPT" "STRIX_GITHUB_MODELS_KEY_FILE" "strix gate reads the optional GitHub Models fallback key file"
	assert_file_contains "$GATE_SCRIPT" "STRIX_GITHUB_MODELS_API_BASE_FILE" "strix gate routes github_models fallback models through the GitHub Models endpoint"
	assert_file_contains "$workflow_file" "Prepare direct OpenAI fallback credentials" "strix workflow provisions direct OpenAI credentials for cross-provider fallbacks"
	assert_file_contains "$workflow_file" 'OPENAI_FALLBACK_API_KEY: ${{ secrets.STRIX_OPENAI_API_KEY || secrets.OPENAI_API_KEY }}' "strix workflow reads the established direct OpenAI secret only at the credential boundary"
	assert_file_contains "$workflow_file" "STRIX_OPENAI_FALLBACK_KEY_FILE" "strix workflow passes the direct OpenAI fallback key through a trusted file"
	assert_file_contains "$GATE_SCRIPT" "STRIX_OPENAI_FALLBACK_KEY_FILE" "strix gate reads the direct OpenAI fallback key from a trusted file"
	assert_file_not_contains "$workflow_file" 'github_models/deepseek/deepseek-r1-0528 | github_models/deepseek/deepseek-v3-0324)' "strix workflow keeps DeepSeek GitHub Models restricted to fallback-only routing"
	assert_file_contains "$workflow_file" '${strix_model#github_models/}' "strix workflow strips manual github_models routing prefix for OpenAI GPT model names before passing model names to LiteLLM"
	assert_file_contains "$workflow_file" "openai_direct/%s" "strix workflow keeps manual direct OpenAI scans distinct from GitHub Models openai/gpt-* routing"
	assert_file_not_contains "$workflow_file" "openai/gpt-4.1" "strix workflow must not fall back to GPT-4.1 or weaker review evidence"
	assert_file_not_contains "$workflow_file" "openai/gpt-5-*" "strix workflow must not accept older GPT-5 variants when GPT-5.4 is required"
	assert_file_contains "$workflow_file" "openai/gpt-5-mini* | openai/gpt-5-nano*" "strix workflow rejects mini and nano GPT-5 variants for security evidence"
	assert_file_contains "$workflow_file" "openai/gpt-5*" "strix workflow accepts GitHub Models OpenAI GPT-5 model prefixes"
	assert_file_not_contains "$workflow_file" "github/gpt-4o" "strix workflow must not default to an unsupported GitHub Models alias"
	assert_file_not_contains "$workflow_file" "gemini/gemini-pro-3.1-preview" "strix workflow must not default to Gemini API when GitHub Models is required"
	assert_file_not_contains "$workflow_file" "if-no-files-found: warn" "strix workflow must not downgrade missing security artifacts to warnings"
	if grep -Eq '^[[:space:]]+pull_request:[[:space:]]*$' "$workflow_file"; then
		record_failure "strix workflow must not expose secrets on pull_request events"
	fi
	assert_file_not_contains "$workflow_file" "github.event_name == 'pull_request'" "strix workflow should not retain pull_request-only expressions"
}

assert_strix_gpt54_model_guard_semantics() {
	local model="$1"
	case "$model" in
	openai/gpt-5-mini* | openai/gpt-5-nano* | \
	openai/openai/gpt-5-mini* | openai/openai/gpt-5-nano* | \
	github_models/openai/gpt-5-mini* | github_models/openai/gpt-5-nano*)
		return 1
		;;
	openai/gpt-5* | openai/gpt-[6-9]* | openai/gpt-[1-9][0-9]* | \
	openai/openai/gpt-5* | openai/openai/gpt-[6-9]* | openai/openai/gpt-[1-9][0-9]* | \
	github_models/openai/gpt-5* | github_models/openai/gpt-[6-9]* | github_models/openai/gpt-[1-9][0-9]* | \
	gpt-5.[4-9]* | gpt-5.[1-9][0-9]* | gpt-[6-9]* | gpt-[1-9][0-9]* | \
	openai-direct/gpt-5.[4-9]* | openai-direct/gpt-5.[1-9][0-9]* | openai-direct/gpt-[6-9]* | openai-direct/gpt-[1-9][0-9]* | \
	openrouter/free | openrouter/openrouter/free | \
	vertex_ai/gemini-3.1-pro-preview-customtools | vertex_ai/gemini-2.5-flash)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

assert_strix_gpt54_model_guard_cases() {
	if ! assert_strix_gpt54_model_guard_semantics "openai/gpt-5"; then
		record_failure "strix guard must accept GitHub Models openai/gpt-5"
	fi
	if assert_strix_gpt54_model_guard_semantics "openai/gpt-5-mini"; then
		record_failure "strix guard must reject GitHub Models openai/gpt-5-mini"
	fi
	if assert_strix_gpt54_model_guard_semantics "github_models/openai/gpt-5-nano"; then
		record_failure "strix guard must reject manual GitHub Models openai/gpt-5-nano"
	fi
	if assert_strix_gpt54_model_guard_semantics "github_models/openai/gpt-4.1"; then
		record_failure "strix guard must reject weaker GitHub Models gpt-4.1"
	fi
	if assert_strix_gpt54_model_guard_semantics "gpt-5"; then
		record_failure "strix GPT-5.4 guard must reject plain gpt-5"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "gpt-5.4"; then
		record_failure "strix GPT-5.4 guard must accept direct OpenAI gpt-5.4"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "openai-direct/gpt-5.4"; then
		record_failure "strix GPT-5.4 guard must accept direct OpenAI openai-direct/gpt-5.4"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "openrouter/free"; then
		record_failure "strix guard must accept OpenRouter openrouter/free"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "openai/gpt-5.4"; then
		record_failure "strix guard must accept GitHub Models openai/gpt-5.4"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "openai/openai/gpt-5"; then
		record_failure "strix guard must accept GitHub Models openai/openai/gpt-5"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "openai/openai/gpt-5.4"; then
		record_failure "strix guard must accept GitHub Models openai/openai/gpt-5.4"
	fi
	if assert_strix_gpt54_model_guard_semantics "openai/deepseek/deepseek-r1-0528"; then
		record_failure "strix guard must reject direct DeepSeek R1 primary selection"
	fi
	if assert_strix_gpt54_model_guard_semantics "openai/deepseek/deepseek-v3-0324"; then
		record_failure "strix guard must reject direct DeepSeek V3 primary selection"
	fi
	if assert_strix_gpt54_model_guard_semantics "github_models/deepseek/deepseek-r1-0528"; then
		record_failure "strix guard must reject manual GitHub Models DeepSeek R1 primary selection"
	fi
	if assert_strix_gpt54_model_guard_semantics "github_models/deepseek/deepseek-v3-0324"; then
		record_failure "strix guard must reject manual GitHub Models DeepSeek V3 primary selection"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "vertex_ai/gemini-3.1-pro-preview-customtools"; then
		record_failure "strix guard must accept the organization-approved Vertex preview model"
	fi
	if ! assert_strix_gpt54_model_guard_semantics "vertex_ai/gemini-2.5-flash"; then
		record_failure "strix guard must accept the approved organization Vertex AI operational model"
	fi
	if assert_strix_gpt54_model_guard_semantics "vertex_ai/gemini-2.5-pro"; then
		record_failure "strix guard must reject arbitrary Vertex models"
	fi
}

assert_strix_gate_target_scope_separated() {
	assert_file_not_contains "$GATE_SCRIPT" "or generated PR scope directories" "strix gate keeps user target validation separate from internal PR scopes"
	assert_file_contains "$GATE_SCRIPT" "TARGET_PATH_IS_INTERNAL_PR_SCOPE" "strix gate marks internally generated PR scan scopes explicitly"
	assert_file_contains "$GATE_SCRIPT" "PR_SCOPE_TARGET_SENTINEL=\"__PR_SCOPE__\"" "strix gate supports an explicit PR-scope target sentinel"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false diff --name-only "$base_sha" "$head_sha"' "strix gate emits literal UTF-8 paths in explicit manual PR-scope diffs"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false diff --name-only "$base_sha...$head_sha"' "strix gate emits literal UTF-8 paths in merge-base PR-scope diffs"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false diff --name-only "$base_sha..$head_sha"' "strix gate emits literal UTF-8 paths in direct fallback PR-scope diffs"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false ls-tree "$head_sha" -- "$relative_path"' "strix gate emits literal UTF-8 paths when validating a PR-head blob"
	assert_file_contains "$GATE_SCRIPT" 'git -c core.quotepath=false ls-tree -r --full-tree "$head_sha"' "strix gate emits literal UTF-8 paths when materializing a PR-head tree"
}

assert_changed_file_membership_uses_cached_normalized_paths() {
	assert_file_contains "$GATE_SCRIPT" "NORMALIZED_CHANGED_FILES=()" "strix gate caches normalized PR changed paths"
	assert_file_contains "$GATE_SCRIPT" 'NORMALIZED_CHANGED_FILES+=("$normalized_changed_file")' "strix gate populates cached normalized PR changed paths"
	assert_file_contains "$GATE_SCRIPT" "for normalized_changed_file in \"\${NORMALIZED_CHANGED_FILES[@]}\"" "strix gate uses cached normalized paths for membership checks"
}

assert_absent_endpoint_search_uses_canonical_target_path() {
	assert_file_contains "$GATE_SCRIPT" 'resolved_target_root="$(resolve_current_target_path "$TARGET_PATH" 2>/dev/null)"' "absent-endpoint search resolves canonical target root"
	assert_file_contains "$GATE_SCRIPT" 'candidate="${resolved_target_root%/}/$dir_entry"' "absent-endpoint search uses canonical target root"
	assert_file_not_contains "$GATE_SCRIPT" 'candidate="${TARGET_PATH%/}/$dir_entry"' "absent-endpoint search avoids relative target path roots"
}

assert_strix_llm_file_read_is_literal_data() {
	assert_file_contains "$GATE_SCRIPT" 'STRIX_LLM_CONTENT="$(cat -- "$STRIX_LLM_FILE")"' "strix gate reads model file content as data before trimming"
	assert_file_contains "$GATE_SCRIPT" 'STRIX_LLM="$(trim_whitespace "$STRIX_LLM_CONTENT")"' "strix gate trims model file content without nested command substitution"
	assert_file_not_contains "$GATE_SCRIPT" 'STRIX_LLM="$(trim_whitespace "$(cat -- "$STRIX_LLM_FILE")")"' "strix gate avoids nested command substitution for model file content"
}

assert_strix_child_target_uses_constant_argument() {
	assert_file_contains "$GATE_SCRIPT" 'command = [resolved_strix_bin, "-n", "-t", str(target_cwd), "--scan-mode", scan_mode]' "strix gate passes the canonical target argument to the child process"
	assert_file_contains "$GATE_SCRIPT" 'cwd=str(scan_working_dir)' "strix gate runs the child process outside the scan target"
	assert_file_contains "$GATE_SCRIPT" 'make_pull_request_scope_dir()' "strix gate creates PR scopes under its private runtime directory"
	assert_file_contains "$GATE_SCRIPT" 'scope_parent="$STRIX_RUNTIME_DIR/pr-scopes"' "strix gate keeps PR scopes inside the private runtime directory"
	assert_file_not_contains "$GATE_SCRIPT" 'command = [resolved_strix_bin, "-n", "-t", ".", "--scan-mode", scan_mode]' "strix gate must not rely on the child cwd as its scan target"
	assert_file_not_contains "$GATE_SCRIPT" 'cwd=str(target_cwd)' "strix gate must not run the child process inside the scan target"
}

assert_strix_severity_markers_require_identifier_boundary() {
	assert_file_contains "$GATE_SCRIPT" '[[ "${line^^}" =~ (^|[^A-Za-z0-9_])SEVERITY' "strix severity extraction rejects identifier suffixes"
	assert_file_contains "$GATE_SCRIPT" "grep -Ei '(^|[^A-Za-z0-9_])severity[[:space:][:punct:]]*:'" "strix severity extraction prefilter rejects identifier suffixes"
	local marker_count
	marker_count="$(grep -Fc "grep -Eiq '(^|[^A-Za-z0-9_])severity[[:space:][:punct:]]*:'" "$GATE_SCRIPT" || true)"
	if [ "$marker_count" -lt 2 ]; then
		record_failure "strix structured and log severity marker checks both reject identifier suffixes (found ${marker_count}, expected at least 2)"
	fi
}

assert_opencode_review_uses_codegraph_and_gpt5_fallback() {
	local bootstrap_file="$REPO_ROOT/.github/workflows/opencode-review.yml"
	local workflow_file="$REPO_ROOT/.github/workflows/opencode-review-dispatch.yml"
	local comment_helpers_file="$REPO_ROOT/scripts/ci/opencode_review_comment_helpers.sh"
	local opencode_config="$REPO_ROOT/opencode.jsonc"

	assert_file_contains "$bootstrap_file" "pull_request_target:" "opencode required workflow loads its metadata-only bootstrap from the protected base ref"
	assert_file_contains "$bootstrap_file" "types: [opened, synchronize, reopened, ready_for_review, closed]" "opencode required workflow reacts to current PR head changes and closed-PR cleanup"
	assert_file_contains "$bootstrap_file" "required-workflow-bootstrap:" "opencode required workflow materializes at least one job for pull_request ruleset runs"
	assert_file_contains "$bootstrap_file" "Required OpenCode workflow materialized without checking out or" "opencode required workflow bootstrap documents its data-only trust boundary"
	assert_file_contains "$bootstrap_file" "coverage-source-tree:" "opencode required workflow preserves the stable coverage-source-tree branch-protection context"
	assert_file_contains "$bootstrap_file" "coverage-evidence:" "opencode required workflow preserves the stable coverage-evidence branch-protection context"
	assert_file_contains "$bootstrap_file" "name: opencode-review" "opencode required workflow preserves the stable opencode-review branch-protection context"
	assert_file_contains "$bootstrap_file" "authenticated default-branch OpenCode review dispatch" "opencode required workflow delegates real review execution to the protected dispatch path"
	assert_file_not_contains "$bootstrap_file" "repository_dispatch:" "opencode required workflow does not mix privileged dispatch execution with pull_request_target"
	assert_file_not_contains "$bootstrap_file" "actions/checkout" "opencode required workflow never checks out pull-request content"
	assert_file_not_contains "$bootstrap_file" '${{ secrets.' "opencode required workflow never binds repository secrets"
	assert_file_contains "$workflow_file" "repository_dispatch:" "opencode review supports default-branch scheduler current-head dispatch"
	assert_file_contains "$workflow_file" "types: [opencode-review]" "opencode repository dispatch accepts only its dedicated event type"
	assert_file_not_contains "$workflow_file" "pull_request_target:" "opencode privileged review is isolated from pull_request_target"
	assert_file_not_contains "$workflow_file" "workflow_dispatch:" "privileged opencode retries cannot load a caller-selected workflow ref"
	if grep -Eq '^[[:space:]]+pull_request:[[:space:]]*$' "$workflow_file"; then
		record_failure "opencode review workflow must not expose privileged tokens through a PR-controlled workflow definition"
	fi
	assert_file_not_contains "$workflow_file" "Wait for trusted OpenCode approval review" "opencode pull_request bridge was removed to avoid duplicate required-check resource use"
	assert_file_not_contains "$workflow_file" "Trusted OpenCode requested changes for head" "opencode pull_request bridge no longer reconsumes stale trusted review state"
	assert_file_not_contains "$workflow_file" "github.event.pull_request.number == 240" "opencode review workflow must not hard-code repository-specific PR bypasses"
	if awk '/^  required-workflow-bootstrap:$/,/^[^ ]/' "$bootstrap_file" | grep -q '^[[:space:]]*if:'; then
		record_failure "opencode required workflow bootstrap must not depend on required-workflow event payload fields"
	fi
	assert_file_contains "$workflow_file" 'github.event.client_payload.target_repository || github.repository' "opencode review scopes concurrency by target repository"
	assert_file_contains "$workflow_file" "format('pr-{0}', github.event.client_payload.pr_number)" "opencode review scopes repository_dispatch concurrency by current PR"
	assert_file_not_contains "$workflow_file" "format('pr-{0}-{1}'" "opencode review does not keep stale head-specific concurrency groups"
	assert_file_contains "$workflow_file" "github.event.client_payload.pr_number && format('pr-{0}', github.event.client_payload.pr_number)" "opencode review retains a manual PR fallback group when no head SHA is provided"
	assert_file_contains "$workflow_file" 'cancel-in-progress: true' "opencode review cancels stale in-progress review attempts when a newer PR event arrives"
	assert_file_contains "$workflow_file" "Materialize pull request merge tree for coverage measurement" "opencode pull_request coverage execution materializes the exact base/head merge tree"
	assert_file_contains "$workflow_file" "stale OpenCode run: event head=" "opencode review side effects are skipped for stale heads"
	assert_file_not_contains "$workflow_file" "github.event.pull_request.head.repo.full_name == github.event.pull_request.base.repo.full_name" "opencode never treats a same-repository pull_request_target head as authorization to execute PR-controlled code"
	assert_file_not_contains "$workflow_file" "github.event.pull_request.head.repo.full_name == github.repository" "opencode required workflow must not compare PR head repo to the central workflow source repository"
	assert_file_contains "$workflow_file" 'DISPATCH_ACTOR: ${{ github.triggering_actor }}' "opencode repository dispatch binds authorization to the current run initiator"
	assert_file_not_contains "$workflow_file" 'DISPATCH_ACTOR: ${{ github.actor }}' "opencode repository dispatch rejects reruns initiated by a different actor"
	assert_file_contains "$workflow_file" "DISPATCH_SENDER: \${{ github.event.sender.login || '' }}" "opencode repository dispatch independently binds the sender identity"
	assert_file_contains "$workflow_file" 'ALLOWED_DISPATCH_ACTOR: ${{ vars.OPENCODE_REPOSITORY_DISPATCH_ACTOR }}' "opencode repository dispatch uses the protected scheduler identity"
	assert_file_contains "$workflow_file" 'ALLOWED_DISPATCH_TARGETS: ${{ vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS }}' "opencode repository dispatch uses an exact target repository allowlist"
	assert_file_contains "$workflow_file" "repository_dispatch authorization rejected actor=" "opencode repository dispatch fails visibly for an unauthorized actor"
	assert_file_contains "$workflow_file" "repository_dispatch authorization rejected target=" "opencode repository dispatch fails visibly for a disallowed target"
	assert_file_contains "$workflow_file" '&& github.event_name == '\''repository_dispatch'\''' "opencode coverage and review execution require an authorized default-branch dispatch"
	assert_file_contains "$workflow_file" "needs.coverage-evidence.result != 'cancelled'" "opencode review does not enqueue stale side-effect jobs after coverage evidence cancellation"
	assert_file_contains "$workflow_file" "opencode-review-target:" "opencode trusted review job owns the required check surface"
	assert_file_contains "$workflow_file" "Initialize CodeGraph index for OpenCode" "opencode review workflow initializes CodeGraph before review"
	assert_file_contains "$workflow_file" "Validate pull request head repository trust" "opencode privileged review validates the live head repository before token exchange and PR-head tooling"
	assert_file_contains "$workflow_file" "metadata changed before OIDC" "opencode privileged review fails closed for repository-dispatched fork or stale heads with a visible reason"
	assert_file_contains "$workflow_file" 'EXPECTED_IS_PRIVATE: ${{ needs.validate-pr-metadata.outputs.is_private }}' "opencode privileged review carries the validated privacy state into its final trust check"
	assert_file_contains "$workflow_file" '[ "$live_is_private" != "$EXPECTED_IS_PRIVATE" ]' "opencode privileged review fails closed when a public repository becomes private before model execution"
	assert_file_contains "$workflow_file" "actions: read" "opencode review workflow can read failed Actions logs without Actions write scope"
	assert_file_contains "$workflow_file" "checks: read" "opencode review workflow can read failed check-run annotations for line-specific findings"
	assert_file_contains "$workflow_file" "contents: read" "opencode review workflow uses read-only repository contents permission"
	assert_file_not_contains "$workflow_file" "contents: write" "opencode review workflow does not need repository contents write scope"
	assert_file_contains "$workflow_file" "pull-requests: write" "opencode review workflow may use github-actions[bot] for same-repository review-thread, update-branch, auto-merge, and merge follow-up"
	assert_file_contains "$workflow_file" "issues: write" "opencode review workflow can publish or update overview comments through the job token"
	assert_file_contains "$workflow_file" "statuses: write" "opencode review workflow can read status contexts and publish the repository_dispatch status evidence it owns"
	assert_file_contains "$workflow_file" "Prepare bounded OpenCode review evidence" "opencode review workflow prepares bounded local evidence instead of oversized GitHub prompt data"
	assert_file_contains "$workflow_file" "emit_file_prefix" "opencode review prompt evidence is byte-capped before GitHub Models requests"
	assert_file_contains "$workflow_file" "bounded-review-evidence.md" "opencode review prompt reads bounded evidence from the isolated workspace instead of inlining it"
	assert_file_not_contains "$workflow_file" '$(cat "$OPENCODE_REVIEW_WORKDIR/bounded-review-evidence-excerpt.md"' "opencode review prompt must not inline evidence excerpts into small-context models"
	assert_file_contains "$workflow_file" "Prepare isolated OpenCode review workspace" "opencode review workflow isolates from the large project AGENTS.md"
	assert_file_contains "$workflow_file" 'cd "$OPENCODE_REVIEW_WORKDIR"' "opencode review runs from the isolated OpenCode workspace"
	assert_file_contains "$workflow_file" "failed-check-evidence.md" "opencode review copies full failed-check evidence into the isolated workspace"
	assert_file_contains "$workflow_file" "Resolve trusted OpenCode source ref" "opencode required workflow resolves the central trusted source ref"
	assert_file_contains "$workflow_file" "workflow_ref" "opencode required workflow can reuse the required-workflow source ref"
	assert_file_contains "$workflow_file" "workflow_sha" "opencode trusted source ref prefers the immutable workflow commit when available"
	assert_file_not_contains "$workflow_file" "INPUT_CANONICAL_REF" "opencode trusted source checkout must not be controlled by repository_dispatch input"
	assert_file_not_contains "$workflow_file" "canonical_ref:" "opencode no longer exposes a checkout-ref override input"
	assert_file_contains "$workflow_file" "Trusted OpenCode workflow ref resolved to an invalid value" "opencode trusted source ref is validated before checkout"
	assert_file_contains "$workflow_file" "Checkout trusted OpenCode review workflow" "opencode review checks out central trusted workflow scripts before processing PR data"
	assert_file_contains "$workflow_file" "Materialize trusted OpenCode coverage contract without a repository token" "opencode coverage job uses central trusted coverage tooling without exposing a contents token"
	assert_file_contains "$workflow_file" 'R_LIBS_USER="/work/.opencode-r-library"' "opencode R coverage isolates the package library inside the untrusted worktree"
	assert_file_not_contains "$workflow_file" 'install.packages(' "opencode R coverage never installs PR-selected mutable packages"
	assert_file_contains "$workflow_file" "libcurl4-openssl-dev libssl-dev libxml2-dev" "opencode R coverage installs system headers required by covr dependencies"
	assert_file_contains "$workflow_file" "r-cran-covr" "opencode R coverage uses the signed distribution covr package instead of mutable CRAN resolution"
	assert_file_contains "$workflow_file" "r-cran-testthat" "opencode R coverage uses the signed distribution testthat package instead of mutable CRAN resolution"
	assert_file_contains "$workflow_file" "R package testthat suite" "opencode R package coverage requires package testthat evidence"
	assert_file_contains "$workflow_file" 'description_snapshot="$(mktemp "$RUNNER_TEMP/r-description.XXXXXX")"' "opencode R coverage snapshots DESCRIPTION before untrusted tests run"
	assert_file_contains "$workflow_file" 'install -m 0444 -- DESCRIPTION "$description_snapshot"' "opencode R coverage keeps the DESCRIPTION snapshot root-owned and immutable"
	assert_file_contains "$workflow_file" '--description "$description_snapshot"' "opencode R package coverage only defers missing dependencies from the trusted DESCRIPTION snapshot"
	assert_file_contains "$workflow_file" "r_coverage_peer_gate.py" "opencode R package coverage classifies bounded package-load-only failures with trusted code"
	assert_file_contains "$workflow_file" "- R test evidence: deferred package-load failures require a successful current-head peer R CMD check" "opencode R package coverage records explicit peer-check deferral evidence"
	assert_file_contains "$workflow_file" "require_r_cmd_check_for_deferred_coverage" "opencode approval verifies deferred R evidence against current-head peer checks"
	assert_file_contains "$workflow_file" "WAITING_FOR_R_CMD_CHECK" "opencode approval fails closed when deferred R coverage lacks successful peer evidence"
	assert_file_not_contains "$workflow_file" 'if (!is.na(pkg) && !requireNamespace(pkg, quietly = TRUE))' "opencode R coverage does not skip the entire test suite merely because the source package is not preinstalled"
	assert_file_contains "$workflow_file" "covr package_coverage unavailable after package tests; treating missing-line report as advisory." "opencode R package coverage does not block on covr installation reproduction after tests pass"
	assert_file_contains "$workflow_file" "signed distribution coverage packages unavailable" "opencode R coverage verifies distribution-provided covr/testthat are loadable"
	assert_file_contains "$workflow_file" "repository: ContextualWisdomLab/.github" "opencode required workflow checks out the central source repository"
	assert_file_contains "$workflow_file" 'ref: ${{ steps.trusted_source.outputs.ref }}' "opencode required workflow checks out the validated trusted-source output"
	assert_file_not_contains "$workflow_file" 'ref: ${{ github.workflow_sha }}' "opencode trusted checkout never bypasses the validated ref output"
	assert_file_contains "$workflow_file" "target_repository:" "opencode repository_dispatch can target a repository whose PR does not inherit required workflows"
	assert_file_contains "$workflow_file" "Materialize pull request merge tree for coverage measurement" "opencode coverage measures the PR merge tree instead of exposing secrets to untrusted checkout actions"
	assert_file_contains "$workflow_file" 'TARGET_REPOSITORY: ${{ needs.validate-pr-metadata.outputs.target_repository }}' "opencode coverage fetches exact validated base/head commits from the target repository"
	assert_file_contains "$workflow_file" "Exchange OpenCode app token for target repository review reads" "opencode review can read private target repositories through the OpenCode app token before materializing review data"
	assert_file_contains "$workflow_file" 'GH_TOKEN: ${{ steps.review_read_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || github.token }}' "opencode materialization prefers the OpenCode app token for private target repository reads"
	assert_file_contains "$workflow_file" '[ "${GH_REPOSITORY:-}" != "${GITHUB_REPOSITORY:-}" ]' "opencode approval uses the app token for target-repository check lookup"
	assert_file_not_contains "$workflow_file" "LEGACY_GITHUB_ACTIONS_REVIEW_TOKEN" "dispatch-only opencode review does not retain an unreachable pull-request-target token bridge"
	assert_file_not_contains "$workflow_file" "legacy_github_actions_opencode_blocking_review_ids" "dispatch-only opencode review does not retain stale github-actions bridge lookup code"
	assert_file_not_contains "$workflow_file" "publish_legacy_github_actions_approval_bridge" "dispatch-only opencode review does not retain stale github-actions bridge publication code"
	assert_file_contains "$workflow_file" 'COVERAGE_SOURCE_WORKDIR: ${{ runner.temp }}/pr-head' "opencode coverage keeps PR-head data outside the trusted workflow root"
	assert_file_contains "$workflow_file" 'target=/trusted,readonly' "opencode coverage mounts central scripts read-only in the isolated sandbox"
	assert_file_contains "$workflow_file" 'target=/work' "opencode coverage mounts only the PR worktree writable in the isolated sandbox"
	assert_file_contains "$workflow_file" '--pids-limit 2048' "opencode coverage isolates pull-request process ancestry and bounds process use"
	assert_file_contains "$workflow_file" '--cap-drop ALL' "opencode coverage drops container capabilities before executing pull-request code"
	assert_file_contains "$workflow_file" 'setpriv' "opencode coverage executes pull-request commands under the non-root source owner"
	assert_file_contains "$workflow_file" "python3 -I -c 'import coverage, interrogate, pytest, pytest_cov" "opencode trusted tool verification ignores PR-controlled Python module shadowing"
	assert_file_contains "$workflow_file" 'python3 -I "$GITHUB_WORKSPACE/scripts/ci/sanitize_github_output_summary.py"' "opencode trusted output sanitizer runs in isolated Python mode"
	assert_file_contains "$workflow_file" 'CARGO_HOME=/work/.opencode-sandbox-home/.cargo' "opencode Rust tooling stays in the low-privilege sandbox home"
	assert_file_contains "$REPO_ROOT/scripts/ci/pr_review_merge_scheduler.py" '"pr_head_ref":' "central scheduler repository_dispatch carries the PR head branch required by current-head code-scanning verification"
	assert_file_contains "$workflow_file" 'github.event.client_payload.pr_head_ref' "opencode review wires the PR head branch into current-head code-scanning verification"
	assert_file_contains "$workflow_file" 'statuses: write' "opencode repository_dispatch can publish GitHub Actions sourced current-head status evidence"
	assert_file_contains "$workflow_file" "Publish repository_dispatch OpenCode status" "opencode repository_dispatch publishes same-head status evidence for required checks"
	assert_file_contains "$workflow_file" 'context="opencode-review"' "opencode repository_dispatch status uses the required OpenCode context"
	assert_file_contains "$workflow_file" 'repos/${GH_REPOSITORY}/statuses/${PR_HEAD_SHA}' "opencode repository_dispatch status targets the reviewed PR head"
	assert_file_contains "$workflow_file" 'status publication failed because pr_head_sha was empty' "opencode repository_dispatch status fails closed when current-head identity is unavailable"
	assert_file_not_contains "$workflow_file" "actions/cache@" "opencode coverage does not restore PR-writable static R caches"
	assert_file_not_contains "$workflow_file" 'ref: ${{ github.event.client_payload.pr_head_sha }}' "opencode review must not checkout PR head into the trusted workflow workspace"
	assert_file_contains "$workflow_file" "Materialize pull request head for OpenCode review data" "opencode review materializes PR-head source as read-only review data"
	assert_file_contains "$workflow_file" 'git remote add pr-source "$GITHUB_SERVER_URL/$GH_REPOSITORY.git"' "opencode review fetches target PR commits through a separate PR-source remote"
	assert_file_contains "$workflow_file" 'refs/pull/${PR_NUMBER}/head' "opencode review can fetch fork PR heads without local workflow copies"
	assert_file_contains "$workflow_file" 'git worktree add --detach "$OPENCODE_SOURCE_WORKDIR" "$PR_HEAD_SHA"' "opencode review materializes the PR head without actions/checkout credentials"
	assert_file_contains "$workflow_file" 'cd "$OPENCODE_SOURCE_WORKDIR"' "opencode CodeGraph indexing runs against the PR-head source worktree"
	assert_file_contains "$workflow_file" 'PR_MERGE_BASE="$(git -C "$OPENCODE_SOURCE_WORKDIR" merge-base "$PR_BASE_SHA" "$PR_HEAD_SHA")"' "opencode review evidence diffs use the PR-head worktree merge base"
	assert_file_contains "$workflow_file" 'git -C "$OPENCODE_SOURCE_WORKDIR" diff' "opencode review builds changed-file evidence from the PR-head worktree"
	assert_file_not_contains "$workflow_file" 'ref: ${{ github.event.pull_request.base.sha' "opencode trusted checkout avoids dynamic pull_request refs that Scorecard flags"
	assert_file_not_contains "$workflow_file" 'ref: ${{ github.event.pull_request.head.sha || github.event.client_payload.pr_head_sha || github.sha }}' "opencode review must not checkout PR head into the trusted workflow workspace"
	assert_file_not_contains "$workflow_file" 'secrets.GITHUB_TOKEN' "opencode review uses github.token instead of a nonexistent GITHUB_TOKEN secret"
	assert_file_contains "$workflow_file" 'STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}' "opencode review uses the organization GitHub Models token secret with GITHUB_TOKEN fallback"
	assert_file_not_contains "$workflow_file" 'GITHUB_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}' "opencode review does not expose GitHub credentials through the generic model environment"
	assert_file_contains "$workflow_file" 'is_private: ${{ steps.validate.outputs.is_private }}' "opencode review carries validated repository privacy into model routing"
	assert_file_contains "$workflow_file" '"opencode-free"' "opencode review enables its anonymous Zen free provider"
	assert_file_contains "$workflow_file" '"baseURL": "https://opencode.ai/zen/v1"' "opencode review routes the free provider through the official Zen endpoint"
	assert_file_contains "$workflow_file" '"nvidia-nim"' "opencode review enables its NVIDIA NIM provider"
	assert_file_contains "$workflow_file" '"baseURL": "https://integrate.api.nvidia.com/v1"' "opencode review routes NVIDIA NIM through its official hosted endpoint"
	assert_file_contains "$workflow_file" '"apiKey": "{env:NVIDIA_API_KEY}"' "opencode review resolves normalized NVIDIA NIM credentials at runtime"
	assert_file_contains "$workflow_file" 'NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}' "opencode review exposes NVIDIA NIM credentials only to the model runtime"
	assert_file_contains "$workflow_file" '"north-mini-code-free"' "opencode review declares the current Zen coding model"
	assert_file_contains "$workflow_file" "needs.validate-pr-metadata.outputs.is_private == 'false'" "opencode review limits data-retaining free models to public repositories"
	assert_file_matches "$workflow_file" 'uses:[[:space:]]+actions/checkout@[0-9a-fA-F]{40}([[:space:]]|$)' "opencode review workflow pins checkout to a full commit SHA"
	assert_workflow_uses_are_sha_pinned "$workflow_file" "opencode review workflow"
	assert_file_contains "$workflow_file" "scripts/ci/codegraph-package/package-lock.json" "opencode review workflow installs CodeGraph from the committed lockfile"
	if ! jq -e '
		.packages["node_modules/@colbymchenry/codegraph"]
		| .version == "1.4.1" and (.integrity | startswith("sha512-"))
	' "$REPO_ROOT/scripts/ci/codegraph-package/package-lock.json" >/dev/null; then
		record_failure "opencode review CodeGraph lockfile pins version 1.4.1 with integrity"
	fi
	if ! jq -e '
		.packages["node_modules/picomatch"]
		| .version == "4.0.4" and (.integrity | startswith("sha512-"))
	' "$REPO_ROOT/scripts/ci/codegraph-package/package-lock.json" >/dev/null; then
		record_failure "opencode review CodeGraph lockfile pins patched picomatch 4.0.4 with integrity"
	fi
	assert_file_contains "$workflow_file" "Hardened CodeGraph platform bundle" "opencode review replaces the vulnerable nested CodeGraph picomatch before execution"
	assert_file_contains "$workflow_file" 'locked_version" != "4.0.4"' "opencode review verifies both nested installed and locked picomatch evidence"
	assert_file_contains "$workflow_file" '"$CODEGRAPH_BIN" explore' "opencode review precomputes structural evidence outside the model process"
	assert_file_contains "$workflow_file" '"$CODEGRAPH_BIN" --version' "opencode review logs the exact trusted CodeGraph version"
	assert_file_contains "$workflow_file" 'cat "$codegraph_status" >&2' "opencode review exposes CodeGraph status failures in the job log"
	assert_file_contains "$workflow_file" 'cat "$codegraph_raw" >&2' "opencode review exposes CodeGraph exploration failures in the job log"
	assert_file_not_contains "$workflow_file" "serve --mcp" "opencode review must not fetch or launch CodeGraph again for MCP"
	assert_file_not_contains "$workflow_file" "https://mcp.deepwiki.com/mcp" "opencode review does not expose remote MCP to the model"
	assert_file_not_contains "$workflow_file" "@upstash/context7-mcp@3.1.0" "opencode review does not install Context7 at runtime"
	assert_file_not_contains "$workflow_file" "@guhcostan/web-search-mcp@1.0.5" "opencode review does not install web-search MCP at runtime"
	assert_file_contains "$workflow_file" 'NPM_CONFIG_IGNORE_SCRIPTS: "true"' "opencode review workflow disables npm lifecycle scripts for local MCP packages"
	assert_file_contains "$workflow_file" "init -i" "opencode review workflow builds the CodeGraph index"
	assert_file_contains "$workflow_file" "precomputed CodeGraph" "opencode review prompt requires precomputed CodeGraph evidence"
	assert_file_contains "$workflow_file" "general-purpose and meticulous" "opencode review prompt requires a general-purpose meticulous review"
	assert_file_contains "$workflow_file" "every MCP server are denied" "opencode review prompt documents the MCP isolation boundary"
	assert_file_contains "$workflow_file" "Do not rely on model memory for user-claimed concepts" "opencode review prompt forces concept checks through evidence sources"
	assert_file_contains "$workflow_file" "Docs-only changes still require trusted CodeGraph or source evidence" "opencode review does not approve docs-only changes without source-backed evidence"
	assert_file_contains "$workflow_file" "changed documentation contradicts current code" "opencode review requires code-doc mismatch findings"
	assert_file_contains "$workflow_file" "code-to-documentation consistency" "opencode review checks code and docs consistency"
	assert_file_contains "$workflow_file" "documentation-to-code consistency" "opencode review checks docs and code consistency"
	assert_file_contains "$workflow_file" "Implementation completeness is mandatory" "opencode review checks for unimplemented runtime code before approving"
	assert_file_contains "$workflow_file" "Distinguish typing.Protocol, abc abstractmethod" "opencode review separates type/interface placeholders from executable implementation gaps"
	assert_file_contains "$workflow_file" "Protocol/abstract/type-declaration placeholders from executable implementation gaps" "opencode exact gate phrase preserves implementation-completeness review guidance"
	assert_file_contains "$workflow_file" "Recent deployment evidence" "opencode review evidence includes deployment records for breaking-change review"
	assert_file_contains "$workflow_file" "Changed file history evidence" "opencode review evidence includes changed-file history"
	assert_file_contains "$workflow_file" "migration/bridge-module needs" "opencode review considers bridge modules for breaking changes"
	assert_file_not_contains "$workflow_file" "PRD|TRD|ERD" "opencode review must not rely on enum-based document safety exceptions"
	assert_file_not_contains "$workflow_file" "non-contract documentation" "opencode review must not use deterministic non-contract documentation approval"
	assert_file_contains "$workflow_file" "deployments: read" "opencode review can read deployment evidence"
	assert_file_contains "$workflow_file" "observable impact, trigger condition" "opencode review prompt requires practical finding details"
	assert_file_contains "$workflow_file" "regression_test_direction should name an exact test target" "opencode review prompt requires concrete validation guidance"
	assert_file_contains "$workflow_file" "P1/P2/P3 priority" "opencode review prompt requires Greptile-style priority labels"
	assert_file_contains "$workflow_file" "nearby implementation, matching existing example, cross-file counterpart, current official docs, or failed check/log evidence" "opencode review prompt requires explicit evidence type"
	assert_file_contains "$workflow_file" "flag unrelated PR scope drift" "opencode review prompt catches unrelated scope drift"
	assert_file_contains "$workflow_file" "GitHub suggestion-ready minimal diffs" "opencode review prompt requires directly applicable suggested diffs"
	assert_file_contains "$workflow_file" "Compare repository-local patterns before judging DX or UX" "opencode review prompt borrows helpful sibling-repo DX/UX patterns before judging changes"
	assert_file_contains "$workflow_file" "URL-only diagnostics" "opencode review prompt flags status and review noise that harms DX/UX"
	assert_file_contains "$workflow_file" "Developer experience:" "opencode review summary requires a developer-experience posture"
	assert_file_contains "$workflow_file" "User experience:" "opencode review summary requires a user-experience posture"
	assert_file_contains "$workflow_file" "compact Mermaid DAG" "opencode review prompt requires a concrete Mermaid DAG"
	assert_file_contains "$workflow_file" "do not use generic placeholder nodes like Changed surface or Main risk" "opencode review prompt forbids generic Mermaid placeholder nodes"
	assert_file_contains "$workflow_file" "PR mergeability evidence" "opencode review evidence includes PR mergeability state"
	assert_file_contains "$workflow_file" "## Changed docs repository tree evidence" "opencode review evidence includes repo-tree facts for changed docs directories"
	assert_file_contains "$workflow_file" 'git -C "$OPENCODE_SOURCE_WORKDIR" ls-tree -r --name-only "$PR_HEAD_SHA" -- "$docs_dir"' "opencode review evidence lists current-head docs assets from the PR head worktree before judging docs claims"
	assert_file_contains "$workflow_file" "Do not claim repository docs, images, or reference assets are unavailable, missing, or absent unless the changed docs repository tree evidence proves it." "opencode review prompt forbids unsupported docs asset absence claims"
	assert_file_contains "$workflow_file" "Merge Conflict Guidance" "opencode review overview includes conflict repair guidance"
	assert_file_contains "$workflow_file" "gh pr checkout" "opencode merge-conflict guidance starts from checking out the PR branch"
	assert_file_contains "$workflow_file" "git fetch origin" "opencode merge-conflict guidance fetches the latest base branch"
	assert_file_contains "$workflow_file" "git status --short" "opencode merge-conflict guidance tells the author how to find unresolved conflict files"
	assert_file_contains "$workflow_file" "git push --force-with-lease" "opencode merge-conflict guidance limits force pushes to the rebase path"
	assert_file_contains "$workflow_file" "mergeStateStatus DIRTY or CONFLICTING" "opencode review prompt handles merge conflicts"
	assert_file_contains "$workflow_file" "mergeStateStatus BLOCKED is a branch policy, review, or check state, not conflict guidance" "opencode review prompt does not misclassify branch-policy blockers as merge conflicts"
	if [ -e "$REPO_ROOT/.github/workflows/opencode-merge-conflict-guidance.yml" ]; then
		record_failure "opencode merge-conflict guidance must stay inside OpenCode Review instead of a separate workflow"
	fi
	assert_file_contains "$workflow_file" "Structural exploration is mandatory for every PR" "opencode review prompt makes structural exploration mandatory"
	assert_file_contains "$workflow_file" "Never state that structural exploration, structural analysis, or structural review is not required or unnecessary" "opencode review prompt forbids dismissing structural review"
	assert_file_contains "$workflow_file" "If structural exploration was not possible or changed files could not be inspected after reading bounded-review-evidence.md and the changed files, do not approve" "opencode review prompt blocks approval without structural evidence"
	assert_file_contains "$workflow_file" "Use precomputed CodeGraph evidence for blast-radius, call graph, and test-coverage questions" "opencode review consumes trusted CodeGraph guidance without exp…121965 tokens truncated…9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

# Regression: Vertex custom model resource path projects/<p>/locations/<l>/models/<id>
# (no publishers/ segment) must be recognized as a Vertex resource path and
# normalized to vertex_ai/<model_id>.
run_gate_case "vertex-custom-model-resource-path" \
	"projects/my-proj/locations/us-central1/models/my-custom-model-123" \
	"vertex_ai/fallback-one" \
	"0" \
	"Normalized STRIX_LLM to provider-qualified model 'vertex_ai/my-custom-model-123'." \
	"1" \
	"vertex_ai/my-custom-model-123" \
	"<unset>"

run_gate_case "vertex-notfound-without-status-fallback-success" \
	"vertex_ai/missing-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case "vertex-notfound-compact-status-fallback-success" \
	"vertex_ai/missing-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case "nonvertex-slash-model-passthrough" \
	"foo/bar" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok with non-vertex slash model passthrough" \
	"1" \
	"foo/bar" \
	"https://example.invalid"

run_gate_case "primary-duplicate-in-fallback" \
	"missing-primary" \
	"vertex_ai/missing-primary fallback-one" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case "multiline-fallback-success" \
	"vertex_ai/missing-primary" \
	$'vertex_ai/fallback-one\nvertex_ai/fallback-two' \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-two' in [0-9]+s\\." \
	"3" \
	"vertex_ai/missing-primary|vertex_ai/fallback-one|vertex_ai/fallback-two" \
	"<unset>|<unset>|<unset>"

run_gate_case_allow_provider_signal "vertex-primary-ratelimit-fallback-success" \
	"vertex_ai/ratelimit-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/ratelimit-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

LC_ALL=C run_gate_case "nvidia-ratelimit-model-quality-warning-fallback-success" \
	"nvidia_nim/nvidia/nemotron-3-super-120b-a12b" \
	"nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5' in [0-9]+s\\." \
	"2" \
	"nvidia_nim/nvidia/nemotron-3-super-120b-a12b|nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" \
	"<unset>|<unset>" \
	"openai"

run_gate_case "hf-advisory-suffix-fails-closed" \
	"vertex_ai/hf-advisory-suffix-fails-closed" \
	"" \
	"1" \
	"Strix run emitted provider infrastructure or failure-signal output; failing closed." \
	"1" \
	"vertex_ai/hf-advisory-suffix-fails-closed" \
	"<unset>"

run_gate_case_allow_provider_signal "vertex-primary-resource-exhausted-fallback-success" \
	"vertex_ai/resource-exhausted-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/resource-exhausted-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case_allow_provider_signal "openai-primary-quota-fallback-success" \
	"openai/quota-primary" \
	"openai/fallback-one openai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'openai/fallback-one' in [0-9]+s\\." \
	"2" \
	"openai/quota-primary|openai/fallback-one" \
	"<unset>|<unset>" \
	"openai"

run_gate_case_allow_provider_signal "vertex-primary-429-fallback-success" \
	"vertex_ai/http429-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/http429-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case_allow_provider_signal "vertex-primary-midstream-fallback-success" \
	"vertex_ai/midstream-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/midstream-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case_allow_provider_signal "vertex-primary-midstream-retry-same-model-success" \
	"vertex_ai/retry-midstream-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after same-model retry" \
	"2" \
	"vertex_ai/retry-midstream-primary|vertex_ai/retry-midstream-primary" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# Bug 9: Rate-limit transient same-model retry (previously untested path)
run_gate_case_allow_provider_signal "vertex-primary-ratelimit-retry-same-model-success" \
	"vertex_ai/retry-ratelimit-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after same-model rate-limit retry" \
	"2" \
	"vertex_ai/retry-ratelimit-primary|vertex_ai/retry-ratelimit-primary" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "vertex-primary-api-connection-retry-same-model-success" \
	"gemini/retry-api-connection-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after same-model api connection retry" \
	"2" \
	"gemini/retry-api-connection-primary|gemini/retry-api-connection-primary" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "github-models-internal-server-connection-retry-same-model-success" \
	"openai/openai/retry-api-connection-primary" \
	"" \
	"0" \
	"scan ok after same-model api connection retry" \
	"2" \
	"openai/openai/retry-api-connection-primary|openai/openai/retry-api-connection-primary" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"1"

run_gate_case "github-models-primary-unavailable-fallback-success" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-r1-0528' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case_allow_provider_signal "github-models-primary-denied-fallback-success" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-r1-0528' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_github_models_http410_case \
	"github-models-http410-authenticated-fallback-success" \
	"0" \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-r1-0528' in [0-9]+s\\."

for scenario in \
	github-models-http410-missing-http-token \
	github-models-http410-missing-provider-error \
	github-models-http410-numeric-continuation-4100 \
	github-models-http410-numeric-continuation-4104 \
	github-models-http410-target-output-spoof \
	github-models-retirement-brownout-phrase-only; do
	run_github_models_http410_case \
		"$scenario" \
		"1" \
		"1" \
		"openai/gpt-5" \
		"https://models.github.ai/inference"
done

run_gate_case "github-models-primary-ratelimit-fallback-success" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-r1-0528' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"2" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case "github-models-fallback-provider-signal-tries-next" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-v3-0324' in [0-9]+s\\." \
	"3" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528|openai/deepseek/deepseek-v3-0324" \
	"https://models.github.ai/inference|https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case "github-models-fallback-baseline-vulnerability-blocks" \
	"openai/gpt-5" \
	"" \
	"1" \
	"Strix model reported threshold vulnerabilities before fallback success; failing closed so every model-reported vulnerability is reviewed." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case "github-models-fallback-changed-vulnerability-before-next-success-blocks" \
	"openai/gpt-5" \
	"" \
	"1" \
	"Strix model reported threshold vulnerabilities before fallback success; failing closed so every model-reported vulnerability is reviewed." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case "github-models-fallback-dockerfile-test-baseline-before-next-success-continues" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'deepseek/deepseek-v3-0324' in [0-9]+s\\." \
	"3" \
	"openai/gpt-5|openai/deepseek/deepseek-r1-0528|openai/deepseek/deepseek-v3-0324" \
	"https://models.github.ai/inference|https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"0" \
	"MEDIUM" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/build-ci-image.yml" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"deepseek/deepseek-r1-0528 deepseek/deepseek-v3-0324" \
	"1"

run_gate_case_allow_provider_signal "gemini-high-demand-retry-same-model-success" \
	"gemini/retry-high-demand-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after same-model high-demand retry" \
	"2" \
	"gemini/retry-high-demand-primary|gemini/retry-high-demand-primary" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "gemini-timeout-direct-fallback-success" \
	"gemini/retry-timeout-primary" \
	"gemini/fallback-one gemini/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'gemini/fallback-one' in [0-9]+s\\." \
	"2" \
	"gemini/retry-timeout-primary|gemini/fallback-one" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "gemini-timeout-fallback-success" \
	"gemini/timeout-fallback-primary" \
	"gemini/fallback-one gemini/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'gemini/fallback-one' in [0-9]+s\\." \
	"2" \
	"gemini/timeout-fallback-primary|gemini/fallback-one" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "gemini-generic-fallback-success" \
	"gemini/timeout-fallback-primary" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'gemini/fallback-one' in [0-9]+s\\." \
	"2" \
	"gemini/timeout-fallback-primary|gemini/fallback-one" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"0" \
	"" \
	"" \
	"" \
	"__UNSET__" \
	"gemini/fallback-one gemini/fallback-two"

run_gate_case_allow_provider_signal "gemini-zero-findings-timeout-fallback-allows-pr" \
	"gemini/zero-timeout-primary" \
	"gemini/fallback-one" \
	"1" \
	"Strix reported zero vulnerabilities before provider infrastructure failure; failing closed because provider infrastructure failures are not clean scan evidence." \
	"2" \
	"gemini/zero-timeout-primary|gemini/fallback-one" \
	"https://example.invalid|https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case_allow_provider_signal "pr-scope-zero-finding-does-not-leak" \
	"gemini/scope-zero-leak-primary" \
	"" \
	"1" \
	"Strix reported zero vulnerabilities before provider infrastructure failure; failing closed because provider infrastructure failures are not clean scan evidence." \
	"1" \
	"gemini/scope-zero-leak-primary" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	$'sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java\nsync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java' \
	"" \
	"1"

run_gate_case "service-unavailable-no-llm-marker-nonrecoverable" \
	"custom/service-unavailable-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"custom/service-unavailable-primary" \
	"https://example.invalid" \
	"custom" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case "server-disconnect-no-llm-marker-nonrecoverable" \
	"vertex_ai/app-server-disconnect-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/app-server-disconnect-primary" \
	"<unset>"

# Bug 11: Timeout should move directly to fallback instead of retrying the same model.
run_gate_case_allow_provider_signal "vertex-primary-timeout-retry-same-model-success" \
	"vertex_ai/retry-timeout-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after timeout fallback" \
	"2" \
	"vertex_ai/retry-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# Bug 11b: Timeout → immediate fallback model succeeds.
run_gate_case_allow_provider_signal "vertex-primary-timeout-exhausted-fallback-success" \
	"vertex_ai/timeout-exhaust-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"scan ok after timeout-exhausted fallback" \
	"2" \
	"vertex_ai/timeout-exhaust-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "zero-findings-timeout-all-models" \
	"vertex_ai/zero-timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix reported zero vulnerabilities before provider infrastructure failure; failing closed because provider infrastructure failures are not clean scan evidence." \
	"2" \
	"vertex_ai/zero-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case_allow_provider_signal "zero-findings-timeout-all-models" \
	"vertex_ai/zero-timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"2" \
	"vertex_ai/zero-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS" \
	"0" \
	"push"

run_gate_case_allow_provider_signal "zero-findings-sticky-across-fallback" \
	"vertex_ai/zero-sticky-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix reported zero vulnerabilities before provider infrastructure failure; failing closed because provider infrastructure failures are not clean scan evidence." \
	"2" \
	"vertex_ai/zero-sticky-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case_allow_provider_signal "zero-findings-with-low-report-timeout" \
	"vertex_ai/zero-low-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"2" \
	"vertex_ai/zero-low-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "strict-zero-findings-timeout-fails-pr" \
	"vertex_ai/zero-timeout-primary" \
	" " \
	"1" \
	"failing closed" \
	"1" \
	"vertex_ai/zero-timeout-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "provider-fatal-success-signal" \
	"vertex_ai/provider-fatal-success-signal" \
	"" \
	"1" \
	"Strix run emitted provider infrastructure or failure-signal output; failing closed." \
	"1" \
	"vertex_ai/provider-fatal-success-signal" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "provider-warning-success-signal" \
	"vertex_ai/provider-warning-success-signal" \
	"" \
	"1" \
	"Strix run emitted provider infrastructure or failure-signal output; failing closed." \
	"1" \
	"vertex_ai/provider-warning-success-signal" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "provider-report-rate-limit-fallback-success" \
	"vertex_ai/report-rate-limit-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/report-rate-limit-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>"

run_gate_case "report-symlink-rejected-without-rewriting-target" \
	"vertex_ai/report-symlink-rejected" \
	"" \
	"1" \
	"Strix report artifact tree contains a symlink" \
	"1" \
	"vertex_ai/report-symlink-rejected" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "report-known-internal-warning-variant-sanitized" \
	"vertex_ai/report-known-internal-warning-variant-sanitized" \
	"" \
	"0" \
	"Strix run succeeded for model 'vertex_ai/report-known-internal-warning-variant-sanitized'" \
	"1" \
	"vertex_ai/report-known-internal-warning-variant-sanitized" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "report-web-search-advisory-sanitized" \
	"vertex_ai/report-web-search-advisory-sanitized" \
	"" \
	"0" \
	"Strix run succeeded for model 'vertex_ai/report-web-search-advisory-sanitized'" \
	"1" \
	"vertex_ai/report-web-search-advisory-sanitized" \
	"<unset>"

run_gate_case "report-web-search-advisory-suffix-fails" \
	"vertex_ai/report-web-search-advisory-suffix-fails" \
	"" \
	"1" \
	"Strix report artifacts emitted warning/fatal/denied/timeout output; failing closed." \
	"1" \
	"vertex_ai/report-web-search-advisory-suffix-fails" \
	"<unset>"

run_gate_case "report-unknown-warning-fails" \
	"vertex_ai/report-unknown-warning-fails" \
	"" \
	"1" \
	"Strix report artifacts emitted warning/fatal/denied/timeout output; failing closed." \
	"1" \
	"vertex_ai/report-unknown-warning-fails" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case "provider-denied-success-signal" \
	"vertex_ai/provider-denied-success-signal" \
	"" \
	"1" \
	"Strix run emitted provider infrastructure or failure-signal output; failing closed." \
	"1" \
	"vertex_ai/provider-denied-success-signal" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"__SAME_AS_FALLBACK_MODELS__" \
	"" \
	"1"

run_gate_case_allow_provider_signal "vertex-all-ratelimited" \
	"vertex_ai/ratelimit-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"3" \
	"vertex_ai/ratelimit-primary|vertex_ai/fallback-one|vertex_ai/fallback-two" \
	"<unset>|<unset>|<unset>"

run_gate_case "vertex-primary-hallucinated-endpoint-fallback-success" \
	"vertex_ai/hallucination-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/hallucination-primary" \
	"<unset>"

run_gate_case "opencode-documented-env-api-key-fallback-success" \
	"vertex_ai/opencode-env-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/opencode-env-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"HIGH" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/opencode-review.yml"

run_gate_case "generic-github-actions-workflow-fallback-success" \
	"vertex_ai/generic-actions-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"vertex_ai/generic-actions-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/strix.yml"

run_gate_case "vertex-primary-existing-endpoint-nonrecoverable" \
	"vertex_ai/existing-endpoint-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/existing-endpoint-primary" \
	"<unset>"

run_gate_case "pr-stale-source-claim-fallback-success" \
	"vertex_ai/stale-source-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/stale-source-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"HIGH" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/db/models.py"

run_gate_case "pr-stale-snapshot-snippet-fallback-success" \
	"vertex_ai/stale-snapshot-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/stale-snapshot-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"MEDIUM" \
	"0" \
	"__PR_SCOPE__" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/app/api/snapshots.py"

run_gate_case "pr-stale-source-plus-real-finding-blocks" \
	"vertex_ai/stale-source-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/stale-source-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"HIGH" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	$'backend/db/models.py\nbackend/api/emails.py'

run_gate_case_allow_provider_signal "pr-changed-finding-with-retry-marker-blocks" \
	"vertex_ai/changed-finding-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/changed-finding-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"HIGH" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/api/emails.py"

run_gate_case "pr-stale-report-plus-inline-changed-finding-blocks" \
	"vertex_ai/stale-inline-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/stale-inline-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"HIGH" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	$'backend/db/models.py\nbackend/api/emails.py'

run_gate_case "high-vuln-below-threshold" \
	"vertex_ai/high-vuln-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/high-vuln-primary" \
	"<unset>"

run_gate_case "multi-severity-low-then-critical" \
	"vertex_ai/multi-severity-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/multi-severity-primary" \
	"<unset>"

run_gate_case "inline-medium-below-threshold" \
	"vertex_ai/inline-medium-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/inline-medium-primary" \
	"<unset>"

run_gate_case "medium-vuln-default-threshold" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"__UNSET__"

# Infrastructure error guard: below-threshold findings must NOT pass when the
# strix log contains evidence of infrastructure-level errors (timeout,
# rate-limit, transport failures) because the scan was likely incomplete.

# Guard test 1: LOW finding + timeout → should fail (exit 1).
# Timeout is Vertex-retryable, but every nonzero attempt remains incomplete
# evidence even when it emits only a below-threshold report.
run_gate_case_allow_provider_signal "below-threshold-with-timeout" \
	"vertex_ai/low-timeout-primary" \
	"vertex_ai/gemini-2.5-pro vertex_ai/gemini-2.5-flash" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"3" \
	"vertex_ai/low-timeout-primary|vertex_ai/gemini-2.5-pro|vertex_ai/gemini-2.5-flash" \
	"<unset>|<unset>|<unset>"

# Guard test 2: LOW finding + rate-limit → should fail (exit 1).
# Rate-limit is Vertex-retryable, so the gate tries every fallback without
# accepting the below-threshold report from a failed scanner process.
run_gate_case_allow_provider_signal "below-threshold-with-ratelimit" \
	"vertex_ai/low-ratelimit-primary" \
	"vertex_ai/gemini-2.5-pro vertex_ai/gemini-2.5-flash" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"3" \
	"vertex_ai/low-ratelimit-primary|vertex_ai/gemini-2.5-pro|vertex_ai/gemini-2.5-flash" \
	"<unset>|<unset>|<unset>"

# Guard test 3: INFO finding + ConnectionError → should fail (exit 1).
# ConnectionError is NOT vertex-retryable, so only the primary model is tried.
run_gate_case_allow_provider_signal "below-threshold-with-connection-error" \
	"vertex_ai/info-conn-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/info-conn-primary" \
	"<unset>"

# Guard test 3b: INFO finding + ConnectionError WITHOUT provider marker → should
# fail closed. A nonzero scanner exit is incomplete evidence even when the
# report contains only below-threshold findings and no provider marker.
run_gate_case "below-threshold-with-connection-error-no-provider" \
	"vertex_ai/info-conn-noprov-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/info-conn-noprov-primary" \
	"<unset>"

# Guard test 3c: INFO finding + requests.exceptions.ConnectionError → should
# fail closed for the same nonzero-exit reason; the transport-library
# classifier no longer controls whether incomplete evidence can pass.
run_gate_case "below-threshold-with-requests-connection-error" \
	"vertex_ai/info-conn-requests-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/info-conn-requests-primary" \
	"<unset>"

# Guard test 4: MEDIUM finding + MidStreamFallbackError → should fail (exit 1).
# Midstream is vertex-retryable, so the gate also tries fallback models
# while every nonzero scanner result remains incomplete evidence.
run_gate_case_allow_provider_signal "below-threshold-with-midstream" \
	"vertex_ai/medium-midstream-primary" \
	"vertex_ai/gemini-2.5-pro vertex_ai/gemini-2.5-flash" \
	"1" \
	"Configured Vertex model and fallback models were unavailable." \
	"3" \
	"vertex_ai/medium-midstream-primary|vertex_ai/gemini-2.5-pro|vertex_ai/gemini-2.5-flash" \
	"<unset>|<unset>|<unset>"

run_gate_case "critical-vuln-at-threshold" \
	"vertex_ai/critical-vuln-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/critical-vuln-primary" \
	"<unset>"

run_gate_case "malformed-severity-marker-nonrecoverable" \
	"vertex_ai/malformed-severity-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/malformed-severity-primary" \
	"<unset>"

# Bug 7: Model disagreement — the primary produces an unmapped CRITICAL report
# alongside a NOT_FOUND error. The report is already actionable fail-closed
# evidence, so the gate must not spend provider budget on a fallback whose LOW
# result could make the earlier finding appear downgraded.
run_gate_case "model-disagreement-critical-in-earlier-report" \
	"vertex_ai/model-a" \
	"vertex_ai/model-b" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/model-a" \
	"<unset>"

# Bug 4: deepseek/models/deepseek-r1 must NOT be rewritten to vertex_ai/deepseek-r1
run_gate_case "nonvertex-slash-model-not-rewritten" \
	"deepseek/models/deepseek-r1" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok with deepseek model passthrough" \
	"1" \
	"deepseek/models/deepseek-r1" \
	"https://example.invalid"

# Regression: STRIX_TARGET_PATH=<dir>/src with default STRIX_SOURCE_DIRS (now ".")
# must resolve to <dir>/src/. (i.e. <dir>/src itself), NOT <dir>/src/src.
# The hallucinated-endpoint scenario writes a threshold report with a fake
# endpoint. Source-dir resolution still runs, but threshold findings now remain
# blocking even when model/source inconsistency is suspected.
run_gate_case "target-path-src-default-source-dirs" \
	"vertex_ai/hallucination-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/hallucination-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1" \
	"CRITICAL" \
	"0" \
	"__USE_SUBDIR_SRC__" \
	""

# Bug 2 follow-up: multi-entry STRIX_SOURCE_DIRS test.
# Endpoint /api/status lives in api/ (not src/).  With STRIX_SOURCE_DIRS="src api"
# the gate must find the endpoint in the api/ dir and treat the finding as
# non-hallucinated → non-recoverable failure (exit 1).
run_gate_case "multi-source-dirs-existing-endpoint" \
	"vertex_ai/multi-dir-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"vertex_ai/multi-dir-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"src api"

run_gate_case "preserve-existing-api-base" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with preserved api base" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://preexisting.invalid" \
	"vertex_ai" \
	"" \
	"https://preexisting.invalid"

run_gate_case "default-fallback-order-fast-first" \
	"vertex_ai/missing-primary" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/gemini-2[.]5-pro' in [0-9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|vertex_ai/gemini-2.5-pro" \
	"<unset>|<unset>"

# Bug 13: All fallback models are the same as the primary model.
# The gate should detect that no distinct fallback was tried and emit an ERROR.
run_gate_case "all-fallbacks-same-as-primary" \
	"vertex_ai/same-primary" \
	"vertex_ai/same-primary vertex_ai/same-primary" \
	"1" \
	"ERROR: All configured fallback models are the same as the primary model" \
	"1" \
	"vertex_ai/same-primary" \
	"<unset>"

# Bug 14: Timeout should fall back rather than emit a same-model retry message.
run_gate_case_allow_provider_signal "vertex-primary-timeout-retry-reason-message" \
	"vertex_ai/retry-timeout-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'vertex_ai/fallback-one' in [0-9]+s\\." \
	"2" \
	"vertex_ai/retry-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"2"

# Bug 14: Retry reason messages — rate-limit retry should say "due to rate limit".
run_gate_case_allow_provider_signal "vertex-primary-ratelimit-retry-reason-message" \
	"vertex_ai/retry-ratelimit-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"0" \
	"Retrying model 'vertex_ai/retry-ratelimit-primary' due to rate limit" \
	"2" \
	"vertex_ai/retry-ratelimit-primary|vertex_ai/retry-ratelimit-primary" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"2"

# Bug 14: Timing message — success should log elapsed time.
run_gate_case "vertex-primary-success-timing-message" \
	"vertex_ai/ready-primary" \
	"" \
	"0" \
	"REGEX:Strix run succeeded for model 'vertex_ai/ready-primary' in [0-9]+s\\." \
	"1" \
	"vertex_ai/ready-primary" \
	"<unset>"

# is_timeout_error() provider-context marker test:
# Bare "Connection timed out" without any LLM provider marker should NOT
# be treated as a timeout error. The gate should fail without retrying.
# The fake strix now also emits "httpx", "httpcore", and "requests" strings
# to verify that transport library names alone do NOT qualify as provider markers.
# Model name deliberately avoids containing any provider marker string
# (litellm, openai, anthropic, VertexAI, vertex.ai, google.cloud).
run_gate_case "bare-timeout-no-provider-marker" \
	"custom/bare-timeout-model" \
	"" \
	"1" \
	"" \
	"1" \
	"custom/bare-timeout-model" \
	"https://example.invalid" \
	"custom" \
	"__DEFAULT__" \
	"" \
	"1"

# is_timeout_error() Tier 2: httpx.ReadTimeout + provider-context marker.
# The timeout should be classified for fallback, not same-model retry.
run_gate_case_allow_provider_signal "httpx-read-timeout-with-provider-marker" \
	"vertex_ai/httpx-timeout-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok after httpx-timeout fallback" \
	"2" \
	"vertex_ai/httpx-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# Negative: httpx.ReadTimeout WITHOUT provider-context marker should NOT
# be classified as a retryable timeout (the gate should treat it as a
# non-recoverable scan failure).
run_gate_case "httpx-read-timeout-no-provider-marker" \
	"custom/httpx-timeout-no-ctx" \
	"" \
	"1" \
	"non-recoverable error" \
	"1" \
	"custom/httpx-timeout-no-ctx" \
	"https://example.invalid" \
	"custom" \
	"__DEFAULT__" \
	"" \
	"1"

# is_timeout_error() Tier 2b: httpcore.ReadTimeout + provider-context marker.
# Mirrors the httpx.ReadTimeout positive case above, but falls back immediately.
run_gate_case_allow_provider_signal "httpcore-read-timeout-with-provider-marker" \
	"vertex_ai/httpcore-timeout-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok after httpcore-timeout fallback" \
	"2" \
	"vertex_ai/httpcore-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# Negative: httpcore.ReadTimeout WITHOUT provider-context marker should NOT
# be classified as a retryable timeout (the gate should treat it as a
# non-recoverable scan failure).
run_gate_case "httpcore-read-timeout-no-provider-marker" \
	"custom/httpcore-timeout-no-ctx" \
	"" \
	"1" \
	"non-recoverable error" \
	"1" \
	"custom/httpcore-timeout-no-ctx" \
	"https://example.invalid" \
	"custom" \
	"__DEFAULT__" \
	"" \
	"1"

# is_timeout_error() positive branch for "Connection timed out" + provider marker:
# When "Connection timed out" appears alongside an LLM provider marker, the
# gate should classify it as a timeout and move to fallback.
run_gate_case_allow_provider_signal "bare-timeout-with-provider-marker" \
	"vertex_ai/bare-timeout-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok after bare-timeout fallback" \
	"2" \
	"vertex_ai/bare-timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# Bare "Connection timed out" + provider marker: primary fails once,
# then gate falls back to fallback-one which succeeds.
run_gate_case_allow_provider_signal "bare-timeout-provider-marker-exhausted-fallback" \
	"vertex_ai/bare-timeout-exhaust-primary" \
	"vertex_ai/fallback-one" \
	"0" \
	"scan ok after bare-timeout-exhaust fallback" \
	"2" \
	"vertex_ai/bare-timeout-exhaust-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

# A rate-limited primary followed by a failed fallback with a partial LOW report
# remains incomplete evidence and must fail closed.
run_gate_case_allow_provider_signal "infra-error-sticky-flag" \
	"vertex_ai/sticky-flag-primary" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"3" \
	"vertex_ai/sticky-flag-primary|vertex_ai/sticky-flag-primary|vertex_ai/gemini-2.5-pro" \
	"<unset>|<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"1"

run_invalid_min_fail_severity_case
run_required_input_file_outside_input_root_fails_closed_case "STRIX_LLM_FILE"
run_required_input_file_outside_input_root_fails_closed_case "LLM_API_KEY_FILE"
run_vertex_model_ignores_untrusted_llm_api_base_file_case
run_llm_api_base_file_outside_input_root_fails_closed_case
run_pr_scoped_llm_api_base_file_config_failure_exits_2_case
run_input_file_root_override_takes_precedence_over_runner_temp_case
run_stale_report_case
run_symlink_report_case
run_unsafe_target_path_case
run_absolute_outside_target_path_case

run_gate_case_allow_provider_signal "slow-timeout" \
	"vertex_ai/slow-primary" \
	"" \
	"1" \
	"Strix run timed out after ${TIMEOUT_TEST_PROCESS_SECONDS}s." \
	"3" \
	"vertex_ai/slow-primary|vertex_ai/gemini-2.5-pro|vertex_ai/gemini-2.5-flash" \
	"<unset>|<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"$TIMEOUT_TEST_PROCESS_SECONDS"

run_gate_case "timeout-disabled-success" \
	"vertex_ai/timeout-disabled-primary" \
	"" \
	"0" \
	"scan ok with timeout disabled" \
	"1" \
	"vertex_ai/timeout-disabled-primary" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"0"

run_timeout_cleanup_case

run_total_timeout_case

run_gate_case "pr-changed-scope-bounded" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with bounded changed-file scope" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "scan-working-directory-isolated" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with isolated Strix working directory" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/app/pg_introspect/introspect.py"

run_gate_case "pr-python-scope-context" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with python dependency scope" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/api/emails.py"

run_gate_case "pr-changed-scope-full" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Scoped pull request Strix scan to 3 changed file(s)." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	$'sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java\nsync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java\nsync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/service/impl/SysUserServiceImpl.java'

run_gate_case "pr-changed-scope-full-set" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with full configured PR scope" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	$'sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java\nsync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java\nsync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/service/impl/SysUserServiceImpl.java\nsync-module-system/smart-crawling-common/src/main/java/org/empasy/sync/common/system/util/JwtUtil.java' \
	"" \
	"2"

large_pr_changed_files=""
for large_pr_index in $(seq 1 38); do
	large_pr_path="backend/large-scope/file-$large_pr_index.py"
	if [ -n "$large_pr_changed_files" ]; then
		large_pr_changed_files+=$'\n'
	fi
	large_pr_changed_files+="$large_pr_path"
done

run_gate_case "pr-large-scope-full-set" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with large full PR scope" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"$large_pr_changed_files" \
	"" \
	"12"

run_gate_case "pr-changed-scope-includes-ci-dependency" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with CI support dependency" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"scripts/ci/strix_quick_gate.sh"

run_gate_case "pr-ci-test-harness-only-skip" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"No scannable changed files in pull request; skipping Strix quick scan." \
	"0" \
	"" \
	"" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"scripts/ci/test_strix_quick_gate.sh"

run_gate_case "pr-deployment-scope-entrypoint-context" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with deployment entrypoint context" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/opencode-review.yml"

run_gate_case "pr-rust-workspace-context" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"scan ok with Rust workspace context" \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/rust.yml"

run_gate_case "pr-empty-diff-skip" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"No scannable changed files in pull request; skipping Strix quick scan." \
	"0" \
	"" \
	"" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"__SET_EMPTY__"

run_gate_case "pr-baseline-critical-unchanged" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "pr-baseline-critical-absolute-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "pr-baseline-critical-extensionless-dockerfile-target" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/opencode-review.yml"

run_gate_case "pr-baseline-critical-subdir-target" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-outside-narrowed-subdir-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-baseline-critical-subdir-boxed-target" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-baseline-critical-subdir-endpoint" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-baseline-critical-subdir-endpoint-bare-filename" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-baseline-critical-subdir-narrative-backticked-file" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-relative-path-escape-subdir-narrative-backticked-file" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-changed" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "pr-changed-file-nonintersecting-line" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request"

run_gate_case "pr-critical-changed-bracketed-next-route" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"frontend/src/app/labels/[slug]/page.tsx"

run_gate_case "pr-critical-changed-xml-file-location" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"MEDIUM" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "pr-critical-changed-xml-file-location-space" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"MEDIUM" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"src/unsafe name.py"

run_gate_case "pr-baseline-critical-narrative-backticked-service-file" \
	"openai/gpt-4o-mini" \
	"" \
	"0" \
	"Strix findings are limited to unchanged files in this pull request; allowing pipeline continuation." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/services/email_client.py"

run_gate_case "pr-critical-unmapped-arbitrary-backticked-service-file" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"backend/services/email_client.py"

run_gate_case "pr-critical-changed-absolute-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java"

run_gate_case "pr-critical-changed-internal-dotdir-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	".github/workflows/opencode-review.yml"

run_gate_case "pr-critical-changed-json-target" \
	"vertex_ai/gemini-2.5-pro" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"vertex_ai/gemini-2.5-pro" \
	"<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"MEDIUM" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"frontend/src/components/CalendarLayout.tsx"

run_gate_case "pr-critical-changed-subdir-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-changed-subdir-endpoint" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix finding intersects files changed in this pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-path-escape-subdir-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-server/src/main/resources/flyway/V24__update_search_expression_team_keyword_id.sql" \
	"" \
	"" \
	"1"

run_gate_case "pr-critical-unmapped" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-biz/src/main/java/org/empasy/sync/modules/system/controller/SysPositionController.java"

run_gate_case "pr-critical-unmapped-narrative-target" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java"

run_gate_case "pr-critical-unmapped-other-workspace-repo" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"sync-module-system/smart-crawling-playwright/src/main/java/org/empasy/sync/mcp/service/PlayWrightService.java"

run_gate_case "pr-critical-manifest-only-pom" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml"

run_gate_case "pr-critical-manifest-only-pom-test-override" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"passed"

run_gate_case "pr-critical-manifest-only-pom-same-head-different-pr" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":201,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":456}]},{"id":202,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":456}]}]}'

run_gate_case "pr-critical-manifest-only-pom-current-pr-authoritative" \
	"openai/gpt-4o-mini" \
	"" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"1" \
	"openai/gpt-4o-mini" \
	"https://example.invalid" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":301,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]},{"id":302,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]}]}'

run_gate_case_allow_provider_signal "pr-critical-manifest-only-pom-after-fallback-authoritative" \
	"vertex_ai/timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"2" \
	"vertex_ai/timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":401,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]},{"id":402,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]}]}'

run_gate_case_allow_provider_signal "pr-critical-manifest-only-pom-console-only-after-fallback-authoritative" \
	"vertex_ai/timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"2" \
	"vertex_ai/timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":403,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]},{"id":404,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]}]}'

run_gate_case_allow_provider_signal "pr-critical-manifest-only-pom-console-target-only-after-fallback-authoritative" \
	"vertex_ai/timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"2" \
	"vertex_ai/timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":405,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]},{"id":406,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]}]}'

run_gate_case_allow_provider_signal "pr-low-markdown-plus-console-critical-manifest-after-fallback-authoritative" \
	"vertex_ai/timeout-primary" \
	"vertex_ai/fallback-one" \
	"1" \
	"Strix changed-manifest threshold finding requires package and CVE remediation; pull-request-controlled SCA workflow results cannot override model evidence, so the scan is failing closed." \
	"2" \
	"vertex_ai/timeout-primary|vertex_ai/fallback-one" \
	"<unset>|<unset>" \
	"vertex_ai" \
	"__DEFAULT__" \
	"" \
	"0" \
	"CRITICAL" \
	"0" \
	"" \
	"" \
	"1200" \
	"0" \
	"pull_request" \
	"pom.xml" \
	"" \
	"" \
	"0" \
	"" \
	"123" \
	'{"workflow_runs":[{"id":405,"name":"Dependency review","path":".github/workflows/dependency-review.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]},{"id":406,"name":"OSV-Scanner","path":".github/workflows/osvscanner.yml","head_sha":"test-head-sha","status":"completed","conclusion":"success","pull_requests":[{"number":123}]}]}'

run_missing_config_case "missing-strix-llm" "" "dummy" "ERROR: STRIX_LLM_FILE must reference a regular file containing the model."
run_missing_config_case "missing-llm-api-key" "openai/gpt-5.4" "" "ERROR: LLM_API_KEY_FILE must reference a regular file containing the API key."
run_missing_config_case "whitespace-only-strix-llm" "   " "dummy" "ERROR: STRIX_LLM_FILE must contain a non-empty model value."
run_missing_config_case "whitespace-only-llm-api-key" "openai/gpt-5.4" $'\t  ' "ERROR: LLM_API_KEY_FILE must contain a non-empty API key."
run_strix_llm_file_command_substitution_literal_case
run_vertex_without_llm_api_key_case
run_vertex_with_llm_api_key_file_does_not_forward_case

# ── Segment boundary enforcement for is_vertex_resource_path / extract_vertex_model_id ──
# Shell glob '*' matches '/' so the old case-pattern implementation accepted
# malformed paths with extra segments (e.g. "projects/a/b/locations/…").
# These tests verify that only paths with the exact expected segment count match.
#
# The gate script cannot be sourced directly (it has top-level side effects),
# so the shared helper script exposes the pure model/path functions directly.
# shellcheck source=scripts/ci/strix_model_utils.sh
# shellcheck disable=SC1091  # source path is repo-local; local lint may omit -x
. "$REPO_ROOT/scripts/ci/strix_model_utils.sh"

assert_vertex_path() {
	local label="$1" path="$2" expect_rc="$3"
	local actual_rc
	if is_vertex_resource_path "$path"; then
		actual_rc=0
	else
		actual_rc=1
	fi
	if [ "$actual_rc" -ne "$expect_rc" ]; then
		echo "FAIL: is_vertex_resource_path($label): got rc=$actual_rc want $expect_rc" >&2
		FAILURES=$((FAILURES + 1))
	fi
}

assert_vertex_extract() {
	local label="$1" path="$2" expected="$3"
	local actual rc
	set +e
	actual="$(extract_vertex_model_id "$path")"
	rc=$?
	set -e
	if [ "$rc" -ne 0 ]; then
		record_failure "extract_vertex_model_id($label) rc=$rc path='$path'"
		return
	fi
	if [ "$actual" != "$expected" ]; then
		echo "FAIL: extract_vertex_model_id($label): got '$actual' want '$expected'" >&2
		FAILURES=$((FAILURES + 1))
	fi
}

assert_normalized_model() {
	local label="$1" model="$2" default_provider="$3" expected="$4"
	local actual rc old_default_provider="${DEFAULT_PROVIDER-__UNSET__}"
	if [ "$old_default_provider" = "__UNSET__" ]; then
		unset DEFAULT_PROVIDER
	else
		DEFAULT_PROVIDER="$old_default_provider"
	fi

	DEFAULT_PROVIDER="$default_provider"
	set +e
	actual="$(normalize_model "$model")"
	rc=$?
	set -e

	if [ "$old_default_provider" = "__UNSET__" ]; then
		unset DEFAULT_PROVIDER
	else
		DEFAULT_PROVIDER="$old_default_provider"
	fi

	if [ "$rc" -ne 0 ]; then
		record_failure "normalize_model($label) rc=$rc model='$model'"
		return
	fi
	if [ "$actual" != "$expected" ]; then
		record_failure "normalize_model($label): got '$actual' want '$expected'"
	fi
}

assert_normalize_model_rejected() {
	local label="$1" model="$2" default_provider="$3"
	local rc old_default_provider="${DEFAULT_PROVIDER-__UNSET__}"
	DEFAULT_PROVIDER="$default_provider"
	set +e
	normalize_model "$model" >/dev/null 2>&1
	rc=$?
	set -e
	if [ "$old_default_provider" = "__UNSET__" ]; then
		unset DEFAULT_PROVIDER
	else
		DEFAULT_PROVIDER="$old_default_provider"
	fi
	if [ "$rc" -eq 0 ]; then
		record_failure "normalize_model($label) accepted a Vertex resource without explicit Vertex provider context"
	fi
}

assert_model_requires_vertex_auth() {
	local label="$1" model="$2" default_provider="$3" expected_rc="$4"
	local rc old_default_provider="${DEFAULT_PROVIDER-__UNSET__}"
	if [ "$old_default_provider" = "__UNSET__" ]; then
		unset DEFAULT_PROVIDER
	else
		DEFAULT_PROVIDER="$old_default_provider"
	fi

	DEFAULT_PROVIDER="$default_provider"
	set +e
	model_requires_vertex_auth "$model"
	rc=$?
	set -e

	if [ "$old_default_provider" = "__UNSET__" ]; then
		unset DEFAULT_PROVIDER
	else
		DEFAULT_PROVIDER="$old_default_provider"
	fi

	assert_equals "$expected_rc" "$rc" "model_requires_vertex_auth($label)"
}

# Valid paths — should return 0
assert_vertex_path "models/<id>" "models/gemini-2.5-pro" 0
assert_vertex_path "publishers/<p>/models/<id>" "publishers/google/models/gemini-2.5-pro" 0
assert_vertex_path "projects/<p>/locations/<l>/models/<id>" "projects/my-proj/locations/us-central1/models/gemini-2.5-pro" 0
assert_vertex_path "projects/<p>/locations/<l>/publishers/<pub>/models/<id>" "projects/my-proj/locations/us-central1/publishers/google/models/gemini-2.5-pro" 0

# Malformed paths — extra segments that '*' used to match across '/'
assert_vertex_path "extra-segment-in-project" "projects/a/b/locations/us/models/foo" 1
assert_vertex_path "extra-segment-in-location" "projects/a/locations/b/c/models/foo" 1
assert_vertex_path "extra-segment-in-publisher" "projects/a/locations/b/publishers/c/d/models/foo" 1
assert_vertex_path "extra-segment-after-models" "projects/a/locations/b/models/foo/bar" 1
assert_vertex_path "empty-model-id" "models/" 1
assert_vertex_path "empty-project" "projects//locations/us/models/foo" 1
assert_vertex_path "plain-model-name" "gemini-2.5-pro" 1
assert_vertex_path "non-vertex-provider-slash" "deepseek/models/deepseek-r1" 1
assert_vertex_path "empty-string" "" 1

# extract_vertex_model_id — valid paths
assert_vertex_extract "models/<id>" "models/gemini-2.5-pro" "gemini-2.5-pro"
assert_vertex_extract "publishers/<p>/models/<id>" "publishers/google/models/gemini-2.5-pro" "gemini-2.5-pro"
assert_vertex_extract "projects/<p>/locations/<l>/models/<id>" "projects/my-proj/locations/us-central1/models/gemini-2.5-pro" "gemini-2.5-pro"
assert_vertex_extract "projects/…/publishers/…/models/<id>" "projects/my-proj/locations/us-central1/publishers/google/models/gemini-2.5-pro" "gemini-2.5-pro"

# extract_vertex_model_id — non-vertex paths return as-is
assert_vertex_extract "non-vertex-passthrough" "deepseek/models/deepseek-r1" "deepseek/models/deepseek-r1"
assert_vertex_extract "plain-model-passthrough" "gemini-2.5-pro" "gemini-2.5-pro"

# Explicit Vertex resource paths require an explicit Vertex provider context.
assert_normalized_model \
	"vertex-resource-ignores-nonvertex-default-provider" \
	"projects/my-proj/locations/us-central1/publishers/google/models/gemini-2.5-pro" \
	"vertex_ai" \
	"vertex_ai/gemini-2.5-pro"

assert_normalized_model \
	"direct-openai-workflow-alias" \
	"openai-direct/gpt-5.6-luna" \
	"openai" \
	"openai_direct/gpt-5.6-luna"

assert_model_requires_vertex_auth "explicit-vertex" "vertex_ai/gemini-2.5-pro" "gemini" "0"
assert_model_requires_vertex_auth "explicit-vertex-beta" "vertex_ai_beta/gemini-2.5-pro" "gemini" "0"
assert_model_requires_vertex_auth "vertex-resource-path" "projects/my-proj/locations/us-central1/models/gemini-2.5-pro" "vertex_ai" "0"
assert_model_requires_vertex_auth "implicit-vertex-default" "gemini-2.5-pro" "vertex_ai" "0"
assert_model_requires_vertex_auth "nonvertex-provider" "gemini/gemini-2.5-pro" "gemini" "1"
assert_normalize_model_rejected "bare-models-openai-context" "models/attacker-selected" "openai"
assert_normalize_model_rejected "bare-models-empty-context" "models/attacker-selected" ""

# Whitespace in paths — must be rejected (SAST word-splitting guard)
assert_vertex_path "space-in-project" "projects/my proj/locations/us/models/foo" 1
assert_vertex_path "tab-in-model-id" $'models/gemini\t2.5' 1
assert_vertex_path "space-in-model-id" "models/my model" 1

run_gate_case "github-models-model-prefix-requires-api-base" \
	"openai/openai/gpt-5.4" \
	"" \
	"2" \
	"GitHub Models Strix scans require LLM_API_BASE_FILE" \
	"0" \
	"" \
	"" \
	"openai" \
	""

run_gate_case "github-models-api-base-rejected-for-direct-openai" \
	"openai/o4-mini" \
	"" \
	"2" \
	"LLM_API_BASE may route through GitHub Models only when STRIX_LLM uses a GitHub Models-compatible model" \
	"0" \
	"" \
	"" \
	"openai" \
	"https://models.github.ai/inference"

run_gate_case "github-models-openai-gpt-requires-api-base" \
	"openai/gpt-5" \
	"" \
	"2" \
	"GitHub Models Strix scans require LLM_API_BASE_FILE" \
	"0" \
	"" \
	"" \
	"openai" \
	""

run_gate_case "direct-openai-gpt-does-not-require-github-models-api-base" \
	"openai_direct/gpt-5.4" \
	"" \
	"0" \
	"scan ok" \
	"1" \
	"openai/gpt-5.4" \
	"<unset>" \
	"openai" \
	""

run_gate_case "github-models-model-prefix-with-api-base-succeeds" \
	"openai/gpt-5" \
	"" \
	"0" \
	"scan ok" \
	"1" \
	"openai/gpt-5" \
	"https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference"

run_gate_case "github-models-meta-prefix-with-api-base-succeeds" \
	"openai/meta/test-github-model" \
	"" \
	"0" \
	"scan ok" \
	"1" \
	"openai/meta/test-github-model" \
	"https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference"

run_gate_case "github-models-mistral-prefix-with-api-base-succeeds" \
	"openai/mistral-ai/test-github-model" \
	"" \
	"0" \
	"scan ok" \
	"1" \
	"openai/mistral-ai/test-github-model" \
	"https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference"

run_gate_case "github-models-fallback-requires-api-base" \
	"vertex_ai/missing-primary" \
	"openai/openai/gpt-5.4" \
	"2" \
	"GitHub Models Strix scans require LLM_API_BASE_FILE" \
	"1" \
	"vertex_ai/missing-primary" \
	"<unset>" \
	"vertex_ai" \
	""

run_gate_case "github-models-fallback-success" \
	"vertex_ai/missing-primary" \
	"github_models/deepseek/deepseek-v3-0324 github_models/deepseek/deepseek-r1-0528" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'github_models/deepseek/deepseek-v3-0324' in [0-9]+s\\." \
	"2" \
	"vertex_ai/missing-primary|openai/deepseek/deepseek-v3-0324" \
	"<unset>|https://models.github.ai/inference" \
	"vertex_ai" \
	"https://models.github.ai/inference" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	0

run_gate_case "github-models-token-limit-fallback-success" \
	"openai/gpt-5" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'github_models/deepseek/deepseek-v3-0324' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5|openai/deepseek/deepseek-v3-0324" \
	"https://models.github.ai/inference|https://models.github.ai/inference" \
	"openai" \
	"https://models.github.ai/inference" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"github_models/deepseek/deepseek-v3-0324 github_models/deepseek/deepseek-r1-0528"

# Direct-OpenAI primary hits a quota/rate-limit error and falls back to a
# GitHub Models candidate, switching both the API base and the API key per
# model (the fake strix asserts the key swap and exits nonzero on a leak).
run_gate_case "openai-direct-quota-github-models-fallback-success" \
	"openai_direct/gpt-5.6-luna" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'github_models/openai/o3' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5.6-luna|openai/o3" \
	"<unset>|https://models.github.ai/inference" \
	"vertex_ai" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"github_models/openai/o3"

# Strix currently reaches LiteLLM with a sampling default and exposes no
# documented generation-parameter override. Azure reasoning deployments reject
# that temperature before Strix's internal model-group fallback can run, so the
# trusted outer gate must try its already-configured distinct provider.
run_gate_case "openai-direct-unsupported-temperature-github-models-fallback-success" \
	"openai_direct/gpt-5.6-sol" \
	"" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'github_models/openai/o3' in [0-9]+s\\." \
	"2" \
	"openai/gpt-5.6-sol|openai/o3" \
	"<unset>|https://models.github.ai/inference" \
	"vertex_ai" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"github_models/openai/o3"

# Cross-line assembly is deliberately rejected: target/source text cannot
# manufacture a provider capability signal from independent log lines.
run_gate_case "openai-direct-unsupported-temperature-split-lines-nonrecoverable" \
	"openai_direct/gpt-5.6-sol" \
	"" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"openai/gpt-5.6-sol" \
	"<unset>" \
	"vertex_ai" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"github_models/openai/o3"

# Repository-derived text containing a valid provider error as a substring
# must not trigger credential-bearing fallback.
run_gate_case "openai-direct-unsupported-temperature-prefixed-target-nonrecoverable" \
	"openai_direct/gpt-5.6-sol" \
	"github_models/openai/o3" \
	"1" \
	"Strix quick scan failed with a non-recoverable error." \
	"1" \
	"openai/gpt-5.6-sol" \
	"https://example.invalid" \
	"vertex_ai"

# Cross-provider fallbacks must switch both the API key and endpoint. Reusing
# NVIDIA credentials or its API base makes a normalized direct-OpenAI model
# fail before producing security evidence.
run_nvidia_openai_direct_fallback_case
run_nvidia_openai_direct_fallback_case \
	"nvidia-openai-direct-fallback-missing-key-fails-closed" \
	"1" \
	"STRIX_OPENAI_FALLBACK_KEY_FILE is unavailable" \
	"1" \
	"nvidia_nim/nvidia/primary" \
	"https://integrate.api.nvidia.com/v1"
run_nvidia_openai_direct_fallback_case \
	"nvidia-openai-direct-missing-key-next-fallback-success" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'nvidia_nim/nvidia/fallback-two' in [0-9]+s\\." \
	"2" \
	"nvidia_nim/nvidia/primary|nvidia_nim/nvidia/fallback-two" \
	"https://integrate.api.nvidia.com/v1|https://integrate.api.nvidia.com/v1" \
	"openai-direct/gpt-5.6-luna nvidia_nim/nvidia/fallback-two"

run_gate_case "github-models-fallback-success-deepseek-v3" \
	"vertex_ai/missing-primary" \
	"github_models/deepseek/deepseek-r1-0528 github_models/deepseek/deepseek-v3-0324" \
	"0" \
	"REGEX:Strix quick scan succeeded with fallback model 'github_models/deepseek/deepseek-v3-0324' in [0-9]+s\\." \
	"3" \
	"vertex_ai/missing-primary|openai/deepseek/deepseek-r1-0528|openai/deepseek/deepseek-v3-0324" \
	"<unset>|https://models.github.ai/inference|https://models.github.ai/inference" \
	"vertex_ai" \
	"https://models.github.ai/inference" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	"" \
	0

# Endpoint only exists in excluded directories (.git/, node_modules/). Even if
# the source does not corroborate it, a threshold report remains blocking and
# requires human remediation/triage rather than silent fallback.
run_gate_case "endpoint-in-excluded-dir" \
	"vertex_ai/excluded-dir-primary" \
	"vertex_ai/fallback-one vertex_ai/fallback-two" \
	"1" \
	"Unable to map Strix findings to changed files; failing closed for pull request." \
	"1" \
	"vertex_ai/excluded-dir-primary" \
	"<unset>"

# Whitespace-only fallback models: STRIX_VERTEX_FALLBACK_MODELS set to "  ".
# This bypasses the :- default but produces an empty array from read -r -a.
# The gate should emit "No fallback models configured" (not the misleading
# "All configured fallback models are the same as the primary model").
run_gate_case "empty-fallback-models" \
	"vertex_ai/empty-fb-primary" \
	"   " \
	"1" \
	"No fallback models configured" \
	"1" \
	"vertex_ai/empty-fb-primary" \
	"<unset>"

if [ "$FAILURES" -ne 0 ]; then
	echo "test_strix_quick_gate: ${FAILURES} failure(s)" >&2
	exit 1
fi

echo "test_strix_quick_gate: PASS"
