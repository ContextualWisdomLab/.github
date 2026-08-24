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
workflow_root="${TRUSTED_WORKSPACE:-$repo_root}"
if [ ! -f "$workflow_root/.github/workflows/strix.yml" ]; then
	workflow_root="$repo_root"
fi
workflow_file="$workflow_root/.github/workflows/strix.yml"
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

assert_status_permissions_scoped() {
	local output

	if ! output="$(python3 - "$workflow_file" 2>&1 <<'PY'
from pathlib import Path
import re
import sys

workflow = Path(sys.argv[1])
lines = workflow.read_text(encoding="utf-8").splitlines()

try:
    permissions_index = lines.index("permissions:")
    jobs_index = lines.index("jobs:")
except ValueError as exc:
    print(f"Strix workflow is missing the required top-level block: {exc}", file=sys.stderr)
    raise SystemExit(1)

top_level_permissions: dict[str, str] = {}
for line in lines[permissions_index + 1 : jobs_index]:
    permission_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*([A-Za-z]+)\s*$", line)
    if permission_match:
        top_level_permissions[permission_match.group(1)] = permission_match.group(2)

expected_top_level_permissions = {
    "actions": "read",
    "contents": "read",
    "models": "read",
}
if top_level_permissions != expected_top_level_permissions:
    print(
        "Strix workflow top-level permissions must be exactly read-only actions, contents, and models; "
        f"found: {top_level_permissions}",
        file=sys.stderr,
    )
    raise SystemExit(1)

allowed_jobs = {
    "cancel-closed-pr-runs",
    "publish-manual-pr-evidence-status",
    "strix",
}
expected_job_permissions = {
    "cancel-closed-pr-runs": {},
    # Status writes use exchanged app/secret tokens, never this job's
    # GITHUB_TOKEN; the historical required-workflow contract pins
    # statuses: write to the strix scan job alone.
    "publish-manual-pr-evidence-status": {
        "id-token": "write",
    },
    "strix": {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "models": "read",
        "statuses": "write",
    },
}
job_names: list[str] = []
job_permissions: dict[str, dict[str, str]] = {}
current_job = ""
inside_permissions = False
for line in lines[jobs_index + 1 :]:
    job_match = re.match(r"^  ([A-Za-z0-9_-]+):$", line)
    if job_match:
        current_job = job_match.group(1)
        if current_job in job_names:
            print(f"Strix workflow defines duplicate job '{current_job}'.", file=sys.stderr)
            raise SystemExit(1)
        job_names.append(current_job)
        job_permissions[current_job] = {}
        inside_permissions = False
        continue
    if not current_job:
        continue
    permissions_match = re.match(r"^    permissions:\s*(.*)$", line)
    if permissions_match:
        inline_permissions = permissions_match.group(1).strip()
        inside_permissions = not inline_permissions
        if inline_permissions and inline_permissions != "{}":
            job_permissions[current_job] = {"__invalid__": inline_permissions}
        continue
    if not inside_permissions:
        continue
    permission_match = re.match(r"^      ([A-Za-z0-9_-]+):\s*([A-Za-z]+)\s*$", line)
    if permission_match:
        job_permissions[current_job][permission_match.group(1)] = permission_match.group(2)
        continue
    if line.strip():
        inside_permissions = False

unknown_jobs = sorted(set(job_names) - allowed_jobs)
missing_jobs = sorted(allowed_jobs - set(job_names))
if unknown_jobs or missing_jobs:
    print(
        "Strix workflow jobs must be exactly the approved required jobs; "
        f"unknown: {unknown_jobs or 'none'}, missing: {missing_jobs or 'none'}",
        file=sys.stderr,
    )
    raise SystemExit(1)

if job_permissions != expected_job_permissions:
    print(
        "Strix workflow job permissions do not match the approved contract; "
        f"found: {job_permissions}",
        file=sys.stderr,
    )
    raise SystemExit(1)

unpinned_actions: list[str] = []
for line_number, line in enumerate(lines, start=1):
    action_match = re.match(r"^\s*uses:\s*([^\s#]+)", line)
    if action_match and not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-fA-F]{40}",
        action_match.group(1),
    ):
        unpinned_actions.append(f"{line_number}:{action_match.group(1)}")

if unpinned_actions:
    print(
        "Strix workflow actions must be pinned to full commit SHAs; found: "
        + ", ".join(unpinned_actions),
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
		)"; then
		record_failure "$output"
	fi
}

if ! bash -n "$gate_script" "$full_gate_test"; then
	record_failure "Strix gate scripts must pass bash syntax checks"
fi

echo "Checking Strix workflow contract in $workflow_file"

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
assert_file_not_contains "$workflow_file" "      - name: Materialize central Strix dependency lock from PR head" "Strix workflow never installs dependencies selected by a PR head"
assert_file_not_contains "$workflow_file" 'show "$PR_HEAD_SHA:requirements-strix-ci-hashes.txt"' "Strix workflow never copies a PR-controlled executable dependency lock"
assert_file_contains "$workflow_file" "requirements-strix-ci-hashes.txt" "Strix workflow installs from the central trusted hashed requirements lock"
assert_file_contains "$workflow_file" 'trusted_lock_blob="$(git rev-parse "HEAD:$trusted_lock")"' "Strix workflow binds its dependency lock to the trusted workflow commit"
assert_file_contains "$workflow_file" '--only-binary=:all:' "Strix workflow installs only hash-verified wheels"
assert_file_contains "$workflow_file" 'Verify Strix sandbox credential boundary' "Strix workflow verifies its target-command sandbox before loading provider credentials"
assert_file_contains "$workflow_file" 'sandbox_environment - allowed_sandbox_environment' "Strix workflow rejects unreviewed host environment keys in the target-command sandbox"
assert_file_contains "$workflow_file" "Materialize target workspace" "Strix workflow separates target workspace from trusted source"
assert_file_contains "$workflow_file" 'STRIX_REPO_ROOT:' "Strix workflow passes target root explicitly"
assert_file_contains "$workflow_file" 'bash "$TRUSTED_STRIX_GATE"' "Strix workflow executes central Strix gate"
assert_file_contains "$workflow_file" "Self-test Strix required workflow contract" "Strix workflow uses bounded required-path smoke test"
assert_file_contains "$workflow_file" 'bash "$TRUSTED_STRIX_REQUIRED_SMOKE"' "Strix workflow executes bounded smoke test"
assert_file_contains "$workflow_file" "timeout-minutes: 2" "Strix required-path smoke test has a short timeout"
assert_status_permissions_scoped
assert_file_contains "$workflow_file" 'context="strix"' "Strix workflow publishes the strix commit status context"
assert_file_contains "$workflow_file" "Existing current-run Strix success status is already present" "Strix manual follow-up status publisher accepts already-published same-run evidence"
assert_file_not_contains "$workflow_file" 'repository: ${{ github.repository }}' "Strix workflow must not checkout target repository with actions/checkout in privileged context"
assert_file_not_contains "$workflow_file" 'bash "$TRUSTED_STRIX_GATE_TEST"' "Strix required path must not execute the full long-form gate harness"
assert_file_not_contains "$workflow_file" "- name: Prepare GitHub Models fallback credentials" "Strix workflow does not define a GitHub Models fallback credential step (a compatibility comment for the retired needle is allowed)"
assert_file_contains "$gate_script" "STRIX_GITHUB_MODELS_KEY_FILE" "Strix gate supports GitHub Models fallback credentials for cross-provider fallback"
assert_file_contains "$gate_script" "STRIX_REPO_ROOT" "Strix gate consumes explicit target root"
assert_file_contains "$gate_script" "STRIX_REPO_ROOT must reference a regular directory" "Strix gate rejects invalid or symlink target roots"
assert_file_contains "$gate_script" "TARGET_PATH_IS_INTERNAL_PR_SCOPE" "Strix gate separates generated PR scopes from user paths"
assert_file_contains "$gate_script" "NPM_CONFIG_IGNORE_SCRIPTS" "Strix gate disables npm lifecycle scripts"
assert_file_contains "$full_gate_test" "assert_strix_workflow_pr_trigger_hardened" "Full Strix harness remains available outside the required path"

assert_file_contains "$workflow_file" "nvidia_nim/nvidia/nemotron-3-super-120b-a12b" "Strix defaults public scans to the current hosted NVIDIA NIM model"
assert_file_contains "$workflow_file" "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 openai_direct/gpt-5.6-luna" "Strix tries another NVIDIA hosted model before falling back to direct OpenAI"
if grep -Eq '^[[:space:]]+STRIX_FALLBACK_MODELS:.*openai-direct/gpt-5\.6-luna' "$workflow_file"; then
	record_failure "Strix active fallback configuration uses the retired direct-OpenAI provider prefix"
fi
assert_file_not_contains "$workflow_file" "github_models/openai/o3" "Strix fallback list must not depend on GitHub Models, which is in platform-wide retirement"
assert_file_contains "$workflow_file" "Nvidia_nimException" "Strix workflow recognizes provider-scoped NVIDIA NIM failures"
assert_file_contains "$gate_script" "is_nvidia_nim_not_found_error" "Strix gate classifies NVIDIA NIM model-catalog 404s"

if [ "$failures" -ne 0 ]; then
	echo "Strix required workflow smoke test failed with $failures failure(s)." >&2
	exit 1
fi

echo "Strix required workflow smoke test passed."
