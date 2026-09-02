#!/usr/bin/env bash
# Helper functions shared by the Strix CI gate and its self-test harness.
# Keep this dependency explicit so PR-scoped Strix scans include the full gate harness.

trim_whitespace() {
	local value="${1-}"
	# Collapse only the leading/trailing shell whitespace that can be introduced by
	# secret files or workflow inputs. Internal spacing remains meaningful for the
	# few callers that parse lists after trimming each token.
	value="${value#"${value%%[!$' \t\r\n']*}"}"
	value="${value%"${value##*[!$' \t\r\n']}"}"
	printf '%s\n' "$value"
}

sanitize_provider_name() {
	local provider
	provider="$(trim_whitespace "${1-}")"
	if [ -z "$provider" ]; then
		return 1
	fi
	if [[ ! "$provider" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then
		echo "ERROR: STRIX_LLM_DEFAULT_PROVIDER contains unsupported characters: '$provider'." >&2
		return 2
	fi
	printf '%s\n' "$provider"
}

is_vertex_resource_path() {
	local path
	path="$(trim_whitespace "${1-}")"
	if [ -z "$path" ] || [[ "$path" =~ [[:space:][:cntrl:]] ]]; then
		return 1
	fi

	IFS='/' read -r -a parts <<<"$path"
	local part
	for part in "${parts[@]}"; do
		if [ -z "$part" ] || [ "$part" = "." ] || [ "$part" = ".." ] ||
			[[ ! "$part" =~ ^[A-Za-z0-9._-]+$ ]]; then
			return 1
		fi
	done

	case "${#parts[@]}" in
	2)
		[ "${parts[0]}" = "models" ]
		;;
	4)
		[ "${parts[0]}" = "publishers" ] && [ "${parts[2]}" = "models" ]
		;;
	6)
		[ "${parts[0]}" = "projects" ] && [ "${parts[2]}" = "locations" ] && [ "${parts[4]}" = "models" ]
		;;
	8)
		[ "${parts[0]}" = "projects" ] && [ "${parts[2]}" = "locations" ] && [ "${parts[4]}" = "publishers" ] && [ "${parts[6]}" = "models" ]
		;;
	*)
		return 1
		;;
	esac
}

extract_vertex_model_id() {
	local model
	model="$(trim_whitespace "${1-}")"
	if is_vertex_resource_path "$model"; then
		printf '%s\n' "${model##*/}"
	else
		printf '%s\n' "$model"
	fi
}

normalize_model() {
	local model
	model="$(trim_whitespace "${1-}")"

	# Strix is an organization review path. Its model selector is therefore a
	# policy boundary, not a generic provider normalizer: all inference must go
	# through contextual-orchestrator's fail-closed zero-cost virtual pool.
	# Provider/model identifiers would bypass the orchestrator's free-candidate
	# source, capability, and private-target ZDR admission contracts, so reject
	# them before credentials or provider endpoints can participate in execution.
	case "$model" in
	orchestrator/free | contextual-orchestrator/orchestrator/free)
		printf '%s\n' "$model"
		return 0
		;;
	*)
		echo "ERROR: Strix model must be orchestrator/free through contextual-orchestrator; direct provider/model routes are forbidden: '$model'." >&2
		return 2
		;;
	esac
}

model_requires_vertex_auth() {
	local model normalized_model
	model="$(trim_whitespace "${1-}")"
	if [ -z "$model" ]; then
		return 1
	fi

	normalized_model="$(normalize_model "$model")" || return $?
	case "$normalized_model" in
	vertex_ai/* | vertex_ai_beta/*)
		return 0
		;;
	*)
		return 1
		;;
	esac
}
