#!/usr/bin/env python3
"""Apply the bounded issue-952 repair to large trusted workflow/gate files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source marker and fail on drift or duplicate matches."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def replace_range(
    text: str, start_marker: str, end_marker: str, replacement: str, label: str
) -> str:
    """Replace one bounded source range while retaining its end marker."""
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker missing")
    if text.find(start_marker, start + 1) >= 0:
        raise RuntimeError(f"{label}: start marker is ambiguous")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker missing")
    return text[:start] + replacement + text[end:]


def patch_workflow() -> None:
    """Patch the base-executed Strix installation and required-check wrapper."""
    path = ROOT / ".github" / "workflows" / "strix.yml"
    text = path.read_text(encoding="utf-8")
    old_install = (
        "          python3 -m pip install --disable-pip-version-check "
        "--no-cache-dir --require-hashes -r requirements-strix-ci-hashes.txt"
    )
    new_install = (
        "          # The compiled hash lock is the complete closed dependency set.\n"
        "          # Avoid re-applying stale transitive metadata constraints at install time.\n"
        "          python3 -m pip install --disable-pip-version-check --no-cache-dir "
        "--require-hashes --no-deps -r requirements-strix-ci-hashes.txt\n"
        "          python3 -I scripts/ci/validate_strix_runtime_compatibility.py "
        "requirements-strix-ci-hashes.txt"
    )
    text = replace_once(text, old_install, new_install, "Strix installer")

    export_marker = (
        '          test -f "$trusted_strix_source/scripts/ci/'
        'strix_required_workflow_smoke.sh"\n'
    )
    export_replacement = (
        export_marker
        + '          test -f "$trusted_strix_source/scripts/ci/'
        'strix_report_semantics.py"\n'
        + '          test -f "$trusted_strix_source/scripts/ci/'
        'validate_strix_runtime_compatibility.py"\n'
    )
    text = replace_once(
        text, export_marker, export_replacement, "trusted Strix helper export"
    )

    wrapper_start = "          # Capture the gate exit code plus its console output."
    wrapper_end = "      - name: Collect Strix reports for artifact upload"
    fail_closed_wrapper = """          # Preserve the gate exit code and console output. An incomplete backend
          # run is not security evidence, so every non-zero gate result remains
          # fail-closed while the following always() steps preserve diagnostics.
          strix_run_log="$RUNNER_TEMP/strix_gate_console.log"
          strix_rc=0
          set +e
          bash "$TRUSTED_STRIX_GATE" 2>&1 | tee "$strix_run_log"
          strix_rc="${PIPESTATUS[0]}"
          set -e
          if [ "$strix_rc" -ne 0 ]; then
            echo "Strix did not produce complete passing security evidence; failing the required check (gate exit ${strix_rc})." >&2
          fi
          exit "$strix_rc"

"""
    text = replace_range(
        text,
        wrapper_start,
        wrapper_end,
        fail_closed_wrapper,
        "required Strix fail-closed wrapper",
    )
    path.write_text(text, encoding="utf-8")


def insert_skip_in_function(text: str, function_name: str, marker: str) -> str:
    """Insert self-negating-report skipping once inside a named shell function."""
    function_start = text.find(f"{function_name}() {{")
    if function_start < 0:
        raise RuntimeError(f"missing shell function: {function_name}")
    marker_position = text.find(marker, function_start)
    if marker_position < 0:
        raise RuntimeError(f"{function_name}: insertion marker missing")
    next_function = text.find("\n}\n\n", function_start)
    if next_function >= 0 and marker_position > next_function:
        raise RuntimeError(f"{function_name}: insertion marker escaped function")
    replacement = marker.replace(
        '\t\t\trank="$(extract_max_severity_rank "$vuln_file")"',
        '\t\t\tif vulnerability_file_is_retryable_model_inconsistency "$vuln_file"; then\n'
        '\t\t\t\tcontinue\n'
        '\t\t\tfi\n'
        '\t\t\trank="$(extract_max_severity_rank "$vuln_file")"',
    )
    if replacement == marker:
        raise RuntimeError(f"{function_name}: unsupported insertion marker")
    return text[:marker_position] + replacement + text[marker_position + len(marker) :]


def patch_gate() -> None:
    """Import authoritative output before judgment and classify pseudo-findings."""
    path = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
    text = path.read_text(encoding="utf-8")

    import_marker = (
        '\tpreserve_attempt_log "$model" "$rc"\n\n'
        '\tsanitize_known_strix_report_warnings'
    )
    import_replacement = '''\tpreserve_attempt_log "$model" "$rc"\n
\tlocal authoritative_reports_dir="${resolved_target_path%/}/strix_runs"
\tif [ -L "$authoritative_reports_dir" ] || { [ -e "$authoritative_reports_dir" ] && [ ! -d "$authoritative_reports_dir" ]; }; then
\t\techo "Strix authoritative report output is not a regular directory; failing closed." | tee -a "$STRIX_LOG" >&2
\t\tINFRA_ERROR_DETECTED=1
\t\treturn 1
\tfi
\tif [ -d "$authoritative_reports_dir" ]; then
\t\tlocal imported_report_count
\t\tif ! imported_report_count="$(python3 -I "$SCRIPT_DIR/strix_report_semantics.py" import-current-attempt "$authoritative_reports_dir" "$ACTIVE_REPORTS_DIR" "$start_epoch" "${PR_BASE_SHA:-}" "${PR_HEAD_SHA:-}")"; then
\t\t\techo "Strix authoritative report import failed; failing closed." | tee -a "$STRIX_LOG" >&2
\t\t\tINFRA_ERROR_DETECTED=1
\t\t\treturn 1
\t\tfi
\t\tif [ "$imported_report_count" -gt 0 ]; then
\t\t\tprintf "Imported %s current-attempt Strix report file(s) from the authoritative target output path.\\n" "$imported_report_count" >&2
\t\tfi
\tfi

\tsanitize_known_strix_report_warnings'''
    text = replace_once(
        text, import_marker, import_replacement, "authoritative report import"
    )

    function_marker = '''vulnerability_file_is_retryable_model_inconsistency() {
\tlocal vuln_file="$1"
\tif ! vulnerability_file_is_below_threshold "$vuln_file"; then'''
    function_replacement = '''vulnerability_file_is_self_negating_no_finding() {
\tlocal vuln_file="$1"
\tpython3 -I "$SCRIPT_DIR/strix_report_semantics.py" is-self-negating "$vuln_file"
}

vulnerability_file_is_retryable_model_inconsistency() {
\tlocal vuln_file="$1"
\tif vulnerability_file_is_self_negating_no_finding "$vuln_file"; then
\t\techo "Detected a self-negating Strix no-finding record with contradictory severity metadata; excluding it from vulnerability severity decisions." >&2
\t\treturn 0
\tfi
\tif ! vulnerability_file_is_below_threshold "$vuln_file"; then'''
    text = replace_once(
        text, function_marker, function_replacement, "self-negating report classifier"
    )

    rank_marker = '''\t\tfor vuln_file in "$vulnerabilities_dir"/*.md; do
\t\t\tif [ ! -f "$vuln_file" ] || [ -L "$vuln_file" ]; then
\t\t\t\tcontinue
\t\t\tfi
\t\t\trank="$(extract_max_severity_rank "$vuln_file")"'''
    text = insert_skip_in_function(
        text, "has_unmapped_threshold_report", rank_marker
    )

    below_marker = '''\t\tfor vuln_file in "$vulnerabilities_dir"/*.md; do
\t\t\tif [ ! -f "$vuln_file" ] || [ -L "$vuln_file" ]; then
\t\t\t\tcontinue
\t\t\tfi

\t\t\tfound_any_vuln_file=1'''
    below_replacement = '''\t\tfor vuln_file in "$vulnerabilities_dir"/*.md; do
\t\t\tif [ ! -f "$vuln_file" ] || [ -L "$vuln_file" ]; then
\t\t\t\tcontinue
\t\t\tfi
\t\t\tif vulnerability_file_is_retryable_model_inconsistency "$vuln_file"; then
\t\t\t\tcontinue
\t\t\tfi

\t\t\tfound_any_vuln_file=1'''
    function_start = text.find("has_only_below_threshold_vulnerabilities() {")
    marker_position = text.find(below_marker, function_start)
    if function_start < 0 or marker_position < 0:
        raise RuntimeError("below-threshold report loop marker missing")
    text = text[:marker_position] + below_replacement + text[marker_position + len(below_marker) :]

    severity_marker = '''\t\tfor vuln_file in "$vulnerabilities_dir"/*.md; do
\t\t\tif [ ! -f "$vuln_file" ] || [ -L "$vuln_file" ]; then
\t\t\t\tcontinue
\t\t\tfi
\t\t\tif grep -Eiq 'severity[[:space:]]*:' "$vuln_file"; then'''
    severity_replacement = '''\t\tfor vuln_file in "$vulnerabilities_dir"/*.md; do
\t\t\tif [ ! -f "$vuln_file" ] || [ -L "$vuln_file" ]; then
\t\t\t\tcontinue
\t\t\tfi
\t\t\tif vulnerability_file_is_retryable_model_inconsistency "$vuln_file"; then
\t\t\t\tcontinue
\t\t\tfi
\t\t\tif grep -Eiq 'severity[[:space:]]*:' "$vuln_file"; then'''
    function_start = text.find("has_any_reported_severity_markers() {")
    marker_position = text.find(severity_marker, function_start)
    if function_start < 0 or marker_position < 0:
        raise RuntimeError("reported-severity loop marker missing")
    text = text[:marker_position] + severity_replacement + text[marker_position + len(severity_marker) :]

    path.write_text(text, encoding="utf-8")


def patch_nvidia_contract_test() -> None:
    """Replace obsolete neutral-success assertions with fail-closed assertions."""
    path = ROOT / "tests" / "test_strix_nvidia_nim_not_found_fallback.py"
    text = path.read_text(encoding="utf-8")
    helper_start = text.find("def _workflow_signal_pattern(")
    helper_end = text.find("\n\nclass StrixNvidiaNotFoundFallbackTests", helper_start)
    if helper_start < 0 or helper_end < 0:
        raise RuntimeError("NVIDIA outer-neutralization helper range missing")
    text = text[:helper_start] + text[helper_end + 2 :]

    tests_start = text.find(
        "    def test_outer_workflow_requires_litellm_context_for_nvidia_404"
    )
    tests_end = text.find("\n\nif __name__ == \"__main__\":", tests_start)
    if tests_start < 0 or tests_end < 0:
        raise RuntimeError("NVIDIA outer-neutralization tests range missing")
    replacement = '''    def test_outer_workflow_keeps_provider_failures_fail_closed(self) -> None:
        """Provider fallback belongs inside the gate; its required wrapper preserves rc."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("backend_unavailable_signal=", workflow)
        self.assertNotIn("reported_vulnerability_signal=", workflow)
        self.assertNotIn("Treating as a neutral skip", workflow)
        self.assertIn('exit "$strix_rc"', workflow)
        self.assertIn(
            "Strix did not produce complete passing security evidence",
            workflow,
        )'''
    text = text[:tests_start] + replacement + text[tests_end:]
    path.write_text(text, encoding="utf-8")


def patch_required_smoke() -> None:
    """Extend the bounded required-path smoke with issue-952 invariants."""
    path = ROOT / "scripts" / "ci" / "strix_required_workflow_smoke.sh"
    text = path.read_text(encoding="utf-8")
    marker = (
        'assert_file_contains "$workflow_file" "requirements-strix-ci-hashes.txt" '
        '"Strix workflow can materialize the central Strix hashed requirements lock"\n'
    )
    replacement = marker + (
        'assert_file_contains "$workflow_file" "--require-hashes --no-deps -r '
        'requirements-strix-ci-hashes.txt" "Strix workflow installs the complete hashed '
        'lock without dependency re-resolution"\n'
        'assert_file_contains "$workflow_file" "validate_strix_runtime_compatibility.py" '
        '"Strix workflow verifies exact pins and executable cryptographic consumers"\n'
    )
    text = replace_once(text, marker, replacement, "required smoke install contract")
    marker = (
        'assert_file_contains "$workflow_file" \'bash "$TRUSTED_STRIX_GATE"\' '
        '"Strix workflow executes central Strix gate"\n'
    )
    replacement = marker + (
        'assert_file_not_contains "$workflow_file" "Treating as a neutral skip" '
        '"Strix required wrapper never converts incomplete scans to success"\n'
        'assert_file_contains "$gate_script" "import-current-attempt" '
        '"Strix gate imports authoritative current-attempt reports before judgment"\n'
        'assert_file_contains "$gate_script" "vulnerability_file_is_self_negating_no_finding" '
        '"Strix gate recognizes contradictory no-finding pseudo-records"\n'
    )
    text = replace_once(text, marker, replacement, "required smoke evidence contract")
    path.write_text(text, encoding="utf-8")


def patch_full_shell_contract() -> None:
    """Extend the long-form shell contract with the same runtime invariants."""
    path = ROOT / "scripts" / "ci" / "test_strix_quick_gate.sh"
    text = path.read_text(encoding="utf-8")
    marker = (
        '\tassert_file_contains "$workflow_file" "Materialize central Strix dependency '
        'lock from PR head" "strix workflow validates central same-repo lock-file PRs '
        'against the PR head lock"\n'
    )
    replacement = marker + (
        '\tassert_file_contains "$workflow_file" "--require-hashes --no-deps -r '
        'requirements-strix-ci-hashes.txt" "strix workflow installs the complete hashed '
        'lock without dependency re-resolution"\n'
        '\tassert_file_contains "$workflow_file" "validate_strix_runtime_compatibility.py" '
        '"strix workflow executes exact-pin and crypto consumer smoke checks"\n'
    )
    text = replace_once(text, marker, replacement, "full shell install contract")
    marker = (
        '\tassert_file_contains "$workflow_file" "bash \\\"$TRUSTED_STRIX_GATE\\\"" '
        '"strix workflow executes trusted temp gate script"\n'
    )
    replacement = marker + (
        '\tassert_file_not_contains "$workflow_file" "Treating as a neutral skip" '
        '"strix workflow keeps incomplete provider scans fail-closed"\n'
        '\tassert_file_contains "$GATE_SCRIPT" "import-current-attempt" '
        '"strix gate imports authoritative current-attempt reports"\n'
        '\tassert_file_contains "$GATE_SCRIPT" '
        '"vulnerability_file_is_self_negating_no_finding" '
        '"strix gate semantically excludes contradictory no-finding records"\n'
    )
    text = replace_once(text, marker, replacement, "full shell evidence contract")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    """Apply every bounded production and regression change exactly once."""
    patch_workflow()
    patch_gate()
    patch_nvidia_contract_test()
    patch_required_smoke()
    patch_full_shell_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
