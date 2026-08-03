#!/usr/bin/env python3
"""Apply focused review fixes to PR 608, then remove bootstrap files."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/ci/strix_quick_gate.sh"
TEST_GATE = ROOT / "scripts/ci/test_strix_quick_gate.sh"
SELF = ROOT / "scripts/ci/bootstrap_pr608_fixes.py"
SELF_WORKFLOW = ROOT / ".github/workflows/bootstrap-pr608-fixes.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and reject stale or ambiguous input."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    """Replace one regular-expression block and reject stale input."""
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return updated


def patch_gate(text: str) -> str:
    """Keep migration enumeration fail-open and recognize both GitHub API bases."""
    migration_replacement = '''\tif [ "${#sql_migration_dirs[@]}" -gt 0 ]; then
\t\tlocal head_sha_for_migration_context migration_context_dir
\t\tlocal sibling_migration normalized_sibling_migration
\t\thead_sha_for_migration_context="$(trim_whitespace "${PR_HEAD_SHA:-}")"
\t\tif [ -n "$head_sha_for_migration_context" ] &&
\t\t\tis_valid_git_commit_sha "$head_sha_for_migration_context" &&
\t\t\tgit rev-parse --verify --quiet "$head_sha_for_migration_context^{commit}" >/dev/null; then
\t\t\tfor migration_context_dir in "${sql_migration_dirs[@]}"; do
\t\t\t\twhile IFS= read -r sibling_migration; do
\t\t\t\t\tcase "$sibling_migration" in
\t\t\t\t\t*.sql) ;;
\t\t\t\t\t*) continue ;;
\t\t\t\t\tesac
\t\t\t\t\tnormalized_sibling_migration="$(
\t\t\t\t\t\tnormalize_changed_file_path "$sibling_migration" 2>/dev/null
\t\t\t\t\t)" || continue
\t\t\t\t\tprintf '%s\\n' "$normalized_sibling_migration"
\t\t\t\tdone < <(
\t\t\t\t\tgit -c core.quotepath=false ls-tree -r --name-only \\
\t\t\t\t\t\t"$head_sha_for_migration_context" -- "$migration_context_dir/" 2>/dev/null || true
\t\t\t\t)
\t\t\tdone
\t\tfi
\tfi'''
    text = regex_once(
        text,
        r'\tif \[ "\$\{#sql_migration_dirs\[@\]\}" -gt 0 \]; then\n.*?\n\tfi\n\}',
        migration_replacement + "\n}",
        "migration enumeration",
    )

    github_models_replacement = '''github_models_api_base_is_active() {
\tlocal api_base_file_label api_base_file
\tlocal resolved_llm_api_base_file llm_api_base_value

\tfor api_base_file_label in LLM_API_BASE_FILE STRIX_GITHUB_MODELS_API_BASE_FILE; do
\t\tcase "$api_base_file_label" in
\t\tLLM_API_BASE_FILE)
\t\t\tapi_base_file="${LLM_API_BASE_FILE:-}"
\t\t\t;;
\t\tSTRIX_GITHUB_MODELS_API_BASE_FILE)
\t\t\tapi_base_file="${STRIX_GITHUB_MODELS_API_BASE_FILE:-}"
\t\t\t;;
\t\tesac
\t\t[ -n "$api_base_file" ] || continue
\t\tif ! resolved_llm_api_base_file="$(
\t\t\tresolve_trusted_input_file "$api_base_file_label" "$api_base_file" 2>/dev/null
\t\t)"; then
\t\t\tcontinue
\t\tfi
\t\tllm_api_base_value="$(cat -- "$resolved_llm_api_base_file" 2>/dev/null)" || continue
\t\tllm_api_base_value="${llm_api_base_value%%/generateContent*}"
\t\tllm_api_base_value="${llm_api_base_value%%:generateContent*}"
\t\tllm_api_base_value="$(trim_whitespace "$llm_api_base_value")"
\t\tif is_github_models_api_base "$llm_api_base_value"; then
\t\t\treturn 0
\t\tfi
\tdone
\treturn 1
}'''
    text = regex_once(
        text,
        r'github_models_api_base_is_active\(\) \{.*?\n\}\n\nstrix_log_has_github_models_context\(\)',
        github_models_replacement + "\n\nstrix_log_has_github_models_context()",
        "GitHub Models endpoint detection",
    )
    return text


def patch_test(text: str) -> str:
    """Keep the migration fixture's revision scoped to its helper function."""
    return replace_once(
        text,
        '\t\tgit commit -qm base\n\t\thead_sha="$(git rev-parse HEAD)"\n',
        '\t\tgit commit -qm base\n\t\tlocal head_sha\n\t\thead_sha="$(git rev-parse HEAD)"\n',
        "fixture head SHA locality",
    )


def main() -> None:
    """Patch both files only after all expected fragments are proven."""
    gate = patch_gate(GATE.read_text(encoding="utf-8"))
    test_gate = patch_test(TEST_GATE.read_text(encoding="utf-8"))
    GATE.write_text(gate, encoding="utf-8")
    TEST_GATE.write_text(test_gate, encoding="utf-8")
    SELF.unlink()
    SELF_WORKFLOW.unlink()


if __name__ == "__main__":
    main()
