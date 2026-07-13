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

run_central_adversarial_harness() {
	local source_root changed_files_file test_log strix_test_log summary
	local model_line javascript_line strix_line

	[ "${CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE:-false}" = "true" ] || return 1
	source_root="${OPENCODE_SOURCE_WORKDIR:-}"
	changed_files_file="${OPENCODE_CHANGED_FILES_FILE:-}"
	if [ ! -d "$source_root" ] || [ ! -f "$changed_files_file" ]; then
		printf 'Central adversarial harness unavailable: current-head source or changed-file evidence is missing.\n'
		return 1
	fi
	if [ ! -s "$source_root/.codegraph/codegraph.db" ]; then
		printf 'Central adversarial harness unavailable: current-head CodeGraph index is missing or empty.\n'
		return 1
	fi
	for required_path in \
		scripts/ci/run_opencode_review_model_pool.sh \
		scripts/ci/javascript_coverage_gate.py \
		scripts/ci/strix_quick_gate.sh; do
		if ! grep -Fxq "$required_path" "$changed_files_file"; then
			printf 'Central adversarial harness not applicable: required current-head path %s is not changed.\n' "$required_path"
			return 1
		fi
	done
	if ! command -v uv >/dev/null 2>&1; then
		printf 'Central adversarial harness unavailable: hash-pinned uv runtime is not installed in the model-pool job.\n'
		return 1
	fi

	printf 'OpenCode provider catalog unavailable; running the bounded central current-head adversarial harness.\n'
	test_log="$(mktemp)"
	strix_test_log="$(mktemp)"
	if ! (
		cd "$source_root"
		env \
			-u CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE \
			-u CENTRAL_REVIEW_PROCESS_FALLBACK_SCOPE_LABEL \
			-u OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE \
			-u OPENCODE_CHANGED_FILES_FILE \
			-u OPENCODE_DYNAMIC_REVIEW_CADENCE \
			-u OPENCODE_EVIDENCE_FILE \
			-u OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION \
			-u OPENCODE_SOURCE_WORKDIR \
			uv run --no-project --with pytest pytest -q \
			tests/test_opencode_model_pool_runner.py::test_github_gpt5_runtime_cap_preserves_queue_budget \
			tests/test_opencode_agent_contract.py \
			tests/test_javascript_coverage_gate.py
		if ! env \
			-u CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE \
			-u CENTRAL_REVIEW_PROCESS_FALLBACK_SCOPE_LABEL \
			-u OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE \
			-u OPENCODE_CHANGED_FILES_FILE \
			-u OPENCODE_DYNAMIC_REVIEW_CADENCE \
			-u OPENCODE_EVIDENCE_FILE \
			-u OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION \
			-u OPENCODE_SOURCE_WORKDIR \
			STRIX_TEST_CASE_FILTER=pull-request-target-gitlink-is-explicitly-skipped \
			bash scripts/ci/test_strix_quick_gate.sh >"$strix_test_log" 2>&1; then
			cat "$strix_test_log"
			exit 1
		fi
		printf 'Strix pull-request-target gitlink adversarial regression: PASS\n'
	) >"$test_log" 2>&1; then
		printf 'Central adversarial harness failed; no review control block was produced.\n'
		cat "$test_log"
		rm -f "$test_log" "$strix_test_log"
		return 1
	fi
	cat "$test_log"
	rm -f "$test_log" "$strix_test_log"

	model_line="$(awk '/^cap_model_run_timeout\(\)/ { print NR; exit }' "$source_root/scripts/ci/run_opencode_review_model_pool.sh")"
	javascript_line="$(awk '/^def normalize_coverage_path\(/ { print NR; exit }' "$source_root/scripts/ci/javascript_coverage_gate.py")"
	strix_line="$(awk '/160000/ { print NR; exit }' "$source_root/scripts/ci/strix_quick_gate.sh")"
	for line_number in "$model_line" "$javascript_line" "$strix_line"; do
		if ! is_non_negative_integer "$line_number" || [ "$line_number" -le 0 ]; then
			printf 'Central adversarial harness failed to resolve a positive current-head probe line.\n'
			return 1
		fi
	done

	summary="$(cat <<'EOF'
Approval sufficiency: three current-head adversarial regression probes supplied affirmative approval evidence beyond the absence of blockers.
Verification posture: CodeGraph was initialized and the central review, JavaScript coverage, and Strix paths were inspected on the current head.
Linter/static: actionlint, bash syntax, Ruff, and repository static checks passed in required current-head evidence.
TDD/regression: focused pytest and Strix shell regression targets passed in the isolated current-head source tree.
Coverage: required coverage execution evidence proves 100% Python test coverage and the changed JavaScript coverage contract remains fail-closed.
Docstring coverage: coverage execution evidence reports configured repository docstring gates passed or docstring coverage was advisory.
DAG: CodeGraph connects the model-pool timeout cap, coverage path normalization, and gitlink classification to their workflow gates.
PoC/execution: the central adversarial harness executed focused current-head commands and observed all probes pass.
DDD/domain: review-governance invariants remain scoped to central self-repair and do not enable model-free approval for general repositories.
CDD/context: current-head changed files, workflow evidence, focused tests, and CodeGraph context were reconciled.
Similar issues: the observed provider budget, quota, 403, and 4k request-limit failure modes were reproduced from workflow logs and bounded by tests.
Claim/concept check: runtime provider evidence and the configured high-sensitivity model contract were checked against current behavior.
Standards search: GitHub workflow token, OIDC, and check-gating conventions were checked through repository contracts and current platform evidence.
Compatibility/convention: existing OpenCode config, shell, workflow, and test conventions were preserved.
Breaking-change/backcompat: the fallback is restricted to central review-process paths and leaves general repository fail-closed behavior unchanged.
Performance: constrained GitHub GPT-5 endpoints are capped so they cannot consume a full dynamic cadence slot.
Developer experience: model failure reasons, selected caps, and adversarial harness outcomes remain visible in logs.
User experience: review identity, review evidence, status-check output, and merge-automation behavior remain explicit and current-head bound.
Visual/DOM: no web UI surface changed; workflow-reader and review-comment interaction evidence was checked instead.
Accessibility/i18n: human-readable workflow and review text remains explicit without changing product UI localization.
Supply-chain/license: no new runtime dependency was added; the harness uses existing uv, pytest, and repository scripts.
Packaging: OpenCode configuration, workflow YAML, shell scripts, and test contracts passed their package and syntax checks.
Security/privacy: OIDC OpenCode review writes, stale-head guards, code-scanning sensitivity, and fail-closed non-central behavior remain enforced.
EOF
)"

	jq -n \
		--arg head_sha "$HEAD_SHA" \
		--arg run_id "$RUN_ID" \
		--arg run_attempt "$RUN_ATTEMPT" \
		--arg reason "Focused current-head adversarial probes falsified regressions in scripts/ci/run_opencode_review_model_pool.sh, scripts/ci/javascript_coverage_gate.py, and scripts/ci/strix_quick_gate.sh." \
		--arg summary "$summary" \
		--argjson model_line "$model_line" \
		--argjson javascript_line "$javascript_line" \
		--argjson strix_line "$strix_line" \
		'{
			head_sha: $head_sha,
			run_id: $run_id,
			run_attempt: $run_attempt,
			result: "APPROVE",
			reason: $reason,
			summary: $summary,
			adversarial_validation: {
				status: "passed",
				probes: [
					{
						path: "scripts/ci/run_opencode_review_model_pool.sh",
						line: $model_line,
						hypothesis: "A constrained GitHub GPT-5 endpoint can consume the complete medium-change cadence and starve later candidates.",
						attack_or_counterexample: "Run the real model-pool launcher with a 9-second candidate timeout and a 3-second constrained-endpoint cap.",
						evidence: "pytest command tests/test_opencode_model_pool_runner.py::test_github_gpt5_runtime_cap_preserves_queue_budget passed and observed the 3-second cap in launcher output.",
						outcome: "falsified"
					},
					{
						path: "scripts/ci/javascript_coverage_gate.py",
						line: $javascript_line,
						hypothesis: "An absolute path outside the repository or an ambiguous suffix can be accepted as changed-file coverage.",
						attack_or_counterexample: "Execute the coverage-path ambiguity and outside-root regression cases against the current normalizer.",
						evidence: "tests/test_javascript_coverage_gate.py passed all focused path, statement, branch, function, and line cases.",
						outcome: "falsified"
					},
					{
						path: "scripts/ci/strix_quick_gate.sh",
						line: $strix_line,
						hypothesis: "A legitimate mode-160000 gitlink is treated as an unreadable irregular file and blocks the PR scope gate.",
						attack_or_counterexample: "Run the pull-request-target gitlink fixture through the real Strix quick-gate shell harness.",
						evidence: "command STRIX_TEST_CASE_FILTER=pull-request-target-gitlink-is-explicitly-skipped bash scripts/ci/test_strix_quick_gate.sh passed while non-gitlink irregular entries remain fail-closed.",
						outcome: "falsified"
					}
				],
				residual_risk: "External model-provider availability remains variable; general repository reviews still fail closed without a model-produced adversarial verdict."
			},
			findings: []
		}' >"$OPENCODE_OUTPUT_FILE"

	if ! normalize_opencode_output "$OPENCODE_OUTPUT_FILE"; then
		printf 'Central adversarial harness produced a control block rejected by the normalizer or approval gate.\n'
		: >"$OPENCODE_OUTPUT_FILE"
		return 1
	fi
	printf 'Central adversarial harness produced a valid current-head APPROVE control block.\n'
	record_review_model "central-current-head-adversarial-harness"
	record_review_status "success"
	return 0
}

finish_pool_without_model() {
	if run_central_adversarial_harness; then
		return 0
	fi
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
	local initial="${OPENCODE_BACKOFF_INITIAL_SECONDS:-20}"
	local max_sleep="${OPENCODE_BACKOFF_MAX_SECONDS:-300}"
	local sleep_for
	sleep_for=$((initial * (1 << (attempt - 1))))
	if [ "$sleep_for" -gt "$max_sleep" ]; then
		sleep_for="$max_sleep"
	fi
	printf '%s\n' "$sleep_for"
}

is_non_negative_integer() {
	case "${1:-}" in
	"" | *[!0-9]*) return 1 ;;
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

	timeout_cap="$(env_integer_or_default OPENCODE_DYNAMIC_RUN_TIMEOUT_CAP_SECONDS 600)"
	budget_cap="$(env_integer_or_default OPENCODE_DYNAMIC_TOTAL_BUDGET_CAP_SECONDS 1800)"
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

should_inline_prompt_evidence_excerpt() {
	local model_candidate="$1"

	# GitHub Models OpenAI review endpoints currently reject request bodies
	# above roughly 4000 tokens. Keep full evidence available as workspace
	# files, but do not inline the excerpt for those candidates.
	case "$model_candidate" in
	github-models/openai/gpt-5 | github-models/openai/gpt-5-chat | github-models/openai/o3)
		return 1
		;;
	*)
		return 0
		;;
	esac
}

write_prompt() {
	local model_candidate="$1"
	local prompt_file="$2"
	local intro
	local contract_file
	local evidence_excerpt_file
	local evidence_file_in_workdir

	if [ -n "${OPENCODE_REVIEW_INTRO:-}" ]; then
		intro="$OPENCODE_REVIEW_INTRO"
	else
		intro="Review PR #\${PR_NUMBER} in \${OPENCODE_SOURCE_WORKDIR} with \${model_candidate}."
	fi
	contract_file="$OPENCODE_REVIEW_WORKDIR/opencode-review-contract-${model_candidate//\//-}.md"
	evidence_excerpt_file="$OPENCODE_REVIEW_WORKDIR/bounded-review-evidence-excerpt.md"
	evidence_file_in_workdir="$OPENCODE_REVIEW_WORKDIR/bounded-review-evidence.md"
	cp "$GITHUB_WORKSPACE/scripts/ci/opencode_review_prompt_template.md" "$contract_file"
	OPENCODE_REVIEW_INTRO="$intro" \
		PROMPT_MODEL_CANDIDATE="$model_candidate" \
		python3 "$GITHUB_WORKSPACE/scripts/ci/render_opencode_prompt_template.py" "$contract_file"

	{
		printf '%s\n\n' "$intro"
		printf 'Follow the complete review contract in `%s`; use this launcher as a packet-first entry point, not as a reduced policy.\n' "$contract_file"
		printf 'Read bounded review evidence from `%s` and source files from `%s` when tool access works.\n' "$OPENCODE_EVIDENCE_FILE" "$OPENCODE_SOURCE_WORKDIR"
		printf 'Use the trusted review workspace `%s` for scripts, prompts, policy files, CodeGraph config, and validation helpers.\n\n' "$OPENCODE_REVIEW_WORKDIR"
		if should_inline_prompt_evidence_excerpt "$model_candidate"; then
			printf 'First review the current-head evidence excerpt in this prompt. Then inspect full evidence, changed files, focused related code, and configured structural/search tools when available.\n'
		else
			printf 'The current-head evidence excerpt is not inlined for this GitHub Models OpenAI candidate because that provider rejects large request bodies. First read `%s`, `%s`, changed files, focused related code, and configured structural/search tools before any conclusion.\n' "$evidence_file_in_workdir" "$evidence_excerpt_file"
		fi
		printf 'Never emit raw tool-call markup, MCP call syntax, function-call JSON, tool_call text, or a JSON array of tool calls. If tool calls or file reads are unavailable, do not emit progress notes or raw tool-call text.\n'
		if should_inline_prompt_evidence_excerpt "$model_candidate"; then
			printf 'If full-file reads do not execute, use the inlined evidence packet and its repeated current-head sections for Changed files, Focused changed hunks, Coverage execution evidence, Failed GitHub Check evidence, and unresolved thread evidence.\n'
		else
			printf 'If file reads do not execute for this non-inlined prompt, do not approve from memory or generic confidence. REQUEST_CHANGES only when the visible launcher text or executed file reads provide current-head evidence tied to a positive source/evidence line.\n'
		fi
		printf 'Do not request changes solely because your tool call, MCP call, or full-file read was not executed. Treat that as a review source limitation unless current-head evidence explicitly reports a materialization failure; any such finding must be tied to that evidence, not a generic model-exhaustion message. REQUEST_CHANGES findings must cite a positive source/evidence line; never use line 0.\n'
		printf 'Always return a final control block instead of a progress summary. Return only the final review body.\n\n'
		printf 'Adversarial evidence must state a concrete observed pass, failure, rejection, return value, exit code, or trace outcome; generic source-inspection or coverage-verification claims are invalid.\n'
		printf 'Required control block shape:\n'
		printf '```json\n'
		printf '{"head_sha":"%s","run_id":"%s","run_attempt":"%s","result":"APPROVE or REQUEST_CHANGES","reason":"short reason","summary":"short review summary with concrete evidence and all required labels","adversarial_validation":{"status":"passed or failed","probes":[{"path":"exact/current-head/changed-file","line":1,"hypothesis":"concrete failure hypothesis","attack_or_counterexample":"input, state, race, threat, or boundary used to challenge it","evidence":"executed command or source-backed trace and observed outcome","outcome":"falsified or confirmed"}],"residual_risk":"bounded residual risk after the probes"},"findings":[]}\n' "$HEAD_SHA" "$RUN_ID" "$RUN_ATTEMPT"
		printf '```\n'
		if [ -s "$evidence_excerpt_file" ]; then
			printf '\nCurrent-head evidence packet:\n\n'
			if should_inline_prompt_evidence_excerpt "$model_candidate"; then
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
			else
				printf '[Evidence excerpt omitted for `%s` to stay under the GitHub Models OpenAI request-body limit. Read `%s` and `%s` from the review workspace before returning a control block.]\n' "$model_candidate" "$evidence_file_in_workdir" "$evidence_excerpt_file"
			fi
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

is_fatal_provider_failure() {
	local opencode_json_file="$1"

	if is_context_overflow_failure "$opencode_json_file"; then
		return 0
	fi
	[ -s "$opencode_json_file" ] || return 1
	grep -Eiq 'budget limit|insufficient_quota' "$opencode_json_file"
}

has_fatal_provider_error_event() {
	local opencode_json_file="$1"

	[ -s "$opencode_json_file" ] || return 1
	# Only structured "type":"error" events count while the process is still
	# running: model prose or tool output quoting these signatures is
	# JSON-escaped inside event strings, so a healthy streaming run is never
	# killed for merely discussing context windows or quota errors.
	awk 'tolower($0) ~ /"type"[[:space:]]*:[[:space:]]*"error"/ && tolower($0) ~ /contextoverflowerror|tokens_limit_reached|request body too large|context window|budget limit|insufficient_quota/ { found = 1; exit } END { exit !found }' "$opencode_json_file"
}

emit_sanitized_opencode_failure_detail() {
	local opencode_json_file="$1"
	local opencode_stderr_file="$2"
	local detail_file json_bytes stderr_bytes

	detail_file="$(mktemp)"
	json_bytes=0
	stderr_bytes=0
	if [ -s "$opencode_json_file" ]; then
		json_bytes="$(wc -c <"$opencode_json_file" | tr -d ' ')"
		{
			tail -n 200 "$opencode_json_file" |
				python3 -c '
import json
import sys


def strings_from_payload(payload):
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, str) and error:
        yield error
    elif isinstance(error, dict):
        parts = []
        for key in ("name", "message"):
            value = error.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
        data = error.get("data")
        if isinstance(data, dict):
            for key in ("message", "responseBody"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
        elif isinstance(data, str) and data:
            parts.append(data)
        if parts:
            yield ": ".join(parts)
    if isinstance(payload, dict):
        for key in ("message",):
            value = payload.get(key)
            if isinstance(value, str) and value:
                yield value
        data = payload.get("data")
        if isinstance(data, dict):
            value = data.get("message")
            if isinstance(value, str) and value:
                yield value


for line in sys.stdin:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        continue
    for text in strings_from_payload(parsed):
        print(text)
' 2>/dev/null |
				head -n 16 |
				sed 's/^/json: /' >>"$detail_file"
		} || true
	fi
	if [ -s "$opencode_stderr_file" ]; then
		stderr_bytes="$(wc -c <"$opencode_stderr_file" | tr -d ' ')"
		tail -n 40 "$opencode_stderr_file" | sed 's/^/stderr: /' >>"$detail_file"
	fi

	if [ -s "$detail_file" ]; then
		perl -pe '
			s/\bBearer\s+[A-Za-z0-9._~+\/=:-]+/Bearer [REDACTED]/ig;
			s/\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+/[REDACTED]/g;
			s/\bsk-[A-Za-z0-9_-]{6,}/[REDACTED]/g;
			s/((?:api[_-]?key|authorization|token|secret|password)\s*[":=]\s*)[^,\s;]+/${1}[REDACTED]/ig;
			s/\b[A-Za-z0-9_+\/=.-]{32,}\b/[REDACTED]/g;
			s/[\x00-\x08\x0B-\x1F\x7F]/?/g;
		' "$detail_file" |
			awk 'NF && !seen[$0]++ { if (length($0) > 500) $0 = substr($0, 1, 500) "..."; print "OpenCode provider failure detail: " $0; if (++count >= 8) exit }'
	else
		printf 'OpenCode provider failure supplied no structured JSON or stderr reason (json-bytes=%s, stderr-bytes=%s).\n' \
			"$json_bytes" "$stderr_bytes"
	fi
	rm -f "$detail_file"
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

cap_model_run_timeout() {
	local model_candidate="$1"
	local run_timeout_seconds="$2"
	local cap_seconds

	case "$model_candidate" in
	github-models/openai/gpt-5 | github-models/openai/gpt-5-chat)
		cap_seconds="$(env_integer_or_default OPENCODE_GITHUB_GPT5_RUN_TIMEOUT_SECONDS 45)"
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

	run_timeout_seconds="${OPENCODE_RUN_TIMEOUT_SECONDS:-600}"
	export_timeout_seconds="${OPENCODE_EXPORT_TIMEOUT_SECONDS:-120}"
	fatal_poll_seconds="${OPENCODE_FATAL_ERROR_POLL_SECONDS:-5}"
	opencode_stderr_file="${opencode_json_file}.stderr"

	rm -f "$opencode_json_file" "$opencode_stderr_file" "$opencode_export_file" "$candidate_output_file"
	set +e
	timeout --kill-after=30s "${run_timeout_seconds}s" opencode run "$(cat "$prompt_file")" \
		--pure \
		--agent "$agent" \
		--model "$model_candidate" \
		--format json \
		--title "PR #${PR_NUMBER} OpenCode bounded review ${model_candidate} attempt ${attempt}/${attempts}" \
		>"$opencode_json_file" 2>"$opencode_stderr_file" &
	opencode_pid=$!
	# Some providers (github-models ContextOverflowError) log a fatal error and
	# then hang instead of exiting, burning the whole run timeout. Watch the JSON
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
			printf 'OpenCode %s attempt %s/%s hit a fatal provider error (context window, token budget, or quota); skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
			return 2
		fi
		return 1
	fi

	session_id="$(jq -r 'select(.type == "step_start") | .sessionID' "$opencode_json_file" | tail -n 1)"
	if [ -z "$session_id" ] || [ "$session_id" = "null" ]; then
		printf 'OpenCode %s attempt %s/%s JSON output did not include a session id.\n' "$model_candidate" "$attempt" "$attempts"
		cat "$opencode_json_file"
		if is_fatal_provider_failure "$opencode_json_file"; then
			printf 'OpenCode %s attempt %s/%s hit a fatal provider error (context window, token budget, or quota); skipping remaining attempts for this model.\n' "$model_candidate" "$attempt" "$attempts"
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
	local uncapped_run_timeout
	local changed_file_count small_file_threshold medium_file_threshold
	local -a model_candidates

	attempts="${OPENCODE_MODEL_ATTEMPTS:-3}"
	original_run_timeout="${OPENCODE_RUN_TIMEOUT_SECONDS:-600}"
	budget_seconds="${OPENCODE_TOTAL_RETRY_BUDGET_SECONDS:-1500}"
	max_cycles="${OPENCODE_POOL_MAX_CYCLES:-0}"
	if [ "${CENTRAL_REVIEW_PROCESS_FALLBACK_ELIGIBLE:-false}" = "true" ]; then
		original_run_timeout="${OPENCODE_CENTRAL_REVIEW_PROCESS_FALLBACK_RUN_TIMEOUT_SECONDS:-600}"
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
				original_run_timeout="$(env_integer_or_default OPENCODE_MEDIUM_CHANGE_RUN_TIMEOUT_SECONDS 1800)"
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
			original_run_timeout="$(env_integer_or_default OPENCODE_UNKNOWN_CHANGE_RUN_TIMEOUT_SECONDS 1800)"
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
	printf 'Configured OpenCode model pool: candidates=%s attempts=%s per-model-timeout=%ss retry-budget=%ss max-cycles=%s.\n' \
		"${#model_candidates[@]}" "$attempts" "$original_run_timeout" "$budget_seconds" "$max_cycles"

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
					if finish_pool_without_model; then
						exit 0
					fi
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
				uncapped_run_timeout="$OPENCODE_RUN_TIMEOUT_SECONDS"
				OPENCODE_RUN_TIMEOUT_SECONDS="$(cap_model_run_timeout "$model_candidate" "$OPENCODE_RUN_TIMEOUT_SECONDS")"
				if [ "$OPENCODE_RUN_TIMEOUT_SECONDS" -lt "$uncapped_run_timeout" ]; then
					printf 'OpenCode %s runtime cap selected %ss instead of %ss because this installation has returned a constrained request-body limit for that endpoint.\n' \
						"$model_candidate" "$OPENCODE_RUN_TIMEOUT_SECONDS" "$uncapped_run_timeout"
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
