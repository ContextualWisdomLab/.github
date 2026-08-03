#!/usr/bin/env python3
"""Apply the bounded #608 Strix review fixes, then remove this bootstrap path."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
TEST_PATH = REPO_ROOT / "scripts" / "ci" / "test_strix_quick_gate.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "bootstrap-strix-review-fixes.yml"
SELF_PATH = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact reviewed source fragment and fail on drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source fragment, found {count}")
    return text.replace(old, new, 1)


def patch_gate(text: str) -> str:
    """Harden migration context paths and GitHub Models endpoint detection."""
    old_migrations = '''\tif [ "${#sql_migration_dirs[@]}" -gt 0 ]; then
\t\tlocal head_sha_for_migration_context migration_context_dir
\t\thead_sha_for_migration_context="$(trim_whitespace "${PR_HEAD_SHA:-}")"
\t\tif [ -n "$head_sha_for_migration_context" ] &&
\t\t\tis_valid_git_commit_sha "$head_sha_for_migration_context" &&
\t\t\tgit rev-parse --verify --quiet "$head_sha_for_migration_context^{commit}" >/dev/null; then
\t\t\tfor migration_context_dir in "${sql_migration_dirs[@]}"; do
\t\t\t\tgit -c core.quotepath=false ls-tree -r --name-only "$head_sha_for_migration_context" -- "$migration_context_dir/" 2>/dev/null |
\t\t\t\t\tgrep -E '\\.sql$' || true
\t\t\tdone
\t\tfi
\tfi
'''
    new_migrations = '''\tif [ "${#sql_migration_dirs[@]}" -gt 0 ]; then
\t\tlocal head_sha_for_migration_context migration_context_dir
\t\tlocal migration_context_file normalized_migration_context_file
\t\thead_sha_for_migration_context="$(trim_whitespace "${PR_HEAD_SHA:-}")"
\t\tif [ -n "$head_sha_for_migration_context" ] &&
\t\t\tis_valid_git_commit_sha "$head_sha_for_migration_context" &&
\t\t\tgit rev-parse --verify --quiet "$head_sha_for_migration_context^{commit}" >/dev/null; then
\t\t\tfor migration_context_dir in "${sql_migration_dirs[@]}"; do
\t\t\t\twhile IFS= read -r migration_context_file; do
\t\t\t\t\t[ -n "$migration_context_file" ] || continue
\t\t\t\t\tnormalized_migration_context_file="$(
\t\t\t\t\t\tnormalize_changed_file_path "$migration_context_file"
\t\t\t\t\t)" || continue
\t\t\t\t\tcase "$normalized_migration_context_file" in
\t\t\t\t\t"$migration_context_dir"/*.sql)
\t\t\t\t\t\tprintf '%s\\n' "$normalized_migration_context_file"
\t\t\t\t\t\t;;
\t\t\t\t\tesac
\t\t\t\tdone < <(
\t\t\t\t\tgit -c core.quotepath=false ls-tree -r --name-only \\
\t\t\t\t\t\t"$head_sha_for_migration_context" -- "$migration_context_dir/" \\
\t\t\t\t\t\t2>/dev/null || true
\t\t\t\t)
\t\t\tdone
\t\tfi
\tfi
'''
    text = replace_once(
        text,
        old_migrations,
        new_migrations,
        "migration context normalization",
    )

    old_api_base = '''github_models_api_base_is_active() {
\tlocal api_base_file="${LLM_API_BASE_FILE:-}"
\tlocal api_base_file_label="LLM_API_BASE_FILE"
\t# Cross-provider fallback: when the primary scan uses direct-OpenAI,
\t# LLM_API_BASE_FILE is not set, but github_models/* fallback models
\t# route through the GitHub Models endpoint supplied by
\t# STRIX_GITHUB_MODELS_API_BASE_FILE.  Recognise either source so that
\t# github_models_rate_limit_should_skip_same_model_retry correctly skips
\t# same-model retries for rate-limited cross-provider fallback models.
\tif [ -z "$api_base_file" ] && [ -n "${STRIX_GITHUB_MODELS_API_BASE_FILE:-}" ]; then
\t\tapi_base_file="$STRIX_GITHUB_MODELS_API_BASE_FILE"
\t\tapi_base_file_label="STRIX_GITHUB_MODELS_API_BASE_FILE"
\tfi

\tif [ -z "$api_base_file" ]; then
\t\treturn 1
\tfi

\tlocal resolved_llm_api_base_file
\tif ! resolved_llm_api_base_file="$(resolve_trusted_input_file "$api_base_file_label" "$api_base_file" 2>/dev/null)"; then
\t\treturn 1
\tfi

\tlocal llm_api_base_value
\tllm_api_base_value="$(cat -- "$resolved_llm_api_base_file" 2>/dev/null)" || return 1
\tllm_api_base_value="${llm_api_base_value%%/generateContent*}"
\tllm_api_base_value="${llm_api_base_value%%:generateContent*}"
\tllm_api_base_value="$(trim_whitespace "$llm_api_base_value")"
\tis_github_models_api_base "$llm_api_base_value"
}
'''
    new_api_base = '''github_models_api_base_is_active() {
\tlocal api_base_file_label api_base_file
\tlocal resolved_llm_api_base_file llm_api_base_value

\t# A cross-provider fallback can have both files configured at once: the
\t# primary provider remains in LLM_API_BASE_FILE while GitHub Models uses its
\t# dedicated endpoint file. Inspect the dedicated fallback endpoint first,
\t# then the primary endpoint, so either valid source activates the rate-limit
\t# retry short-circuit without allowing one non-GitHub value to hide the other.
\tfor api_base_file_label in STRIX_GITHUB_MODELS_API_BASE_FILE LLM_API_BASE_FILE; do
\t\tcase "$api_base_file_label" in
\t\tSTRIX_GITHUB_MODELS_API_BASE_FILE)
\t\t\tapi_base_file="${STRIX_GITHUB_MODELS_API_BASE_FILE:-}"
\t\t\t;;
\t\tLLM_API_BASE_FILE)
\t\t\tapi_base_file="${LLM_API_BASE_FILE:-}"
\t\t\t;;
\t\tesac
\t\t[ -n "$api_base_file" ] || continue
\t\tresolved_llm_api_base_file="$(
\t\t\tresolve_trusted_input_file "$api_base_file_label" "$api_base_file" 2>/dev/null
\t\t)" || continue
\t\tllm_api_base_value="$(cat -- "$resolved_llm_api_base_file" 2>/dev/null)" || continue
\t\tllm_api_base_value="${llm_api_base_value%%/generateContent*}"
\t\tllm_api_base_value="${llm_api_base_value%%:generateContent*}"
\t\tllm_api_base_value="$(trim_whitespace "$llm_api_base_value")"
\t\tif is_github_models_api_base "$llm_api_base_value"; then
\t\t\treturn 0
\t\tfi
\tdone
\treturn 1
}
'''
    return replace_once(
        text,
        old_api_base,
        new_api_base,
        "GitHub Models endpoint source selection",
    )


def patch_tests(text: str) -> str:
    """Strengthen the focused regression harness for all three review findings."""
    text = replace_once(
        text,
        '''\tassert_file_contains "$GATE_SCRIPT" "git -c core.quotepath=false ls-tree -r --name-only \\\"\\$head_sha_for_migration_context\\\" -- \\\"\\$migration_context_dir/\\\"" "strix gate enumerates sibling migrations from the PR head without quoting non-ASCII paths"
\tassert_file_contains "$GATE_SCRIPT" "fails open" "strix gate migration context enumeration is documented as fail-open"
''',
        '''\tassert_file_contains "$GATE_SCRIPT" "git -c core.quotepath=false ls-tree -r --name-only \\\"\\$head_sha_for_migration_context\\\" -- \\\"\\$migration_context_dir/\\\"" "strix gate enumerates sibling migrations from the PR head without quoting non-ASCII paths"
\tassert_file_contains "$GATE_SCRIPT" 'normalize_changed_file_path "$migration_context_file"' "strix gate normalizes every sibling migration path before emission"
\tassert_file_contains "$GATE_SCRIPT" "for api_base_file_label in STRIX_GITHUB_MODELS_API_BASE_FILE LLM_API_BASE_FILE" "strix gate evaluates both dedicated fallback and primary GitHub Models endpoints"
\tassert_file_contains "$GATE_SCRIPT" "fails open" "strix gate migration context enumeration is documented as fail-open"
''',
        "static migration and endpoint contracts",
    )
    text = replace_once(
        text,
        '''\tlocal tmp_dir
\ttmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/strix-migration-context.XXXXXX")"
''',
        '''\tlocal tmp_dir head_sha
\ttmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/strix-migration-context.XXXXXX")"
''',
        "local head SHA declaration",
    )
    text = replace_once(
        text,
        '''\t\tprintf 'ALTER TABLE t ADD COLUMN d text;\\n' >"server/db with space/migrations/0003_add_second_col.sql"
\t\tgit add -A
''',
        '''\t\tprintf 'ALTER TABLE t ADD COLUMN d text;\\n' >"server/db with space/migrations/0003_add_second_col.sql"
\t\tprintf 'SELECT 1;\\n' >"server/db with space/migrations/0004_bad;name.sql"
\t\tgit add -A
''',
        "unsafe migration fixture",
    )
    text = replace_once(
        text,
        '''\t\t\t\tnormalize_changed_file_path() { printf "%s" "$1"; }
\t\t\t\t'"$(sed -n "/^pull_request_scope_context_files()/,/^}/p" "$GATE_SCRIPT")"'
''',
        '''\t\t\t\t'"$(sed -n "/^normalize_changed_file_path()/,/^}/p" "$GATE_SCRIPT")"'
\t\t\t\t'"$(sed -n "/^pull_request_scope_context_files()/,/^}/p" "$GATE_SCRIPT")"'
''',
        "functional path normalizer fixture",
    )
    return replace_once(
        text,
        '''\tassert_file_contains "$tmp_dir/out.txt" "server/db with space/migrations/0001_기초.sql" "strix gate preserves spaces and non-ASCII sibling migration paths"
\tlocal sibling_count
''',
        '''\tassert_file_contains "$tmp_dir/out.txt" "server/db with space/migrations/0001_기초.sql" "strix gate preserves spaces and non-ASCII sibling migration paths"
\tassert_file_not_contains "$tmp_dir/out.txt" "0004_bad;name.sql" "strix gate silently skips unsafe sibling migration paths"
\tlocal sibling_count
''',
        "unsafe path regression assertion",
    )


def main() -> int:
    """Patch reviewed fragments and remove the one-shot privileged bootstrap."""
    GATE_PATH.write_text(patch_gate(GATE_PATH.read_text(encoding="utf-8")), encoding="utf-8")
    TEST_PATH.write_text(patch_tests(TEST_PATH.read_text(encoding="utf-8")), encoding="utf-8")
    WORKFLOW_PATH.unlink(missing_ok=True)
    SELF_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
