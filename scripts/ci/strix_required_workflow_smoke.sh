#!/usr/bin/env bash
set -euo pipefail

script_dir="$(
	CDPATH=''
	cd -P -- "$(dirname -- "$0")"
	pwd -P
)"
repo_root="$(
	CDPATH=''
	cd -P -- "$script_dir/../.."
	pwd -P
)"
workflow_file="$repo_root/.github/workflows/strix.yml"
gate_script="$repo_root/scripts/ci/strix_quick_gate.sh"
full_gate_test="$repo_root/scripts/ci/test_strix_quick_gate.sh"

failures=0

record_failure() {
	echo "FAIL: $1" >&2
	failures=$((failures + 1))
}

assert_file_contains() {
	local file_path="$1"
	local needle="$2"
	local message="$3"

	if ! grep -Fq -- "$needle" "$file_path"; then
		record_failure "$message (missing '$needle')"
	fi
}

assert_file_not_contains() {
	local file_path="$1"
	local needle="$2"
	local message="$3"

	if grep -Fq -- "$needle" "$file_path"; then
		record_failure "$message (unexpected '$needle')"
	fi
}

if ! bash -n "$gate_script" "$full_gate_test"; then
	record_failure "Strix gate scripts must pass bash syntax checks"
fi

checkout_count="$(grep -Fc "uses: actions/checkout@" "$workflow_file" || true)"
if [ "$checkout_count" != "1" ]; then
	record_failure "Strix workflow must use actions/checkout exactly once for central trusted source checkout"
fi

assert_file_contains "$workflow_file" "Resolve trusted Strix source ref" "Strix workflow resolves central trusted source"
assert_file_contains "$workflow_file" "workflow_repository" "Strix workflow reads required-workflow repository identity"
assert_file_contains "$workflow_file" "workflow_sha" "Strix workflow prefers required-workflow source SHA"
assert_file_contains "$workflow_file" "Checkout trusted Strix source" "Strix workflow checks out central source"
assert_file_contains "$workflow_file" 'repository: ${{ steps.trusted_source.outputs.repository }}' "Strix workflow checks out resolved central repository"
assert_file_contains "$workflow_file" 'ref: ${{ steps.trusted_source.outputs.ref }}' "Strix workflow checks out resolved central ref"
assert_file_contains "$workflow_file" "Materialize target workspace" "Strix workflow separates target workspace from trusted source"
assert_file_contains "$workflow_file" 'STRIX_REPO_ROOT:' "Strix workflow passes target root explicitly"
assert_file_contains "$workflow_file" 'bash "$TRUSTED_STRIX_GATE"' "Strix workflow executes central Strix gate"
assert_file_contains "$workflow_file" "Self-test Strix required workflow contract" "Strix workflow uses bounded required-path smoke test"
assert_file_contains "$workflow_file" 'bash "$TRUSTED_STRIX_REQUIRED_SMOKE"' "Strix workflow executes bounded smoke test"
assert_file_contains "$workflow_file" "timeout-minutes: 2" "Strix required-path smoke test has a short timeout"
assert_file_contains "$workflow_file" 'statuses: write' "Strix workflow can publish manual PR evidence status"
assert_file_contains "$workflow_file" 'context="strix"' "Strix workflow publishes the strix commit status context"
assert_file_not_contains "$workflow_file" 'repository: ${{ github.repository }}' "Strix workflow must not checkout target repository with actions/checkout in privileged context"
assert_file_not_contains "$workflow_file" 'bash "$TRUSTED_STRIX_GATE_TEST"' "Strix required path must not execute the full long-form gate harness"
assert_file_contains "$gate_script" "STRIX_REPO_ROOT" "Strix gate consumes explicit target root"
assert_file_contains "$gate_script" "STRIX_REPO_ROOT must reference a regular directory" "Strix gate rejects invalid or symlink target roots"
assert_file_contains "$gate_script" "TARGET_PATH_IS_INTERNAL_PR_SCOPE" "Strix gate separates generated PR scopes from user paths"
assert_file_contains "$gate_script" "NPM_CONFIG_IGNORE_SCRIPTS" "Strix gate disables npm lifecycle scripts"
assert_file_contains "$full_gate_test" "assert_strix_workflow_pr_trigger_hardened" "Full Strix harness remains available outside the required path"

if [ "$failures" -ne 0 ]; then
	echo "Strix required workflow smoke test failed with $failures failure(s)." >&2
	exit 1
fi

echo "Strix required workflow smoke test passed."
