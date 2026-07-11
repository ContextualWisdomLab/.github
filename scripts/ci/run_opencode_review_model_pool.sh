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
	local initial="${OPENCODE_BACKOFF_INITIAL_SECONDS:-20}"
	local max_sleep="${OPENCODE_BACKOFF_MAX_SECONDS:-300}"
	local sleep_for
	sleep_for=$((initial * (1 << (attempt - 1))))
	if [ "$sleep_for" -gt "$max_sleep" ]; then
		sleep_for="$max_sleep"
	fi
	printf '%s\n' "$sleep_for"
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
	contract_file="$OPENCODE_REVIEW_WORKDIR/opencode-review-contract-${model_candidate//\//-}.md"
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
		printf 'Required control block shape:\n'
		printf '```json\n'
		printf '{"head_sha":"%s","run_id":"%s","run_attempt":"%s","result":"APPROVE or REQUEST_CHANGES","reason":"short reason","summary":"short review summary with concrete evidence and all required labels","findings":[]}\n' "$HEAD_SHA" "$RUN_ID" "$RUN_ATTEMPT"
		printf '```\n'
		if [ -s "$evidence_excerpt_file" ]; then
			printf '\nCurrent-head evidence packet:\n\n'
			cat "$evidence_excerpt_file"
			printf '\n'
		fi
	} >"$prompt_file"
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

is_direct_openai_candidate() {
	case "$1" in
	openai/*) return 0 ;;
	*) return 1 ;;
	esac
}

is_low_sensitivity_candidate() {
	case "$1" in
	openai/*-mini | openai/*-nano | \
		github-models/openai/*-mini | github-models/openai/*-nano)
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
	return 1
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
	local run_timeout_seconds export_timeout_seconds opencode_status session_id

	run_timeout_seconds="${OPENCODE_RUN_TIMEOUT_SECONDS:-600}"
	export_timeout_seconds="${OPENCODE_EXPORT_TIMEOUT_SECONDS:-60}"

	rm -f "$opencode_json_file" "$opencode_export_file" "$candidate_output_file"
	set +e
	timeout --kill-after=30s "${run_timeout_seconds}s" opencode run "$(cat "$prompt_file")" \
		--pure \
		--agent "$agent" \
		--model "$model_candidate" \
		--format json \
		--title "PR #${PR_NUMBER} OpenCode bounded review ${model_candidate} attempt ${attempt}/${attempts}" >"$opencode_json_file"
	opencode_status=$?
	set -e
	if [ "$opencode_status" -ne 0 ]; then
		printf 'OpenCode %s attempt %s/%s failed with exit %s.\n' "$model_candidate" "$attempt" "$attempts" "$opencode_status"
		if [ "$opencode_status" -eq 124 ] || [ "$opencode_status" -eq 137 ]; then
			printf 'OpenCode %s attempt %s/%s timed out after %ss; falling through within the remaining retry budget instead of blocking the org queue.\n' "$model_candidate" "$attempt" "$attempts" "$run_timeout_seconds"
		fi
		if is_context_overflow_failure "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s exceeded the provider context window; skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
			return 2
		fi
		return 1
	fi

	session_id="$(jq -r 'select(.type == "step_start") | .sessionID' "$opencode_json_file" | tail -n 1)"
	if [ -z "$session_id" ] || [ "$session_id" = "null" ]; then
		printf 'OpenCode %s attempt %s/%s JSON output did not include a session id.\n' "$model_candidate" "$attempt" "$attempts"
		cat "$opencode_json_file"
		if is_context_overflow_failure "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s exceeded the provider context window; skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
			return 2
		fi
		return 1
	fi
	if ! timeout --kill-after=15s "${export_timeout_seconds}s" opencode export "$session_id" --pure >"$opencode_export_file"; then
		printf 'OpenCode %s attempt %s/%s session export did not complete within %ss.\n' "$model_candidate" "$attempt" "$attempts" "$export_timeout_seconds"
		return 1
	fi
	jq -r '.messages[] | select(.info.role == "assistant") | .parts[]? | select(.type == "text") | .text' "$opencode_export_file" >"$candidate_output_file"
	if [ ! -s "$candidate_output_file" ]; then
		printf 'OpenCode %s attempt %s/%s session export did not include assistant text.\n' "$model_candidate" "$attempt" "$attempts"
		cat "$opencode_export_file"
		return 1
	fi
	if ! normalize_opencode_output "$candidate_output_file"; then
		printf 'OpenCode %s attempt %s/%s output did not include a valid control conclusion.\n' "$model_candidate" "$attempt" "$attempts"
		cat "$candidate_output_file"
		return 1
	fi
	return 0
}

main() {
	local attempts budget_seconds deadline now remaining model_candidate attempt safe_model prompt_file candidate_output_file
	local opencode_json_file opencode_export_file agent retry_sleep original_run_timeout run_status cycle_sleep cycle max_cycles
	local -a model_candidates

	attempts="${OPENCODE_MODEL_ATTEMPTS:-3}"
	original_run_timeout="${OPENCODE_RUN_TIMEOUT_SECONDS:-600}"
	budget_seconds="${OPENCODE_TOTAL_RETRY_BUDGET_SECONDS:-2400}"
	max_cycles="${OPENCODE_POOL_MAX_CYCLES:-0}"
	deadline=0
	if [ "$budget_seconds" -gt 0 ]; then
		deadline=$((SECONDS + budget_seconds))
	fi
	: >"$OPENCODE_OUTPUT_FILE"
	cd "$OPENCODE_REVIEW_WORKDIR"
	read -r -a model_candidates <<<"${OPENCODE_MODEL_CANDIDATES:-}"
	if [ "${#model_candidates[@]}" -eq 0 ]; then
		printf 'OpenCode model pool has no configured model candidates.\n'
		record_pool_exhausted
		exit 1
	fi

	cycle=1
	while :; do
		printf 'Starting OpenCode model pool cycle %s.\n' "$cycle"
		for model_candidate in "${model_candidates[@]}"; do
			if should_skip_model_candidate "$model_candidate"; then
				continue
			fi
			assert_reasoning_effort_for_candidate "$model_candidate"
			safe_model="${model_candidate//\//-}"
			prompt_file="${RUNNER_TEMP}/opencode-review-${safe_model}-prompt.md"
			candidate_output_file="${RUNNER_TEMP}/opencode-review-${safe_model}.md"
			opencode_json_file="${candidate_output_file}.jsonl"
			opencode_export_file="${candidate_output_file}.session.json"
			write_prompt "$model_candidate" "$prompt_file"
			for attempt in $(seq 1 "$attempts"); do
				now="$SECONDS"
				if [ "$deadline" -gt 0 ] && [ "$now" -ge "$deadline" ]; then
					printf 'OpenCode model pool retry deadline elapsed before %s attempt %s/%s.\n' "$model_candidate" "$attempt" "$attempts"
					record_pool_exhausted
					exit 1
				fi
				remaining="$original_run_timeout"
				if [ "$deadline" -gt 0 ]; then
					remaining=$((deadline - now))
				fi
				OPENCODE_RUN_TIMEOUT_SECONDS="$original_run_timeout"
				if [ "$deadline" -gt 0 ] && [ "$OPENCODE_RUN_TIMEOUT_SECONDS" -gt "$remaining" ]; then
					OPENCODE_RUN_TIMEOUT_SECONDS="$remaining"
				fi
				export OPENCODE_RUN_TIMEOUT_SECONDS
				printf 'OpenCode %s attempt %s/%s using %ss run timeout with %ss retry budget remaining.\n' "$model_candidate" "$attempt" "$attempts" "$OPENCODE_RUN_TIMEOUT_SECONDS" "$remaining"
				agent="${OPENCODE_AGENT:-ci-review-fallback}"
				if [ "$attempt" -eq 1 ] && [ -n "${OPENCODE_FIRST_ATTEMPT_AGENT:-}" ]; then
					agent="$OPENCODE_FIRST_ATTEMPT_AGENT"
				fi
				run_status=0
				if run_one_model_attempt "$model_candidate" "$attempt" "$attempts" "$agent" "$prompt_file" "$candidate_output_file" "$opencode_json_file" "$opencode_export_file"; then
					cp "$candidate_output_file" "$OPENCODE_OUTPUT_FILE"
					record_review_model "$model_candidate"
					record_review_status "success"
					exit 0
				else
					run_status=$?
				fi
				if [ "$run_status" -eq 2 ]; then
					break
				fi
				if [ "$attempt" -lt "$attempts" ]; then
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

		printf 'OpenCode completed a full model-candidate cycle without a valid control conclusion; continuing until a model succeeds or the configured retry deadline is reached.\n'
		if [ "$max_cycles" -gt 0 ] && [ "$cycle" -ge "$max_cycles" ]; then
			printf 'OpenCode model pool reached configured max cycle count %s without a valid control conclusion.\n' "$max_cycles"
			record_pool_exhausted
			exit 1
		fi
		printf 'OpenCode retry budget and the workflow step timeout remain the outer guards for invalid or unavailable provider output.\n'
		cycle_sleep="${OPENCODE_POOL_CYCLE_SLEEP_SECONDS:-60}"
		if [ "$deadline" -gt 0 ] && [ $((SECONDS + cycle_sleep)) -gt "$deadline" ]; then
			cycle_sleep=$((deadline - SECONDS))
			if [ "$cycle_sleep" -le 0 ]; then
				printf 'OpenCode model pool retry deadline elapsed after cycle %s.\n' "$cycle"
				record_pool_exhausted
				exit 1
			fi
		fi
		printf 'Restarting OpenCode model pool after %ss.\n' "$cycle_sleep"
		sleep "$cycle_sleep"
		cycle=$((cycle + 1))
	done
}

main "$@"
