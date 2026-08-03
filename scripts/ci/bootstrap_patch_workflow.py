#!/usr/bin/env python3
"""Wire the trusted npm workspace resolver, then remove this bootstrap."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
CONTRACT = ROOT / "tests/test_opencode_agent_contract.py"
SELF = ROOT / "scripts/ci/bootstrap_patch_workflow.py"
SELF_WORKFLOW = ROOT / ".github/workflows/bootstrap-npm-workspace-wiring.yml"
FOCUSED_WORKFLOW = ROOT / ".github/workflows/pr703-focused-tests.yml"


def replace_once(text: str, old: str, new: str, name: str) -> str:
    """Replace one exact fragment and reject base drift or ambiguity."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, name: str) -> str:
    """Replace one regular-expression block and reject base drift."""
    updated, count = re.subn(
        pattern,
        lambda _match: replacement,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError(f"{name}: expected one match, found {count}")
    return updated


def patch_workflow(text: str) -> str:
    """Patch the central coverage workflow with fail-closed root resolution."""
    resolver_and_trust = r'''          resolve_npm_package_root() {
            local selected_package_dir="$1"
            local candidate_root

            case "$selected_package_dir" in
              "$COVERAGE_SOURCE_WORKDIR" | "$COVERAGE_SOURCE_WORKDIR"/*)
                candidate_root="$selected_package_dir"
                ;;
              .)
                candidate_root="$PWD"
                ;;
              "" | /* | ../* | */../* | */.. | *\\* | *$'\n'* | *$'\r'*)
                echo "::error::Selected npm package directory is not a safe repository-relative path."
                return 1
                ;;
              *)
                candidate_root="$COVERAGE_SOURCE_WORKDIR/$selected_package_dir"
                ;;
            esac
            if [ ! -d "$candidate_root" ] || [ -L "$candidate_root" ]; then
              echo "::error::Selected npm package directory must be a real non-symlink directory."
              return 1
            fi
            candidate_root="$(realpath -e -- "$candidate_root")" || {
              echo "::error::Could not canonicalize the selected npm package directory."
              return 1
            }
            case "$candidate_root" in
              "$COVERAGE_SOURCE_WORKDIR" | "$COVERAGE_SOURCE_WORKDIR"/*) ;;
              *)
                echo "::error::Selected npm package directory escaped the validated coverage worktree."
                return 1
                ;;
            esac
            printf '%s\n' "$candidate_root"
          }

          resolve_npm_install_root() {
            local selected_package_dir="$1"
            local relative_root
            local candidate_root

            if ! relative_root="$(
              python3 -I "$GITHUB_WORKSPACE/scripts/ci/npm_workspace_install_root.py" \
                --repo-root "$COVERAGE_SOURCE_WORKDIR" \
                --package-dir "$selected_package_dir" \
                --base-sha "$PR_BASE_SHA" \
                --head-sha "$PR_HEAD_SHA"
            )"; then
              echo "::error::Could not resolve a validated npm workspace lock owner for ${selected_package_dir}."
              return 1
            fi
            case "$relative_root" in
              .)
                candidate_root="$COVERAGE_SOURCE_WORKDIR"
                ;;
              "" | /* | ../* | */../* | */.. | *\\* | *$'\n'* | *$'\r'*)
                echo "::error::Resolved npm workspace lock owner is not a safe repository-relative path."
                return 1
                ;;
              *)
                candidate_root="$COVERAGE_SOURCE_WORKDIR/$relative_root"
                ;;
            esac
            if [ ! -d "$candidate_root" ] || [ -L "$candidate_root" ]; then
              echo "::error::Resolved npm workspace lock owner must be a real non-symlink directory."
              return 1
            fi
            candidate_root="$(realpath -e -- "$candidate_root")" || {
              echo "::error::Could not canonicalize the resolved npm workspace lock owner."
              return 1
            }
            case "$candidate_root" in
              "$COVERAGE_SOURCE_WORKDIR" | "$COVERAGE_SOURCE_WORKDIR"/*) ;;
              *)
                echo "::error::Resolved npm workspace lock owner escaped the validated coverage worktree."
                return 1
                ;;
            esac
            printf '%s\n' "$candidate_root"
          }

          trusted_npm_lock_is_materialized() {
            local install_root="$1"
            local relative_dir
            local lock_name
            local relative_lock
            local head_blob
            local worktree_blob
            local trust_manifest

            case "$install_root" in
              "$COVERAGE_SOURCE_WORKDIR")
                relative_dir=""
                ;;
              "$COVERAGE_SOURCE_WORKDIR"/*)
                relative_dir="${install_root#"$COVERAGE_SOURCE_WORKDIR"/}"
                ;;
              *)
                echo "::error::npm install root escaped the validated coverage worktree."
                return 1
                ;;
            esac
            if [ ! -d "$install_root" ] || [ -L "$install_root" ]; then
              echo "::error::npm install root must be a real non-symlink directory."
              return 1
            fi
            if [ -f "$install_root/npm-shrinkwrap.json" ] && [ ! -L "$install_root/npm-shrinkwrap.json" ]; then
              lock_name="npm-shrinkwrap.json"
            elif [ -f "$install_root/package-lock.json" ] && [ ! -L "$install_root/package-lock.json" ]; then
              lock_name="package-lock.json"
            else
              echo "::error::Resolved npm lock owner must contain a regular non-symlink package-lock.json or npm-shrinkwrap.json."
              return 1
            fi
            relative_lock="${relative_dir:+${relative_dir}/}${lock_name}"

            head_blob="$(trusted_git rev-parse "${PR_HEAD_SHA}:${relative_lock}" 2>/dev/null)" || {
              echo "::error::Validated head does not contain ${relative_lock}."
              return 1
            }
            worktree_blob="$(
              trusted_git hash-object --path="$relative_lock" -- "$install_root/$lock_name"
            )" || {
              echo "::error::Could not hash current npm lock ${relative_lock}."
              return 1
            }
            if [ "$head_blob" != "$worktree_blob" ]; then
              echo "::error::Current npm lock ${relative_lock} does not match the live-validated HEAD blob."
              return 1
            fi

            trust_manifest="/opt/javascript-package-locks/manifest.json"
            if [ ! -f "$trust_manifest" ] || [ -L "$trust_manifest" ]; then
              echo "::error::Trusted JavaScript package lock manifest must be a regular non-symlink file."
              return 1
            fi
            if ! jq -e \
              --arg source "$relative_lock" \
              --arg package_manager "npm" \
              --arg base_sha "${PR_BASE_SHA,,}" \
              --arg head_sha "${PR_HEAD_SHA,,}" \
              --arg lock_blob "${head_blob,,}" \
              'any(.[];
                .source == $source
                and .package_manager == $package_manager
                and .lock_blob == $lock_blob
                and (.revision_sha == $base_sha or .revision_sha == $head_sha)
              )' "$trust_manifest" >/dev/null; then
              echo "::error::Current npm lock ${relative_lock} lacks an exact validated base-or-HEAD materialization receipt."
              return 1
            fi
          }'''
    text = regex_once(
        text,
        r"          trusted_npm_lock_is_materialized\(\) \{.*?\n          \}\n\n          prepare_writable_npm_cache\(\)",
        resolver_and_trust + "\n\n          prepare_writable_npm_cache()",
        "npm trust block",
    )

    npm_case = r'''          install_package_dependencies() {
            local package_runner="$1"
            local selected_package_dir="${2:-$PWD}"
            case "$package_runner" in
              npm)
                local selected_package_root
                local npm_install_root
                local npm_workspace_selector=""
                local npm_workspace_args=()

                if ! selected_package_root="$(resolve_npm_package_root "$selected_package_dir")" ||
                  ! npm_install_root="$(resolve_npm_install_root "$selected_package_root")"; then
                  append "### JavaScript/TypeScript dependencies (npm)"
                  append ""
                  append "- Result: FAIL"
                  append "- Reason: no validated local or ancestor npm workspace lock owns the selected package."
                  append ""
                  failures=$((failures + 1))
                  return 0
                fi
                if ! trusted_npm_lock_is_materialized "$npm_install_root" || ! prepare_writable_npm_cache; then
                  append "### JavaScript/TypeScript dependencies (npm)"
                  append ""
                  append "- Result: FAIL"
                  append "- Reason: the resolved npm lock lacks an exact validated base-or-HEAD receipt, or the trusted npm cache is unavailable."
                  append ""
                  failures=$((failures + 1))
                  return 0
                fi

                case "$selected_package_root" in
                  "$npm_install_root")
                    ;;
                  "$npm_install_root"/*)
                    npm_workspace_selector="${selected_package_root#"$npm_install_root"/}"
                    case "$npm_workspace_selector" in
                      "" | /* | ../* | */../* | */.. | *\\* | *$'\n'* | *$'\r'*)
                        append "### JavaScript/TypeScript dependencies (npm)"
                        append ""
                        append "- Result: FAIL"
                        append "- Reason: the selected npm workspace path is not a safe lock-root-relative selector."
                        append ""
                        failures=$((failures + 1))
                        return 0
                        ;;
                    esac
                    npm_workspace_args=(--workspace "$npm_workspace_selector")
                    ;;
                  *)
                    append "### JavaScript/TypeScript dependencies (npm)"
                    append ""
                    append "- Result: FAIL"
                    append "- Reason: the selected npm package is outside its validated lock owner."
                    append ""
                    failures=$((failures + 1))
                    return 0
                    ;;
                esac

                run_and_capture "JavaScript/TypeScript dependencies (npm workspace-root offline ci, lifecycle hooks disabled)" \
                  bash -c 'cd "$1" && cache="$2" && shift 2 && npm ci --offline --ignore-scripts --cache "$cache" --no-audit --no-fund "$@"' \
                  bash "$npm_install_root" "$writable_npm_cache_dir" "${npm_workspace_args[@]}"
                ;;
              pnpm)'''
    text = regex_once(
        text,
        r"          install_package_dependencies\(\) \{\n.*?\n              pnpm\)",
        npm_case,
        "npm install case",
    )
    text = replace_once(
        text,
        '            install_package_dependencies "$package_runner"\n'
        '            package_name="$(jq -r \'.name // empty\' "${package_dir}/package.json")"',
        '            install_package_dependencies "$package_runner" "$package_dir"\n'
        '            package_name="$(jq -r \'.name // empty\' "${package_dir}/package.json")"',
        "Tauri package install root",
    )
    text = replace_once(
        text,
        "              ContextualWisdomLab/.github:scripts/ci/materialize_base_javascript_packages.py | \\\n",
        "              ContextualWisdomLab/.github:scripts/ci/materialize_base_javascript_packages.py | \\\n"
        "              ContextualWisdomLab/.github:scripts/ci/npm_workspace_install_root.py | \\\n",
        "resolver fallback allowlist",
    )
    text = replace_once(
        text,
        "              ContextualWisdomLab/.github:tests/test_materialize_base_javascript_packages.py | \\\n",
        "              ContextualWisdomLab/.github:tests/test_materialize_base_javascript_packages.py | \\\n"
        "              ContextualWisdomLab/.github:tests/test_npm_workspace_install_root.py | \\\n"
        "              ContextualWisdomLab/.github:tests/test_npm_workspace_install_root_hardening.py | \\\n",
        "resolver test fallback allowlist",
    )
    return text


def patch_contract(text: str) -> str:
    """Update exact workflow contract assertions for the new npm path."""
    text = replace_once(
        text,
        '    assert "trusted_npm_lock_is_materialized()" in measure_step\n',
        '    assert "trusted_npm_lock_is_materialized()" in measure_step\n'
        '    assert "resolve_npm_package_root()" in measure_step\n'
        '    assert "resolve_npm_install_root()" in measure_step\n'
        '    assert \'python3 -I "$GITHUB_WORKSPACE/scripts/ci/npm_workspace_install_root.py"\' in measure_step\n'
        '    assert \'--base-sha "$PR_BASE_SHA"\' in measure_step\n'
        '    assert \'--head-sha "$PR_HEAD_SHA"\' in measure_step\n',
        "resolver assertions",
    )
    text = replace_once(
        text,
        '    assert "npm offline ci" in measure_step\n',
        '    assert "npm workspace-root offline ci" in measure_step\n',
        "npm title assertion",
    )
    text = replace_once(
        text,
        '        "if ! trusted_npm_lock_is_materialized || "\n'
        '        "! prepare_writable_npm_cache; then"\n',
        '        \'if ! trusted_npm_lock_is_materialized "$npm_install_root" || \'\n'
        '        "! prepare_writable_npm_cache; then"\n',
        "npm trust invocation",
    )
    text = replace_once(
        text,
        '        "the current npm lock is not hash-bounded to the validated base or HEAD, "\n',
        '        "the resolved npm lock lacks an exact validated base-or-HEAD receipt, "\n',
        "npm trust diagnostic",
    )
    text = replace_once(
        text,
        '        "offline npm coverage requires a tracked package-lock.json or "\n'
        '        "npm-shrinkwrap.json at the validated base and current head"\n',
        '        "no validated local or ancestor npm workspace lock owns the selected "\n'
        '        "package"\n',
        "resolver failure diagnostic",
    )
    anchor = '    assert "return 1" not in npm_install_case\n'
    addition = anchor + """    assert 'npm_workspace_args=(--workspace "$npm_workspace_selector")' in npm_install_case
    assert 'npm ci --offline --ignore-scripts' in npm_install_case
    assert 'bash "$npm_install_root" "$writable_npm_cache_dir" "${npm_workspace_args[@]}"' in npm_install_case
    assert 'ContextualWisdomLab/.github:scripts/ci/npm_workspace_install_root.py' in workflow
    assert 'ContextualWisdomLab/.github:tests/test_npm_workspace_install_root.py' in workflow
    assert 'ContextualWisdomLab/.github:tests/test_npm_workspace_install_root_hardening.py' in workflow
"""
    text = replace_once(
        text,
        anchor,
        addition,
        "workspace root assertions",
    )
    return text


def main() -> None:
    """Patch both contracts after all expected base fragments are proven."""
    workflow = patch_workflow(WORKFLOW.read_text(encoding="utf-8"))
    contract = patch_contract(CONTRACT.read_text(encoding="utf-8"))
    WORKFLOW.write_text(workflow, encoding="utf-8")
    CONTRACT.write_text(contract, encoding="utf-8")
    SELF.unlink()
    SELF_WORKFLOW.unlink()
    FOCUSED_WORKFLOW.unlink()


if __name__ == "__main__":
    main()
