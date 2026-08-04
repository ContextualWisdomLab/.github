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
	if [ -z "$model" ]; then
		return 0
	fi

	if is_vertex_resource_path "$model"; then
		local provider
		provider="$(sanitize_provider_name "${DEFAULT_PROVIDER:-}")" || {
			echo "ERROR: Vertex resource paths require an explicit vertex_ai or vertex_ai_beta provider." >&2
			return 2
		}
		case "$provider" in
		vertex_ai | vertex_ai_beta) ;;
		*)
			echo "ERROR: Vertex resource paths require an explicit vertex_ai or vertex_ai_beta provider." >&2
			return 2
			;;
		esac
		printf '%s/%s\n' "$provider" "$(extract_vertex_model_id "$model")"
		return 0
	fi

	local provider="${DEFAULT_PROVIDER:-}"
	if [ -z "$provider" ]; then
		provider="vertex_ai"
	fi
	provider="$(sanitize_provider_name "$provider")" || return $?

	case "$model" in
	projects/* | models/* | publishers/*)
		printf '%s\n' "$model"
		return 0
		;;
	*/*)
		printf '%s\n' "$model"
		return 0
		;;
	*)
		printf '%s/%s\n' "$provider" "$model"
		return 0
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

apply_contextual_fallback_policy() {
	# Reorder only after the trusted workflow has materialized its model/key files.
	# The original gate remains responsible for transport, retries, report parsing,
	# severity thresholds, and fail-closed provider-signal handling.
	local policy_script original_primary repository_visibility primary_policy_token
	local primary_api_base fallback_raw plan_file policy_llm_file model actual_model
	local -a configured_models configured_fallbacks deduplicated_models policy_args
	local -a logical_models actual_models
	local seen_models_text=$'\n' seen_actual_text=$'\n'

	[ -n "${STRIX_LLM_FILE:-}" ] || return 0
	policy_script="${SCRIPT_DIR:?}/contextual_fallback_policy.py"
	if [ ! -f "$policy_script" ] || [ -L "$policy_script" ]; then
		echo "ERROR: contextual fallback policy adapter is unavailable." >&2
		return 2
	fi
	if [ ! -f "$STRIX_LLM_FILE" ] || [ -L "$STRIX_LLM_FILE" ]; then
		echo "ERROR: STRIX_LLM_FILE must reference a regular non-symlink file." >&2
		return 2
	fi
	original_primary="$(tr -d '\r\n' <"$STRIX_LLM_FILE")"
	original_primary="$(trim_whitespace "$original_primary")"
	if [ -z "$original_primary" ] || [[ "$original_primary" =~ [[:space:][:cntrl:]] ]]; then
		echo "ERROR: STRIX_LLM_FILE contains an invalid model token." >&2
		return 2
	fi

	repository_visibility="private"
	case "$original_primary" in
	nvidia_nim/*) repository_visibility="public" ;;
	esac
	if [ -n "${STRIX_REPOSITORY_VISIBILITY:-}" ]; then
		case "$STRIX_REPOSITORY_VISIBILITY" in
		public | private | internal) repository_visibility="$STRIX_REPOSITORY_VISIBILITY" ;;
		*)
			echo "ERROR: STRIX_REPOSITORY_VISIBILITY must be public, private, or internal." >&2
			return 2
			;;
		esac
	fi

	if [ -n "${LLM_API_KEY_FILE:-}" ] && [ -f "$LLM_API_KEY_FILE" ] && [ ! -L "$LLM_API_KEY_FILE" ] && [ -s "$LLM_API_KEY_FILE" ]; then
		export STRIX_PRIMARY_KEY_CONFIGURED=1
	fi
	if [ -n "${STRIX_GITHUB_MODELS_KEY_FILE:-}" ] && [ -f "$STRIX_GITHUB_MODELS_KEY_FILE" ] && [ ! -L "$STRIX_GITHUB_MODELS_KEY_FILE" ] && [ -s "$STRIX_GITHUB_MODELS_KEY_FILE" ]; then
		export STRIX_GITHUB_MODELS_CONFIGURED=1
	fi

	primary_policy_token="$original_primary"
	case "$original_primary" in
	nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b | \
	nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 | \
	nvidia_nim/nvidia/nemotron-3-super-120b-a12b | \
	openrouter/free | openai_direct/gpt-5.6-luna | \
	vertex_ai/gemini-3.1-pro-preview-customtools | vertex_ai/gemini-2.5-flash) ;;
	*)
		primary_api_base=""
		if [ -n "${LLM_API_BASE_FILE:-}" ] && [ -f "$LLM_API_BASE_FILE" ] && [ ! -L "$LLM_API_BASE_FILE" ]; then
			primary_api_base="$(tr -d '\r\n' <"$LLM_API_BASE_FILE")"
		fi
		case "$primary_api_base:$original_primary" in
		https://models.github.ai/inference:* | *:github_models/*)
			primary_policy_token="configured/strix-github-primary"
			;;
		*) primary_policy_token="configured/strix-paid-primary" ;;
		esac
		;;
	esac

	configured_models=("$primary_policy_token")
	if [[ "$original_primary" == nvidia_nim/* ]] && [ -n "${STRIX_PRIMARY_KEY_CONFIGURED:-}" ]; then
		configured_models+=(
			"nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b"
			"nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"
			"nvidia_nim/nvidia/nemotron-3-super-120b-a12b"
		)
	fi
	if [ -n "${STRIX_GITHUB_MODELS_CONFIGURED:-}" ]; then
		configured_models+=(
			"github_models/openai/o3"
			"github_models/openai/gpt-5-chat"
		)
	fi
	fallback_raw="${STRIX_FALLBACK_MODELS:-} ${STRIX_VERTEX_FALLBACK_MODELS:-}"
	read -r -a configured_fallbacks <<<"$fallback_raw"
	configured_models+=("${configured_fallbacks[@]}")

	deduplicated_models=()
	for model in "${configured_models[@]}"; do
		[ -n "$model" ] || continue
		if [[ "$seen_models_text" != *$'\n'"$model"$'\n'* ]]; then
			seen_models_text+="$model"$'\n'
			deduplicated_models+=("$model")
		fi
	done

	plan_file="$(mktemp)"
	policy_args=(
		--agent strix
		--repository-visibility "$repository_visibility"
		--required-capability security_review
		--format lines
	)
	for model in "${deduplicated_models[@]}"; do
		policy_args+=(--configured-model "$model")
	done
	if ! python3 "$policy_script" "${policy_args[@]}" >"$plan_file"; then
		rm -f -- "$plan_file"
		echo "ERROR: Strix shared fallback plan could not be created." >&2
		return 2
	fi
	mapfile -t logical_models <"$plan_file"
	rm -f -- "$plan_file"
	if [ "${#logical_models[@]}" -eq 0 ]; then
		echo "ERROR: Strix shared fallback plan is empty." >&2
		return 2
	fi

	actual_models=()
	for model in "${logical_models[@]}"; do
		case "$model" in
		configured/strix-github-primary | configured/strix-paid-primary)
			actual_model="$original_primary"
			;;
		*) actual_model="$model" ;;
		esac
		if [[ "$seen_actual_text" != *$'\n'"$actual_model"$'\n'* ]]; then
			seen_actual_text+="$actual_model"$'\n'
			actual_models+=("$actual_model")
		fi
	done
	policy_llm_file="$(mktemp "${STRIX_INPUT_FILE_ROOT:-${RUNNER_TEMP:-/tmp}}/strix-policy-model.XXXXXX")"
	printf '%s' "${actual_models[0]}" >"$policy_llm_file"
	chmod 0600 "$policy_llm_file"
	STRIX_LLM_FILE="$policy_llm_file"
	if [ "${#actual_models[@]}" -gt 1 ]; then
		STRIX_FALLBACK_MODELS="${actual_models[*]:1}"
		STRIX_VERTEX_FALLBACK_MODELS="$STRIX_FALLBACK_MODELS"
	else
		STRIX_FALLBACK_MODELS=""
		STRIX_VERTEX_FALLBACK_MODELS=""
	fi
	export STRIX_LLM_FILE STRIX_FALLBACK_MODELS STRIX_VERTEX_FALLBACK_MODELS
}

if [ -n "${STRIX_LLM_FILE:-}" ]; then
	apply_contextual_fallback_policy
fi
