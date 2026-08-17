#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:=/dev/null}"

record_review_status() {
	printf 'review_status=%s\n' "$1" >>"$GITHUB_OUTPUT"
}

record_review_model() {
	printf 'review_model=%s\n' "$1" >>"$GITHUB_OUTPUT"
}

record_pool_exhausted() {
	printf 'OpenCode model pool exhausted before producing a valid control conclusion.\n'
	record_review_model ""
	record_review_status "exhausted"
}

finish_pool_without_model() {
	record_pool_exhausted
	return 1
}

normalize_opencode_output() {
	local output_file="$1"

	# Validate a throwaway copy, never the file itself. The publish step runs
	# opencode_review_normalize_output.py on the model output, and that script
	# REWRITES its input in place (it is not idempotent). If the pool normalized
	# output_file directly, the publish step would normalize the already-rewritten
	# content a second time and fail with "Selected successful OpenCode output did
	# not include a valid control conclusion", ending the run instead of falling
	# through to the next model. Mirror the publish step exactly — ANSI-strip a
	# copy, then normalize — so the pool only records success for output the
	# publish step will accept, and leave output_file pristine for the publish
	# step to normalize itself.
	local probe rc
	probe="$(mktemp)"
	perl -pe 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$output_file" >"$probe" 2>/dev/null || cp "$output_file" "$probe"

	if python3 "$GITHUB_WORKSPACE/scripts/ci/opencode_review_normalize_output.py" \
		"$HEAD_SHA" "$RUN_ID" "$RUN_ATTEMPT" "$probe"; then
		bash "$GITHUB_WORKSPACE/scripts/ci/opencode_review_approve_gate.sh" \
			"$HEAD_SHA" "$RUN_ID" "$RUN_ATTEMPT" "$probe" >/dev/null
		rc=$?
	else
		rc=1
	fi
	rm -f "$probe"
	return "$rc"
}

backoff_sleep() {
	local attempt="$1"
	local initial max_sleep attempt_value
	local sleep_for
	if ! is_non_negative_integer "$attempt" || [ "$((10#$attempt))" -lt 1 ] || [ "$((10#$attempt))" -gt 30 ]; then
		attempt="1"
	fi
	initial="$(env_integer_or_default OPENCODE_BACKOFF_INITIAL_SECONDS 20)"
	max_sleep="$(env_integer_or_default OPENCODE_BACKOFF_MAX_SECONDS 300)"
	attempt_value=$((10#$attempt))
	initial=$((10#$initial))
	max_sleep=$((10#$max_sleep))
	sleep_for=$((initial * (1 << (attempt_value - 1))))
	if [ "$sleep_for" -gt "$max_sleep" ]; then
		sleep_for="$max_sleep"
	fi
	printf '%s\n' "$sleep_for"
}

is_non_negative_integer() {
	case "${1:-}" in
	"" | *[!0-9]* | ??????????*) return 1 ;;
	*) return 0 ;;
	esac
}

env_integer_or_default() {
	local name="$1"
	local default_value="$2"
	local value="${!name:-}"

	if is_non_negative_integer "$value"; then
		printf '%s\n' "$value"
	else
		printf '%s\n' "$default_value"
	fi
}

cap_dynamic_cadence_for_queue() {
	local timeout_cap budget_cap cycle_cap previous_run_timeout previous_budget_seconds previous_max_cycles

	timeout_cap="$(env_integer_or_default OPENCODE_DYNAMIC_RUN_TIMEOUT_CAP_SECONDS 7200)"
	budget_cap="$(env_integer_or_default OPENCODE_DYNAMIC_TOTAL_BUDGET_CAP_SECONDS 7200)"
	cycle_cap="$(env_integer_or_default OPENCODE_DYNAMIC_MAX_CYCLES_CAP 0)"
	previous_run_timeout="$original_run_timeout"
	previous_budget_seconds="$budget_seconds"
	previous_max_cycles="$max_cycles"

	if [ "$timeout_cap" -gt 0 ] && [ "$original_run_timeout" -gt "$timeout_cap" ]; then
		original_run_timeout="$timeout_cap"
	fi
	if [ "$budget_cap" -gt 0 ] && [ "$budget_seconds" -gt "$budget_cap" ]; then
		budget_seconds="$budget_cap"
	fi
	if [ "$cycle_cap" -gt 0 ]; then
		if [ "$max_cycles" -eq 0 ] || [ "$max_cycles" -gt "$cycle_cap" ]; then
			max_cycles="$cycle_cap"
		fi
	fi

	if [ "$original_run_timeout" != "$previous_run_timeout" ] ||
		[ "$budget_seconds" != "$previous_budget_seconds" ] ||
		[ "$max_cycles" != "$previous_max_cycles" ]; then
		printf 'OpenCode dynamic review cadence queue cap applied: per-attempt %ss -> %ss, total budget %ss -> %ss, max-cycles %s -> %s; set OPENCODE_DYNAMIC_*_CAP_SECONDS or OPENCODE_DYNAMIC_MAX_CYCLES_CAP to 0 to disable a specific queue cap.\n' \
			"$previous_run_timeout" "$original_run_timeout" \
			"$previous_budget_seconds" "$budget_seconds" \
			"$previous_max_cycles" "$max_cycles"
	fi
}

count_changed_files_for_cadence() {
	local changed_files_file="${OPENCODE_CHANGED_FILES_FILE:-}"

	if [ -z "$changed_files_file" ] || [ ! -f "$changed_files_file" ]; then
		return 1
	fi
	awk 'NF { count += 1 } END { printf "%d\n", count + 0 }' "$changed_files_file"
}

write_prompt() {
	local model_candidate="$1"
	local prompt_file="$2"
	local intro
	local contract_file
	local evidence_excerpt_file

	if [ -n "${OPENCODE_REVIEW_INTRO:-}" ]; then
		intro="$OPENCODE_REVIEW_INTRO"
	else
		intro="Review PR #\${PR_NUMBER} in \${OPENCODE_SOURCE_WORKDIR} with \${model_candidate}."
	fi
	# Colon-safe: OpenRouter ":free" candidates would otherwise produce file
	# names that Windows and actions/upload-artifact reject.
	contract_file="$OPENCODE_REVIEW_WORKDIR/opencode-review-contract-${model_candidate//[\/:]/-}.md"
	evidence_excerpt_file="$OPENCODE_REVIEW_WORKDIR/bounded-review-evidence-excerpt.md"
	cp "$GITHUB_WORKSPACE/scripts/ci/opencode_review_prompt_template.md" "$contract_file"
	OPENCODE_REVIEW_INTRO="$intro" \
		PROMPT_MODEL_CANDIDATE="$model_candidate" \
		python3 "$GITHUB_WORKSPACE/scripts/ci/render_opencode_prompt_template.py" "$contract_file"

	{
		printf '%s\n\n' "$intro"
		printf 'Follow the complete review contract in `%s`; use this launcher as a packet-first entry point, not as a reduced policy.\n' "$contract_file"
		printf 'Read bounded review evidence from `%s` and source files from `%s` when tool access works.\n' "$OPENCODE_EVIDENCE_FILE" "$OPENCODE_SOURCE_WORKDIR"
		printf 'Use the trusted review workspace `%s` for scripts, prompts, policy files, CodeGraph config, and validation helpers.\n\n' "$OPENCODE_REVIEW_WORKDIR"
		printf 'First review the current-head evidence excerpt in this prompt. Then inspect full evidence, changed files, focused related code, and configured structural/search tools when available.\n'
		printf 'Never emit raw tool-call markup, MCP call syntax, function-call JSON, tool_call text, or a JSON array of tool calls. If tool calls or file reads are unavailable, do not emit progress notes or raw tool-call text.\n'
		printf 'If full-file reads do not execute, use the inlined evidence packet and its repeated current-head sections for Changed files, Focused changed hunks, Coverage execution evidence, Failed GitHub Check evidence, and unresolved thread evidence.\n'
		printf 'Do not request changes solely because your tool call, MCP call, or full-file read was not executed. Treat that as a review source limitation unless current-head evidence explicitly reports a materialization failure; any such finding must be tied to that evidence, not a generic model-exhaustion message. REQUEST_CHANGES findings must cite a positive source/evidence line; never use line 0.\n'
		printf 'Always return a final control block instead of a progress summary. Return only the final review body.\n\n'
		printf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome and copy exactly one source-line-sha256=<64 lowercase hex> receipt with its matching path and line from the trusted receipt section; generic source-inspection or coverage-verification claims are invalid.\n'
		printf 'Current-run identity values are head_sha=%s, run_id=%s, run_attempt=%s. Copy them into the one final control object required by the contract file.\n' "$HEAD_SHA" "$RUN_ID" "$RUN_ATTEMPT"
		printf 'Do not quote, repeat, or emit a schema example before the final sentinel. Choose exactly one result token, APPROVE or REQUEST_CHANGES; never emit the literal phrase "APPROVE or REQUEST_CHANGES".\n'
		printf 'Before returning, verify: exactly one top-level current-run control object; non-empty reason, summary, and residual_risk; the required number of complete probes; APPROVE has status=passed, only falsified probes, and findings=[]; REQUEST_CHANGES has status=failed, a confirmed probe, and a same-location source-backed finding.\n'
		if [ -s "$evidence_excerpt_file" ]; then
			printf '\nCurrent-head evidence packet:\n\n'
			python3 - "$evidence_excerpt_file" "${OPENCODE_PROMPT_EVIDENCE_MAX_BYTES:-120000}" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
max_bytes = int(sys.argv[2])
data = path.read_bytes()
if len(data) <= max_bytes:
    sys.stdout.buffer.write(data)
else:
    head = data[: max_bytes // 2]
    tail = data[-(max_bytes // 2) :]
    sys.stdout.buffer.write(head)
    sys.stdout.write(
        "\n\n[OpenCode evidence excerpt truncated for provider context window; "
        f"showing {len(head)} head bytes and {len(tail)} tail bytes from {len(data)} total bytes. "
        "Read the full bounded-review-evidence.md file before making any source-backed conclusion.]\n\n"
    )
    sys.stdout.buffer.write(tail)
PY
			printf '\n'
		fi
	} >"$prompt_file"
}

write_schema_repair_prompt() {
	local model_candidate="$1"
	local prompt_file="$2"

	write_prompt "$model_candidate" "$prompt_file"
	{
		printf '\nA previous response from this same provider reached the trusted validator but failed the control schema. Perform the review again from the same trusted evidence and return one corrected review body only.\n'
		printf 'This is a schema repair opportunity, not permission to weaken, omit, or fabricate evidence. Check every item before returning:\n'
		printf -- '- Emit exactly one sentinel and exactly one current-run JSON control object; do not quote any example object or earlier response.\n'
		printf -- '- Choose exactly APPROVE or REQUEST_CHANGES, with a non-empty reason, summary, and residual_risk.\n'
		printf -- '- Include "adversarial_validation" as an object with at least the required probe count. Copy each path, line, and source-line-sha256 receipt exactly from trusted bounded evidence.\n'
		printf -- '- APPROVE requires status=passed, every probe outcome=falsified, and findings=[].\n'
		printf -- '- REQUEST_CHANGES requires status=failed, at least one outcome=confirmed, and a non-empty source-backed finding at the same path and line.\n'
		printf 'Return only the corrected review body now.\n'
	} >>"$prompt_file"
}

assert_reasoning_effort_for_candidate() {
	local model_candidate="$1"

	python3 "$GITHUB_WORKSPACE/scripts/ci/assert_opencode_reasoning_effort.py" \
		--config opencode.jsonc \
		"$model_candidate"
}

is_context_overflow_failure() {
	local opencode_json_file="$1"

	[ -s "$opencode_json_file" ] || return 1
	grep -Eiq 'ContextOverflowError|tokens_limit_reached|Request body too large|context window' "$opencode_json_file"
}

is_fatal_provider_failure() {
	local opencode_json_file="$1"

	if is_context_overflow_failure "$opencode_json_file"; then
		return 0
	fi
	[ -s "$opencode_json_file" ] || return 1
	grep -Eiq 'budget limit|insufficient_quota|insufficient credits|payment required|model_not_found|model not found|ModelNotFoundError|not a valid model|no endpoints' "$opencode_json_file"
}

has_fatal_provider_error_event() {
	local opencode_json_file="$1"

	[ -s "$opencode_json_file" ] || return 1
	# Only structured "type":"error" events count while the process is still
	# running: model prose or tool output quoting these signatures is
	# JSON-escaped inside event strings, so a healthy streaming run is never
	# killed for merely discussing context windows, quota errors, or missing
	# models. Model-unavailable signatures (OpenRouter "No endpoints found" /
	# "not a valid model ID", OpenAI-style model_not_found) matter because a
	# delisted pinned free model would otherwise hang and burn the whole
	# candidate run budget.
	awk 'tolower($0) ~ /"type"[[:space:]]*:[[:space:]]*"error"/ && tolower($0) ~ /contextoverflowerror|tokens_limit_reached|request body too large|context window|budget limit|insufficient_quota|insufficient credits|payment required|model_not_found|model not found|modelnotfounderror|not a valid model|no endpoints/ { found = 1; exit } END { exit !found }' "$opencode_json_file"
}

is_credit_exhausted_failure() {
	local opencode_json_file="$1"
	local opencode_stderr_file="$2"

	# Paid-provider credit exhaustion (OpenRouter HTTP 402 "Insufficient
	# credits") can never recover within one run: every retry is a wasted
	# paid request. Match structured "type":"error" events in the JSON
	# stream (same trust model as has_fatal_provider_error_event) plus
	# CLI diagnostics on stderr, which never contain model prose.
	if [ -s "$opencode_json_file" ] &&
		awk 'tolower($0) ~ /"type"[[:space:]]*:[[:space:]]*"error"/ && tolower($0) ~ /insufficient credits|payment required|(^|[^0-9])402([^0-9]|$)/ { found = 1; exit } END { exit !found }' "$opencode_json_file"; then
		return 0
	fi
	[ -s "$opencode_stderr_file" ] || return 1
	grep -Eiq 'insufficient credits|payment required|"code"[[:space:]]*:[[:space:]]*402' "$opencode_stderr_file"
}

emit_sanitized_opencode_failure_detail() {
	local opencode_json_file="$1"
	local opencode_stderr_file="$2"
	local json_bytes stderr_bytes failure_class

	json_bytes=0
	stderr_bytes=0
	if [ -s "$opencode_json_file" ]; then
		json_bytes="$(wc -c <"$opencode_json_file" | tr -d ' ')"
	fi
	if [ -s "$opencode_stderr_file" ]; then
		stderr_bytes="$(wc -c <"$opencode_stderr_file" | tr -d ' ')"
	fi

	failure_class="unclassified"
	if grep -Eiq 'ContextOverflowError|tokens_limit_reached|Request body too large|context window' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="context-window"
	elif grep -Eiq 'insufficient credits|payment required|"code"[[:space:]]*:[[:space:]]*402' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="credit-exhausted"
	elif grep -Eiq 'budget limit|insufficient_quota|quota exceeded' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="quota-or-budget"
	elif grep -Eiq 'model_not_found|model not found|ModelNotFoundError|not a valid model|no endpoints' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="model-unavailable"
	elif grep -Eiq 'rate.?limit|too many requests|(^|[^0-9])429([^0-9]|$)' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="rate-limit"
	elif grep -Eiq 'permission denied|authentication|authorization|(^|[^0-9])(401|403)([^0-9]|$)' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="authentication-or-permission"
	elif grep -Eiq 'timed? ?out|timeout' "$opencode_json_file" "$opencode_stderr_file" 2>/dev/null; then
		failure_class="timeout"
	elif [ "$json_bytes" -gt 0 ] || [ "$stderr_bytes" -gt 0 ]; then
		failure_class="provider-error"
	else
		failure_class="no-provider-detail"
	fi
	printf 'OpenCode provider failure metadata: class=%s json-bytes=%s stderr-bytes=%s; provider-controlled content suppressed.\n' \
		"$failure_class" "$json_bytes" "$stderr_bytes"
}

emit_rejected_opencode_artifact_metadata() {
	local artifact_kind="$1"
	local artifact_file="$2"
	local artifact_bytes=0 artifact_lines=0

	if [ -f "$artifact_file" ]; then
		artifact_bytes="$(wc -c <"$artifact_file" | tr -d ' ')"
		artifact_lines="$(wc -l <"$artifact_file" | tr -d ' ')"
	fi
	printf 'OpenCode rejected provider artifact metadata: kind=%s bytes=%s lines=%s; provider-controlled content suppressed.\n' \
		"$artifact_kind" "$artifact_bytes" "$artifact_lines"
}

is_direct_openai_candidate() {
	case "$1" in
	openai/*) return 0 ;;
	*) return 1 ;;
	esac
}

is_openrouter_candidate() {
	case "$1" in
	openrouter/*) return 0 ;;
	*) return 1 ;;
	esac
}

is_nvidia_nim_candidate() {
	case "$1" in
	nvidia-nim/*) return 0 ;;
	*) return 1 ;;
	esac
}

is_schema_repair_candidate() {
	case "$1" in
	nvidia-nim/* | opencode-free/*) return 0 ;;
	*) return 1 ;;
	esac
}

# Org secret name is NVIDIA_NIM_API_KEY (GitHub Actions / org secrets UI).
# opencode.jsonc nvidia-nim provider block resolves {env:NVIDIA_API_KEY}.
# Normalize only the scoped secret and discard any legacy provider credential so
# it cannot activate NIM candidates outside the explicit governance boundary.
if [ -n "${NVIDIA_NIM_API_KEY:-}" ]; then
	export NVIDIA_API_KEY="$NVIDIA_NIM_API_KEY"
else
	unset NVIDIA_API_KEY
fi

is_low_sensitivity_candidate() {
	case "$1" in
	openai/*-mini | openai/*-nano)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

should_skip_model_candidate() {
	local model_candidate="$1"

	if is_low_sensitivity_candidate "$model_candidate"; then
		printf 'Skipping OpenCode %s because mini/nano review models are disabled for high-sensitivity security review.\n' "$model_candidate"
		return 0
	fi
	if is_direct_openai_candidate "$model_candidate" && [ -z "${OPENAI_API_KEY:-}" ]; then
		printf 'Skipping OpenCode %s because OPENAI_API_KEY is not configured; falling back to the next provider-qualified candidate.\n' "$model_candidate"
		return 0
	fi
	if is_openrouter_candidate "$model_candidate" && [ -z "${OPENROUTER_API_KEY:-}" ]; then
		printf 'Skipping OpenCode %s because OPENROUTER_API_KEY is not configured; falling back to the next provider-qualified candidate.\n' "$model_candidate"
		return 0
	fi
	if is_nvidia_nim_candidate "$model_candidate" && [ -z "${NVIDIA_NIM_API_KEY:-}" ]; then
		printf 'Skipping OpenCode %s because scoped NVIDIA_NIM_API_KEY is not configured; falling back to the next provider-qualified candidate.\n' "$model_candidate"
		return 0
	fi
	return 1
}

cap_model_run_timeout() {
	local model_candidate="$1"
	local run_timeout_seconds="$2"
	local cap_seconds

	case "$model_candidate" in
	nvidia-nim/*)
		cap_seconds="$(env_integer_or_default OPENCODE_NVIDIA_NIM_RUN_TIMEOUT_SECONDS 7200)"
		;;
	opencode-free/*)
		cap_seconds="$(env_integer_or_default OPENCODE_FREE_RUN_TIMEOUT_SECONDS 3600)"
		;;
	*)
		printf '%s\n' "$run_timeout_seconds"
		return 0
		;;
	esac
	if [ "$cap_seconds" -gt 0 ] && [ "$run_timeout_seconds" -gt "$cap_seconds" ]; then
		printf '%s\n' "$cap_seconds"
	else
		printf '%s\n' "$run_timeout_seconds"
	fi
}

run_one_model_attempt() {
	local model_candidate="$1"
	local attempt="$2"
	local attempts="$3"
	local agent="$4"
	local prompt_file="$5"
	local candidate_output_file="$6"
	local opencode_json_file="$7"
	local opencode_export_file="$8"
	local run_timeout_seconds export_timeout_seconds opencode_status session_id opencode_stderr_file
	local opencode_pid fatal_poll_seconds

	run_timeout_seconds="${OPENCODE_RUN_TIMEOUT_SECONDS:-3600}"
	export_timeout_seconds="${OPENCODE_EXPORT_TIMEOUT_SECONDS:-120}"
	fatal_poll_seconds="${OPENCODE_FATAL_ERROR_POLL_SECONDS:-5}"
	opencode_stderr_file="${opencode_json_file}.stderr"

	rm -f "$opencode_json_file" "$opencode_stderr_file" "$opencode_export_file" "$candidate_output_file"
	set +e
	timeout --kill-after=30s "${run_timeout_seconds}s" \
		env -u GH_TOKEN -u GITHUB_TOKEN -u OPENCODE_APP_TOKEN \
		-u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL \
		opencode run "$(cat "$prompt_file")" \
		--pure \
		--agent "$agent" \
		--model "$model_candidate" \
		--format json \
		--title "PR #${PR_NUMBER} OpenCode bounded review ${model_candidate} attempt ${attempt}/${attempts}" \
		>"$opencode_json_file" 2>"$opencode_stderr_file" &
	opencode_pid=$!
	# Some providers log a fatal error and then hang instead of exiting,
	# burning the whole run timeout. Watch the JSON
	# log while opencode runs and kill the process early so the pool falls
	# through to the next candidate within seconds instead of minutes.
	while kill -0 "$opencode_pid" 2>/dev/null; do
		if has_fatal_provider_error_event "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s logged a fatal provider error while still running; killing the hung process instead of waiting out the %ss run timeout.\n' \
				"$model_candidate" "$attempt" "$attempts" "$run_timeout_seconds"
			kill "$opencode_pid" 2>/dev/null
			for _ in $(seq 1 30); do
				kill -0 "$opencode_pid" 2>/dev/null || break
				sleep 1
			done
			kill -9 "$opencode_pid" 2>/dev/null
			break
		fi
		sleep "$fatal_poll_seconds"
	done
	wait "$opencode_pid"
	opencode_status=$?
	set -e
	if [ "$opencode_status" -ne 0 ]; then
		printf 'OpenCode %s attempt %s/%s failed with exit %s.\n' "$model_candidate" "$attempt" "$attempts" "$opencode_status"
		emit_sanitized_opencode_failure_detail "$opencode_json_file" "$opencode_stderr_file"
		if [ "$opencode_status" -eq 124 ] || [ "$opencode_status" -eq 137 ]; then
			printf 'OpenCode %s attempt %s/%s timed out after %ss; falling through within the remaining retry budget instead of blocking the org queue.\n' "$model_candidate" "$attempt" "$attempts" "$run_timeout_seconds"
		fi
		if is_fatal_provider_failure "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s hit a fatal provider error (context window, token budget, quota, or model unavailable); skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
			return 2
		fi
		return 1
	fi

	session_id="$(jq -r 'select(.type == "step_start") | .sessionID' "$opencode_json_file" | tail -n 1)"
	if [ -z "$session_id" ] || [ "$session_id" = "null" ]; then
		printf 'OpenCode %s attempt %s/%s JSON output did not include a session id.\n' "$model_candidate" "$attempt" "$attempts"
		emit_rejected_opencode_artifact_metadata "sessionless-json" "$opencode_json_file"
		if is_fatal_provider_failure "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s hit a fatal provider error (context window, token budget, quota, or model unavailable); skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
			return 2
		fi
		return 1
	fi
	if ! timeout --kill-after=15s "${export_timeout_seconds}s" \
		env -u GH_TOKEN -u GITHUB_TOKEN -u OPENCODE_APP_TOKEN \
		-u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL \
		opencode export "$session_id" --pure >"$opencode_export_file"; then
		printf 'OpenCode %s attempt %s/%s session export did not complete within %ss.\n' "$model_candidate" "$attempt" "$attempts" "$export_timeout_seconds"
		return 1
	fi
	jq -r '.messages[] | select(.info.role == "assistant") | .parts[]? | select(.type == "text") | .text' "$opencode_export_file" >"$candidate_output_file"
	if [ ! -s "$candidate_output_file" ]; then
		printf 'OpenCode %s attempt %s/%s session export did not include assistant text.\n' "$model_candidate" "$attempt" "$attempts"
		emit_rejected_opencode_artifact_metadata "assistant-empty-export" "$opencode_export_file"
		return 1
	fi
	if ! normalize_opencode_output "$candidate_output_file"; then
		printf 'OpenCode %s attempt %s/%s output did not include a valid control conclusion.\n' "$model_candidate" "$attempt" "$attempts"
		emit_rejected_opencode_artifact_metadata "invalid-control-output" "$candidate_output_file"
		return 3
	fi
	return 0
}

main() {
	local attempts schema_repair_attempts effective_attempts budget_seconds deadline now remaining model_candidate attempt safe_model prompt_file candidate_output_file
	local opencode_json_file opencode_export_file agent retry_sleep original_run_timeout run_status cycle_sleep cycle max_cycles
	local uncapped_run_timeout
	local changed_file_count small_file_threshold medium_file_threshold
	local invalid_control_cap max_total_attempts total_attempts alive_candidates
	local nim_budget_seconds nim_elapsed_seconds nim_remaining_seconds
	local nim_attempt_started nim_attempt_elapsed non_nim_candidate_count
	local -A dead_candidate_reasons invalid_control_counts
	local -a model_candidates

	# Spend guards, not timing: a paid candidate that keeps producing
	# control-rejected output or has exhausted provider credits must stop
	# consuming paid requests instead of cycling until the retry budget
	# elapses (run 30120972549 burned the org OpenRouter credit in ~102
	# cycles of re-sent full prompts). Timeouts/deadlines are untouched.
	invalid_control_cap="$(env_integer_or_default OPENCODE_INVALID_CONTROL_OUTPUT_CAP 3)"
	max_total_attempts="$(env_integer_or_default OPENCODE_POOL_MAX_TOTAL_ATTEMPTS 30)"
	total_attempts=0

	attempts="${OPENCODE_MODEL_ATTEMPTS:-3}"
	schema_repair_attempts="$(env_integer_or_default OPENCODE_SCHEMA_REPAIR_ATTEMPTS 1)"
	original_run_timeout="${OPENCODE_RUN_TIMEOUT_SECONDS:-3600}"
	budget_seconds="${OPENCODE_TOTAL_RETRY_BUDGET_SECONDS:-1500}"
	max_cycles="${OPENCODE_POOL_MAX_CYCLES:-0}"
	if [ "${CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE:-false}" = "true" ]; then
		original_run_timeout="${OPENCODE_CENTRAL_REVIEW_PROCESS_FALLBACK_RUN_TIMEOUT_SECONDS:-3600}"
		budget_seconds="${OPENCODE_CENTRAL_REVIEW_PROCESS_FALLBACK_TOTAL_BUDGET_SECONDS:-3600}"
		max_cycles="${OPENCODE_CENTRAL_REVIEW_PROCESS_FALLBACK_MAX_CYCLES:-1}"
		printf 'Central review-process evidence fallback eligible for scope "%s"; limiting OpenCode model pool to %ss per attempt, %ss total budget, and %s cycle(s) so provider delay is logged before the publish fallback evaluates current-head peer evidence.\n' \
			"${CENTRAL_REVIEW_PROCESS_FALLBACK_SCOPE_LABEL:-unsupported}" "$original_run_timeout" "$budget_seconds" "$max_cycles"
	elif [ "${OPENCODE_DYNAMIC_REVIEW_CADENCE:-false}" = "true" ]; then
		small_file_threshold="$(env_integer_or_default OPENCODE_SMALL_CHANGE_FILE_THRESHOLD 3)"
		medium_file_threshold="$(env_integer_or_default OPENCODE_MEDIUM_CHANGE_FILE_THRESHOLD 20)"
		if changed_file_count="$(count_changed_files_for_cadence)"; then
			if [ "$changed_file_count" -le "$small_file_threshold" ]; then
				original_run_timeout="$(env_integer_or_default OPENCODE_SMALL_CHANGE_RUN_TIMEOUT_SECONDS 900)"
				budget_seconds="$(env_integer_or_default OPENCODE_SMALL_CHANGE_TOTAL_BUDGET_SECONDS 2100)"
			elif [ "$changed_file_count" -le "$medium_file_threshold" ]; then
				original_run_timeout="$(env_integer_or_default OPENCODE_MEDIUM_CHANGE_RUN_TIMEOUT_SECONDS 3600)"
				budget_seconds="$(env_integer_or_default OPENCODE_MEDIUM_CHANGE_TOTAL_BUDGET_SECONDS 3900)"
			else
				original_run_timeout="$(env_integer_or_default OPENCODE_LARGE_CHANGE_RUN_TIMEOUT_SECONDS 3600)"
				budget_seconds="$(env_integer_or_default OPENCODE_LARGE_CHANGE_TOTAL_BUDGET_SECONDS 7200)"
			fi
			max_cycles="$(env_integer_or_default OPENCODE_DYNAMIC_MAX_CYCLES 0)"
			cap_dynamic_cadence_for_queue
			printf 'OpenCode dynamic review cadence selected %ss per attempt and %ss total budget for %s changed file(s); max-cycles=%s.\n' \
				"$original_run_timeout" "$budget_seconds" "$changed_file_count" "$max_cycles"
		else
			original_run_timeout="$(env_integer_or_default OPENCODE_UNKNOWN_CHANGE_RUN_TIMEOUT_SECONDS 3600)"
			budget_seconds="$(env_integer_or_default OPENCODE_UNKNOWN_CHANGE_TOTAL_BUDGET_SECONDS 3900)"
			max_cycles="$(env_integer_or_default OPENCODE_DYNAMIC_MAX_CYCLES 0)"
			cap_dynamic_cadence_for_queue
			printf 'OpenCode dynamic review cadence could not read OPENCODE_CHANGED_FILES_FILE; using %ss per attempt and %ss total budget; max-cycles=%s.\n' \
				"$original_run_timeout" "$budget_seconds" "$max_cycles"
		fi
	fi
	deadline=0
	if [ "$budget_seconds" -gt 0 ]; then
		deadline=$((SECONDS + budget_seconds))
	fi
	: >"$OPENCODE_OUTPUT_FILE"
	cd "$OPENCODE_REVIEW_WORKDIR"
	read -r -a model_candidates <<<"${OPENCODE_MODEL_CANDIDATES:-}"
	if [ "${#model_candidates[@]}" -eq 0 ]; then
		printf 'OpenCode model pool has no configured model candidates.\n'
		if finish_pool_without_model; then
			exit 0
		fi
		exit 1
	fi
	has_nim_candidate=0
	for model_candidate in "${model_candidates[@]}"; do
		if is_nvidia_nim_candidate "$model_candidate"; then
			has_nim_candidate=1
			break
		fi
	done
	if [ "$has_nim_candidate" -eq 1 ] && [ -z "${NVIDIA_NIM_API_KEY:-}" ]; then
		printf 'OpenCode model pool requires NVIDIA_NIM_API_KEY; failing closed without GitHub Models fallback.\n'
		if finish_pool_without_model; then
			exit 0
		fi
		exit 1
	fi
	nim_budget_seconds="$(env_integer_or_default OPENCODE_NVIDIA_NIM_TOTAL_BUDGET_SECONDS 7200)"
	nim_elapsed_seconds=0
	non_nim_candidate_count=0
	for model_candidate in "${model_candidates[@]}"; do
		if ! is_nvidia_nim_candidate "$model_candidate"; then
			non_nim_candidate_count=$((non_nim_candidate_count + 1))
		fi
	done
	if [ "$non_nim_candidate_count" -gt 0 ] &&
		[ "$budget_seconds" -gt 0 ] &&
		[ "$nim_budget_seconds" -ge "$budget_seconds" ]; then
		nim_budget_seconds=$((budget_seconds / 2))
		printf 'OpenCode NVIDIA NIM combined runtime budget was capped at %ss so %s non-NIM fallback candidate(s) retain retry budget.\n' \
			"$nim_budget_seconds" "$non_nim_candidate_count"
	fi
	printf 'Configured OpenCode model pool: candidates=%s attempts=%s per-model-timeout=%ss retry-budget=%ss max-cycles=%s NVIDIA-NIM-combined-budget=%ss.\n' \
		"${#model_candidates[@]}" "$attempts" "$original_run_timeout" "$budget_seconds" "$max_cycles" "$nim_budget_seconds"

	cycle=1
	while :; do
		printf 'Starting OpenCode model pool cycle %s.\n' "$cycle"
		for model_candidate in "${model_candidates[@]}"; do
			if [ -n "${dead_candidate_reasons[$model_candidate]:-}" ]; then
				printf 'Skipping OpenCode %s for the rest of this run: %s.\n' \
					"$model_candidate" "${dead_candidate_reasons[$model_candidate]}"
				continue
			fi
			if should_skip_model_candidate "$model_candidate"; then
				continue
			fi
			if is_nvidia_nim_candidate "$model_candidate" &&
				[ "$nim_elapsed_seconds" -ge "$nim_budget_seconds" ]; then
				printf 'Skipping OpenCode %s because the NVIDIA NIM combined runtime budget of %ss is exhausted; preserving the remaining retry budget for fallback candidates.\n' \
					"$model_candidate" "$nim_budget_seconds"
				continue
			fi
			assert_reasoning_effort_for_candidate "$model_candidate"
			safe_model="${model_candidate//[\/:]/-}"
			prompt_file="${RUNNER_TEMP}/opencode-review-${safe_model}-prompt.md"
			candidate_output_file="${RUNNER_TEMP}/opencode-review-${safe_model}.md"
			opencode_json_file="${candidate_output_file}.jsonl"
			opencode_export_file="${candidate_output_file}.session.json"
			write_prompt "$model_candidate" "$prompt_file"
			effective_attempts="$attempts"
			if is_schema_repair_candidate "$model_candidate"; then
				effective_attempts=$((effective_attempts + schema_repair_attempts))
			fi
			for attempt in $(seq 1 "$effective_attempts"); do
				if [ "$attempt" -gt "$attempts" ]; then
					write_schema_repair_prompt "$model_candidate" "$prompt_file"
					printf 'OpenCode %s schema-repair attempt %s/%s will re-review from trusted evidence with a non-replayable control checklist.\n' \
						"$model_candidate" "$attempt" "$effective_attempts"
				fi
				now="$SECONDS"
				if is_nvidia_nim_candidate "$model_candidate" &&
					[ "$nim_elapsed_seconds" -ge "$nim_budget_seconds" ]; then
					printf 'Stopping OpenCode %s retries because the NVIDIA NIM combined runtime budget of %ss is exhausted.\n' \
						"$model_candidate" "$nim_budget_seconds"
					break
				fi
				if [ "$deadline" -gt 0 ] && [ "$now" -ge "$deadline" ]; then
					printf 'OpenCode model pool retry deadline elapsed before %s attempt %s/%s.\n' "$model_candidate" "$attempt" "$effective_attempts"
					if finish_pool_without_model; then
						exit 0
					fi
					exit 1
				fi
				if [ "$max_total_attempts" -gt 0 ] && [ "$total_attempts" -ge "$max_total_attempts" ]; then
					printf 'OpenCode model pool reached the per-run provider attempt ceiling of %s attempts; ending the pool to bound provider spend. Set OPENCODE_POOL_MAX_TOTAL_ATTEMPTS=0 to disable.\n' "$max_total_attempts"
					if finish_pool_without_model; then
						exit 0
					fi
					exit 1
				fi
				total_attempts=$((total_attempts + 1))
				remaining="$original_run_timeout"
				if [ "$deadline" -gt 0 ]; then
					remaining=$((deadline - now))
				fi
				OPENCODE_RUN_TIMEOUT_SECONDS="$original_run_timeout"
				if [ "$deadline" -gt 0 ] && [ "$OPENCODE_RUN_TIMEOUT_SECONDS" -gt "$remaining" ]; then
					OPENCODE_RUN_TIMEOUT_SECONDS="$remaining"
				fi
				if is_nvidia_nim_candidate "$model_candidate"; then
					nim_remaining_seconds=$((nim_budget_seconds - nim_elapsed_seconds))
					if [ "$OPENCODE_RUN_TIMEOUT_SECONDS" -gt "$nim_remaining_seconds" ]; then
						printf 'OpenCode %s combined NVIDIA NIM budget cap selected %ss instead of %ss so fallback candidates retain retry budget.\n' \
							"$model_candidate" "$nim_remaining_seconds" "$OPENCODE_RUN_TIMEOUT_SECONDS"
						OPENCODE_RUN_TIMEOUT_SECONDS="$nim_remaining_seconds"
					fi
				fi
				uncapped_run_timeout="$OPENCODE_RUN_TIMEOUT_SECONDS"
				OPENCODE_RUN_TIMEOUT_SECONDS="$(cap_model_run_timeout "$model_candidate" "$OPENCODE_RUN_TIMEOUT_SECONDS")"
				if [ "$OPENCODE_RUN_TIMEOUT_SECONDS" -lt "$uncapped_run_timeout" ]; then
					printf 'OpenCode %s runtime cap selected %ss instead of %ss because this provider has a bounded failover window.\n' \
						"$model_candidate" "$OPENCODE_RUN_TIMEOUT_SECONDS" "$uncapped_run_timeout"
				fi
				export OPENCODE_RUN_TIMEOUT_SECONDS
				printf 'OpenCode %s attempt %s/%s using %ss run timeout with %ss retry budget remaining.\n' "$model_candidate" "$attempt" "$effective_attempts" "$OPENCODE_RUN_TIMEOUT_SECONDS" "$remaining"
				agent="${OPENCODE_AGENT:-ci-review-fallback}"
				if [ "$attempt" -eq 1 ] && [ -n "${OPENCODE_FIRST_ATTEMPT_AGENT:-}" ]; then
					agent="$OPENCODE_FIRST_ATTEMPT_AGENT"
				fi
				run_status=0
				nim_attempt_started="$SECONDS"
				if run_one_model_attempt "$model_candidate" "$attempt" "$effective_attempts" "$agent" "$prompt_file" "$candidate_output_file" "$opencode_json_file" "$opencode_export_file"; then
					cp "$candidate_output_file" "$OPENCODE_OUTPUT_FILE"
					record_review_model "$model_candidate"
					record_review_status "success"
					exit 0
				else
					run_status=$?
				fi
				if is_nvidia_nim_candidate "$model_candidate"; then
					nim_attempt_elapsed=$((SECONDS - nim_attempt_started))
					nim_elapsed_seconds=$((nim_elapsed_seconds + nim_attempt_elapsed))
					printf 'OpenCode NVIDIA NIM combined runtime used %ss/%ss after %s attempt %s/%s.\n' \
						"$nim_elapsed_seconds" "$nim_budget_seconds" "$model_candidate" "$attempt" "$effective_attempts"
				fi
				if [ "$run_status" -ne 3 ] && is_credit_exhausted_failure "$opencode_json_file" "${opencode_json_file}.stderr"; then
					dead_candidate_reasons[$model_candidate]="provider credits exhausted (HTTP 402 / payment required)"
					printf 'OpenCode %s provider credits are exhausted; marking this candidate failed for the rest of the run so retries cannot accrue further spend.\n' "$model_candidate"
					break
				fi
				if [ "$run_status" -eq 3 ]; then
					invalid_control_counts[$model_candidate]=$((${invalid_control_counts[$model_candidate]:-0} + 1))
					if [ "$invalid_control_cap" -gt 0 ] && [ "${invalid_control_counts[$model_candidate]}" -ge "$invalid_control_cap" ]; then
						dead_candidate_reasons[$model_candidate]="produced ${invalid_control_counts[$model_candidate]} control-rejected outputs"
						printf 'OpenCode %s produced %s control-rejected outputs; marking this candidate failed for the rest of the run so paid retries cannot loop on rejected output. Set OPENCODE_INVALID_CONTROL_OUTPUT_CAP=0 to disable.\n' \
							"$model_candidate" "${invalid_control_counts[$model_candidate]}"
						break
					fi
				fi
				if [ "$run_status" -eq 2 ]; then
					break
				fi
				if [ "$run_status" -ne 3 ] && [ "$attempt" -ge "$attempts" ]; then
					break
				fi
				if [ "$attempt" -lt "$effective_attempts" ] && [ "$attempt" -lt "$attempts" ]; then
					retry_sleep="$(backoff_sleep "$attempt")"
					if [ "$deadline" -gt 0 ] && [ $((SECONDS + retry_sleep)) -gt "$deadline" ]; then
						retry_sleep=$((deadline - SECONDS))
					fi
					if [ "$retry_sleep" -gt 0 ]; then
						printf 'Retrying OpenCode after exponential backoff of %ss.\n' "$retry_sleep"
						sleep "$retry_sleep"
					fi
				fi
			done
		done

		alive_candidates=0
		for model_candidate in "${model_candidates[@]}"; do
			if [ -z "${dead_candidate_reasons[$model_candidate]:-}" ]; then
				alive_candidates=$((alive_candidates + 1))
			fi
		done
		if [ "$alive_candidates" -eq 0 ]; then
			printf 'Every OpenCode model candidate is marked failed for this run; ending the pool without further provider spend.\n'
			if finish_pool_without_model; then
				exit 0
			fi
			exit 1
		fi

		printf 'OpenCode completed a full model-candidate cycle without a valid control conclusion; continuing until a model succeeds or the retry budget/GitHub Actions job timeout is reached.\n'
		if [ "$max_cycles" -gt 0 ] && [ "$cycle" -ge "$max_cycles" ]; then
			printf 'OpenCode model pool reached configured max cycle count %s without a valid control conclusion.\n' "$max_cycles"
			if finish_pool_without_model; then
				exit 0
			fi
			exit 1
		fi
		printf 'OpenCode retry budget and the workflow step timeout remain the outer guards for invalid or unavailable provider output.\n'
		cycle_sleep="${OPENCODE_POOL_CYCLE_SLEEP_SECONDS:-60}"
		if [ "$deadline" -gt 0 ] && [ $((SECONDS + cycle_sleep)) -gt "$deadline" ]; then
			cycle_sleep=$((deadline - SECONDS))
			if [ "$cycle_sleep" -le 0 ]; then
				printf 'OpenCode model pool retry deadline elapsed after cycle %s.\n' "$cycle"
				if finish_pool_without_model; then
					exit 0
				fi
				exit 1
			fi
		fi
		printf 'Restarting OpenCode model pool after %ss.\n' "$cycle_sleep"
		sleep "$cycle_sleep"
		cycle=$((cycle + 1))
	done
}

main "$@"
