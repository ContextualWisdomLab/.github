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

required_workflow_bootstrap_has_if() {
	local bootstrap_file="$1"

	awk '/^  required-workflow-bootstrap:$/{p=1; print; next} p && /^  [A-Za-z0-9_-]+:/{exit} p' "$bootstrap_file" |
		grep '^[[:space:]]*if:' >/dev/null
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
	assert_file_contains "$workflow_file" "admit-current-head:" "strix workflow admits the live pull request head before provider execution"
	assert_file_contains "$workflow_file" "needs: [changed-scope, admit-current-head]" "strix provider queue waits for live-head admission"
	assert_file_contains "$workflow_file" 'strix-security-scan-${{' "strix workflow coalesces by repository and PR before job admission"
	assert_file_not_contains "$workflow_file" 'strix-security-scan-${{ needs.admit-current-head.outputs.target_repository }}-${{' "strix concurrency is not delayed until job admission"
	assert_file_contains "$workflow_file" "format('push-{0}', github.ref_name)" "strix push scans coalesce per protected branch instead of one group per run id"
	assert_file_contains "$workflow_file" "cancel-superseded-pr-runs:" "strix workflow runs superseded-head cleanup outside the provider scan queue"
	assert_file_not_contains "$workflow_file" "format('closed-pr-{0}-{1}'" "strix cleanup does not need a second concurrency queue"
	assert_file_contains "$workflow_file" 'echo "pr_number=${GITHUB_RUN_ID}"' "strix workflow preserves independent push and schedule evidence"
	assert_file_contains "$workflow_file" "github.event.client_payload.target_repository ||" "strix manual dispatch concurrency scopes to the target repository when provided"
	assert_file_contains "$workflow_file" "github.repository }}" "strix workflow falls back to the workflow repository when no target repository is provided"
	assert_file_contains "$workflow_file" "github.event.pull_request.number ||" "strix workflow scopes native evidence to the pull request"
	assert_file_contains "$workflow_file" "github.event.client_payload.pr_number ||" "strix workflow scopes dispatched evidence to the same pull request"
	assert_file_not_contains "$workflow_file" "format('pr-{0}-{1}'" "strix workflow does not keep stale head-specific concurrency groups"
	assert_file_contains "$workflow_file" "cancel-in-progress: true" "strix workflow cancels superseded same-PR scans"
	assert_file_not_contains "$workflow_file" "queue: max" "strix workflow uses only supported GitHub concurrency keys"
	assert_file_not_contains "$workflow_file" "format('{0}-{1}-{2}', github.event_name," "strix workflow unifies pull-request and repository-dispatch evidence for one PR"
	assert_file_contains "$workflow_file" "Strix event does not match the live pull request head; skipping stale evidence." "strix workflow rejects stale events before provider concurrency"
	assert_file_contains "$workflow_file" "refs/pull/<n>/head has already advanced before this queued run starts" "strix workflow documents stale scan queue avoidance"
	status_token_count="$(grep -c '^[[:space:]]*GITHUB_STATUS_TOKEN:' "$workflow_file")"
	assert_equals "1" "$status_token_count" "strix workflow defines GITHUB_STATUS_TOKEN once so GitHub can parse repository_dispatch"
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
	assert_file_contains "$workflow_file" "Materialize central Strix dependency lock from PR head" "strix workflow validates central same-repo lock-file PRs against the PR head lock"
	assert_file_contains "$workflow_file" "github.event.pull_request.head.repo.full_name == 'ContextualWisdomLab/.github'" "strix workflow limits central lock materialization to same-repository PR heads"
	assert_file_contains "$workflow_file" 'git -C "$TRUSTED_WORKSPACE" show "$PR_HEAD_SHA:requirements-strix-ci-hashes.txt"' "strix workflow copies only the hashed requirements lock from the PR head"
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
	assert_file_contains "$workflow_file" "Resolve target repository visibility" "strix workflow resolves target privacy for the gateway ZDR policy"
	assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" "strix workflow passes repository privacy to the contextual-orchestrator ZDR policy"
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
	assert_file_contains "$workflow_file" "Provision contextual-orchestrator Strix sidecar" "strix workflow provisions the central contextual-orchestrator sidecar"
	assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_BASE_URL" "strix workflow uses the sidecar base URL"
	assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_TOKEN" "strix workflow uses the sidecar token"
	assert_file_not_contains "$workflow_file" "timeout-minutes: 200" "strix workflow job must not cap model inference"
	assert_file_not_contains "$workflow_file" "timeout-minutes: 170" "strix scan step must not cap model inference"
	assert_file_contains "$workflow_file" 'export LLM_TIMEOUT=0' "strix disables the model client inference timeout"
	assert_file_contains "$workflow_file" 'export STRIX_MEMORY_COMPRESSOR_TIMEOUT=0' "strix disables the memory-compressor inference timeout"
	assert_file_contains "$workflow_file" 'export STRIX_PROCESS_TIMEOUT_SECONDS=0' "strix disables the scanner process timeout"
	assert_file_contains "$workflow_file" 'export STRIX_TOTAL_TIMEOUT_SECONDS=0' "strix disables the total scanner timeout"
	assert_file_contains "$workflow_file" 'Error code:[[:space:]]*500[^[:cntrl:]]*internal_error' "strix workflow retries contextual-orchestrator internal provider failures"
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
	assert_file_contains "$workflow_file" "EVENT_REPOSITORY_VISIBILITY:" "strix workflow uses trusted event visibility before cross-repository API lookup"
	assert_file_contains "$workflow_file" "PUBLIC | public) is_private=false" "strix workflow accepts GitHub's lowercase public visibility"
	assert_file_contains "$workflow_file" "PRIVATE | private | INTERNAL | internal) is_private=true" "strix workflow keeps private and internal repositories off public-only providers"
	assert_file_contains "$workflow_file" '(.visibility // "" | ascii_downcase) as $visibility' "strix dispatch visibility maps the authoritative API visibility instead of the lossy private boolean"
	assert_file_not_contains "$workflow_file" "gh api \"repos/\${TARGET_REPOSITORY}\" --jq '.private'" "strix dispatch visibility does not misclassify internal repositories through the private boolean"
	assert_file_contains "$REPO_ROOT/tests/test_strix_repository_visibility_contract.py" "test_dispatch_api_visibility_preserves_internal_privacy" "strix visibility contract executes public, private, and internal dispatch fixtures"
	assert_file_contains "$workflow_file" 'STRIX_MODEL: ${{ steps.gate.outputs.strix_model }}' "strix workflow propagates the gate-selected fallback model to the scanner"
	assert_file_not_contains "$workflow_file" "secrets.STRIX_LLM ||" "strix workflow must not let the legacy STRIX_LLM secret override PR defaults"
	assert_file_contains "$workflow_file" "Strix model overrides are limited to contextual-orchestrator/orchestrator/free" "strix workflow rejects non-gateway model overrides"
	assert_file_contains "$workflow_file" "STRIX_LLM must select contextual-orchestrator/orchestrator/free" "strix workflow accepts only the gateway model"
	assert_file_contains "$workflow_file" 'STRIX_FALLBACK_MODELS: ""' "strix workflow disables external fallback models"
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
	# contextual-orchestrator#925 (merged) fixed the gateway's rejection of
	# stream_options.include_usage=true alongside tools -- the actual root
	# cause #1448's LLM_DISABLE_STREAMING opt-in routed around. That opt-in is
	# reverted (this PR); these guard against it silently reappearing.
	assert_file_not_contains "$GATE_SCRIPT" 'STRIX_CHILD_DISABLE_STREAMING="$strix_disable_streaming"' "strix gate no longer threads a streaming opt-in through to the child process environment"
	assert_file_not_contains "$GATE_SCRIPT" 'child_env["LLM_DISABLE_STREAMING"] = "true"' "strix gate no longer disables Strix's own SDK streaming for the contextual-orchestrator gateway"
	assert_file_contains "$GATE_SCRIPT" '[[ "$normalized_changed_file" =~ ^backend/.+\.py$ ]]' "strix gate detects nested backend Python files for PR-scoped import context"
	assert_file_contains "$GATE_SCRIPT" '[[ "$normalized_changed_file" == scripts/ci/test_*.sh || "$normalized_changed_file" == scripts/ci/*_test.sh ]]' "strix gate excludes large CI test harness scripts from model scan input"
	assert_file_contains "$GATE_SCRIPT" "Materialized PR-head changed-file scope for Strix scan" "strix gate avoids copying the full PR head tree into privileged scan targets by default"
	assert_file_contains "$GATE_SCRIPT" "sanitize_known_strix_report_warnings" "strix gate sanitizes only known internal Strix report warnings"
	assert_file_contains "$GATE_SCRIPT" 'MODEL QUALITY WARNING' "strix gate accepts the scanner's informational fallback-model banner"
	assert_file_contains "$GATE_SCRIPT" 'unauthenticated requests to the HF Hub' "strix gate accepts the scanner dependency's non-fatal download warning"
	assert_file_not_contains "$GATE_SCRIPT" 'known_scanner_warning = re.compile(r".*Warn' "strix gate does not broadly suppress warning-class evidence"
	assert_file_contains "$GATE_SCRIPT" "vulnerability_file_reports_documented_opencode_env_api_key_reference" "strix gate fact-checks documented OpenCode env apiKey references before accepting secret-templating reports"
	assert_file_contains "$GATE_SCRIPT" "iter_report_logs" "strix gate enumerates report logs through a safe walker"
	assert_file_contains "$GATE_SCRIPT" "os.walk(root, topdown=True, followlinks=False)" "strix gate does not recurse into symlinked report directories"
	assert_file_not_contains "$GATE_SCRIPT" 'root.rglob("*.log")' "strix gate avoids recursive pathlib glob traversal for report logs"
	assert_file_contains "$GATE_SCRIPT" "has_strix_report_failure_signal" "strix gate fails closed on warning-class Strix report artifacts"
	assert_file_not_contains "$workflow_file" "ignore::UserWarning" "strix workflow must not blanket-suppress all UserWarning output"
	assert_file_contains "$GATE_SCRIPT" "vulnerability_file_reports_generic_github_actions_workflow_insecurity" "strix gate fact-checks generic GitHub Actions workflow security reports before accepting whole-file claims"
	assert_file_not_contains "$workflow_file" "vertex_ai/* | vertex_ai_beta/*" "strix workflow must not accept arbitrary Vertex models"
	assert_file_not_contains "$workflow_file" "github/gpt-4o" "strix workflow must not default to an unsupported GitHub Models alias"
	assert_file_contains "$workflow_file" "provider_mode=contextual_orchestrator" "strix workflow selects the contextual-orchestrator provider mode"
	assert_file_not_contains "$workflow_file" "provider_mode=openai_direct" "strix workflow has no direct OpenAI provider mode"
	assert_file_not_contains "$workflow_file" "provider_mode=github_models" "strix workflow has no GitHub Models provider mode"
	assert_file_not_contains "$workflow_file" "provider_mode=openrouter" "strix workflow has no OpenRouter provider mode"
	assert_file_not_contains "$workflow_file" "provider_mode=nvidia_nim" "strix workflow has no direct NVIDIA provider mode"
	assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_TOKEN" "strix workflow keeps the gateway token in provider-scoped key material"
	assert_file_not_contains "$workflow_file" "secrets.LLM_API_KEY" "strix workflow must not expose the legacy generic LLM secret"
	assert_file_contains "$workflow_file" 'PROVIDER_MODE: ${{ steps.gate.outputs.provider_mode }}' "strix workflow passes provider mode through env"
	assert_file_contains "$workflow_file" 'if [ "$PROVIDER_MODE" != "contextual_orchestrator" ]; then' "strix workflow fails closed if the provider mode changes"
	assert_file_contains "$workflow_file" "STRIX_REASONING_EFFORT: none" "strix gateway free-pool scans use provider-neutral reasoning effort"
	assert_file_contains "$workflow_file" "llm_api_key_file" "strix workflow writes the gateway token into the trusted input file"
	assert_file_contains "$workflow_file" "STRIX_LLM_DEFAULT_PROVIDER: contextual_orchestrator" "strix workflow sends Strix through the gateway provider"
	assert_file_contains "$workflow_file" "Prepare contextual-orchestrator API base" "strix workflow prepares the gateway API base"
	assert_file_contains "$workflow_file" "http://127.0.0.1:18080" "strix workflow pins the sidecar loopback origin"
	assert_file_contains "$workflow_file" "LLM_API_BASE_FILE" "strix workflow passes the gateway API base through a trusted input file"
	assert_file_not_contains "$workflow_file" "https://models.github.ai/inference" "strix workflow has no direct GitHub Models endpoint"
	assert_file_not_contains "$workflow_file" "https://openrouter.ai/api/v1" "strix workflow has no direct OpenRouter endpoint"
	assert_file_not_contains "$workflow_file" "https://integrate.api.nvidia.com/v1" "strix workflow has no direct NVIDIA endpoint"
	assert_file_not_contains "$workflow_file" "https://api.openai.com/v1" "strix workflow has no direct OpenAI endpoint"
	assert_file_not_contains "$workflow_file" "nvidia/llama-3.3-nemotron-super-49b-v1.5" "strix workflow does not pin the retired NVIDIA fallback"
	assert_file_contains "$GATE_SCRIPT" "STRIX_GITHUB_MODELS_KEY_FILE" "strix gate reads the optional GitHub Models fallback key file"
	assert_file_contains "$GATE_SCRIPT" "STRIX_GITHUB_MODELS_API_BASE_FILE" "strix gate routes github_models fallback models through the GitHub Models endpoint"
	assert_file_not_contains "$workflow_file" 'github_models/deepseek/deepseek-r1-0528 | github_models/deepseek/deepseek-v3-0324)' "strix workflow keeps DeepSeek GitHub Models restricted to fallback-only routing"
	assert_file_not_contains "$workflow_file" "gemini/gemini-pro-3.1-preview" "strix workflow must not default to an unsupported Gemini API model"
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

assert_strix_evidence_binding_contract() {
	assert_file_contains "$GATE_SCRIPT" "sanitize_remediation_evidence_claims" "strix gate sanitizes false already-applied remediation claims"
	assert_file_contains "$GATE_SCRIPT" 'scripts/ci/strix_evidence_binding.py' "strix gate binds remediation evidence through the tested Python binder"
	assert_file_contains "$GATE_SCRIPT" "evidence_scope=pr_delta" "strix gate labels PR-delta findings with authenticated provenance"
	assert_file_contains "$GATE_SCRIPT" "evidence_scope=repository_baseline" "strix gate labels unchanged-path findings as repository_baseline"
	assert_file_contains "$REPO_ROOT/scripts/ci/strix_evidence_binding.py" 'PR_DELTA = "pr_delta"' "strix evidence binder defines pr_delta scope"
	assert_file_contains "$REPO_ROOT/scripts/ci/strix_evidence_binding.py" 'REMEDIATION_FAILED = "remediation_failed"' "strix evidence binder fails closed on apply_patch misses"
	assert_file_contains "$REPO_ROOT/tests/test_strix_evidence_binding.py" "completely_base_identical_source_finding" "strix evidence binder has a RED fixture for base-identical findings"
	assert_file_contains "$REPO_ROOT/tests/test_strix_evidence_binding.py" "apply_patch_miss_rejects_already_applied_claim" "strix evidence binder has a RED fixture for apply_patch misses"
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

assert_opencode_review_uses_codegraph_and_contextual_orchestrator() {
	local bootstrap_file="$REPO_ROOT/.github/workflows/opencode-review.yml"
	local workflow_file="$REPO_ROOT/.github/workflows/opencode-review-dispatch.yml"
	local comment_helpers_file="$REPO_ROOT/scripts/ci/opencode_review_comment_helpers.sh"
	local opencode_config="$REPO_ROOT/opencode.jsonc"

	assert_file_contains "$bootstrap_file" "pull_request_target:" "opencode required workflow loads its metadata-only bootstrap from the protected base ref"
	assert_file_contains "$bootstrap_file" "types: [opened, synchronize, reopened, ready_for_review, converted_to_draft, closed]" "opencode required workflow reacts to current PR head changes, mid-poll draft conversion, and closed-PR cleanup"
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
	# Match against the full awk output rather than letting `grep -q` close its
	# end of the pipe on the first match: a large bootstrap job's piped output
	# can exceed the OS pipe buffer, and `grep -q`'s early exit can SIGPIPE the
	# still-writing awk producer. Under `set -o pipefail` (top of this file)
	# that SIGPIPE (128+13=141) outranks grep's own 0 exit, so the `if`
	# incorrectly takes the "no match" branch even though the forbidden `if:`
	# key was found. Dropping `-q` makes grep read to completion, so it never
	# closes the pipe early and the real exit status is preserved.
	if required_workflow_bootstrap_has_if "$bootstrap_file"; then
		record_failure "opencode required workflow bootstrap must not depend on required-workflow event payload fields"
	fi
	local large_bootstrap_fixture
	local fixture_line
	large_bootstrap_fixture="$(mktemp)"
	{
		printf '%s\n' 'jobs:' '  required-workflow-bootstrap:' '    if: forbidden'
		for ((fixture_line = 0; fixture_line < 20000; fixture_line++)); do
			printf '%s\n' '    # padding forces the producer past the pipe buffer'
		done
		printf '%s\n' '  next-job:' '    runs-on: ubuntu-latest'
	} >"$large_bootstrap_fixture"
	if ! required_workflow_bootstrap_has_if "$large_bootstrap_fixture"; then
		record_failure "opencode required workflow bootstrap condition detection must survive a job block larger than the pipe buffer"
	fi
	rm -f "$large_bootstrap_fixture"
	assert_file_contains "$workflow_file" 'needs.validate-pr-metadata.outputs.target_repository' "opencode review scopes concurrency by the live validated target repository"
	assert_file_contains "$workflow_file" 'needs.validate-pr-metadata.outputs.pr_number || github.run_id' "opencode review scopes concurrency by the live validated PR with a non-PR fallback"
	assert_file_not_contains "$workflow_file" "format('pr-{0}-{1}'" "opencode review does not keep stale head-specific concurrency groups"
	assert_file_contains "$workflow_file" 'opencode-review-${{' "opencode review uses the workflow-repository-PR group prefix"
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
	assert_file_contains "$REPO_ROOT/scripts/ci/pr_review_merge_scheduler_core.py" '"pr_head_ref":' "central scheduler repository_dispatch carries the PR head branch required by current-head code-scanning verification"
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
	assert_file_not_contains "$workflow_file" 'ref: ${{ github.event.pull_request.head.sha || github.event.client_payload.pr_head_sha || github.sha }}' "opencode review must not check