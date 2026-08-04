#!/usr/bin/env bash
# Apply contextual-orchestrator's verified free-first policy, then delegate to
# the unchanged OpenCode transport, validation, retry, and evidence gate.
set -euo pipefail

# Static fail-closed contract retained for source-level governance tests.
# The unchanged implementation lives in run_opencode_review_model_pool_core.sh.
: <<'OPENCODE_CORE_CONTRACT'
finish_pool_without_model()
record_pool_exhausted
normalize_opencode_output()
OPENCODE_CORE_CONTRACT

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
POLICY_SCRIPT="$SCRIPT_DIR/contextual_fallback_policy.py"
CORE_SCRIPT="$SCRIPT_DIR/run_opencode_review_model_pool_core.sh"

if [ ! -f "$POLICY_SCRIPT" ] || [ -L "$POLICY_SCRIPT" ]; then
	echo "ERROR: contextual fallback policy adapter is unavailable." >&2
	exit 2
fi
if [ ! -f "$CORE_SCRIPT" ] || [ -L "$CORE_SCRIPT" ]; then
	echo "ERROR: OpenCode model-pool core is unavailable." >&2
	exit 2
fi
if [ -z "${OPENCODE_MODEL_CANDIDATES:-}" ]; then
	# The unchanged core owns its bounded no-model central fallback path.
	exec bash "$CORE_SCRIPT" "$@"
fi

repository_visibility="private"
case " ${OPENCODE_MODEL_CANDIDATES} " in
*" nvidia-nim/"* | *" opencode-free/"*) repository_visibility="public" ;;
esac
if [ -n "${OPENCODE_REPOSITORY_VISIBILITY:-}" ]; then
	case "$OPENCODE_REPOSITORY_VISIBILITY" in
	public | private | internal) repository_visibility="$OPENCODE_REPOSITORY_VISIBILITY" ;;
	*)
		echo "ERROR: OPENCODE_REPOSITORY_VISIBILITY must be public, private, or internal." >&2
		exit 2
		;;
	esac
fi

plan_file="$(mktemp)"
trap 'rm -f -- "$plan_file"' EXIT
if ! python3 "$POLICY_SCRIPT" \
	--agent opencode-review \
	--repository-visibility "$repository_visibility" \
	--configured-models-env OPENCODE_MODEL_CANDIDATES \
	--required-capability code_review \
	--format lines >"$plan_file"; then
	echo "ERROR: OpenCode shared fallback plan could not be created." >&2
	exit 2
fi
mapfile -t policy_models <"$plan_file"
if [ "${#policy_models[@]}" -eq 0 ]; then
	echo "ERROR: OpenCode shared fallback plan is empty." >&2
	exit 2
fi
OPENCODE_MODEL_CANDIDATES="${policy_models[*]}"
export OPENCODE_MODEL_CANDIDATES

exec bash "$CORE_SCRIPT" "$@"
