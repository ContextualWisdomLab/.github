#!/usr/bin/env python3
"""Finalize PR 709's retained least-privilege automation files."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOURLY = ROOT / ".github/workflows/naruon-commercial-readiness-hourly.yml"
DEVELOPMENT = ROOT / ".github/workflows/naruon-commercial-readiness-development.yml"
CONTRACT = ROOT / "tests/test_naruon_commercial_readiness_hourly_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact block or accept an already-materialized replacement."""
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source block, found {count}")
    return text.replace(old, new, 1)


def remove_once(text: str, value: str, label: str) -> str:
    """Remove one exact block while remaining idempotent."""
    if value not in text:
        return text
    count = text.count(value)
    if count != 1:
        raise RuntimeError(f"{label}: expected one removable block, found {count}")
    return text.replace(value, "", 1)


def finalize_hourly() -> None:
    """Apply bounded runtime and step-scoped credentials to the hourly loop."""
    text = HOURLY.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "  orchestrate:\n    runs-on: ubuntu-latest\n    permissions:\n",
        "  orchestrate:\n    runs-on: ubuntu-latest\n    timeout-minutes: 15\n    permissions:\n",
        "hourly timeout",
    )
    text = replace_once(
        text,
        "      actions: write\n      contents: write\n      pull-requests: read\n",
        "      actions: write\n      contents: read\n      pull-requests: read\n",
        "hourly permissions",
    )
    text = remove_once(
        text,
        "      GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}\n",
        "hourly job credential",
    )
    text = replace_once(
        text,
        "      - name: Read live pull request queue\n        id: queue\n        run: |\n",
        "      - name: Read live pull request queue\n        id: queue\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: |\n",
        "queue read token",
    )
    text = replace_once(
        text,
        "      - name: Dispatch review feedback fixes\n        run: |\n",
        "      - name: Dispatch review feedback fixes\n        env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || '' }}\n        run: |\n",
        "fix dispatch token",
    )
    text = replace_once(
        text,
        "      - name: Dispatch current-head review and merge processing\n        run: |\n",
        "      - name: Dispatch current-head review and merge processing\n        env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || '' }}\n        run: |\n",
        "merge dispatch token",
    )
    text = replace_once(
        text,
        "        env:\n          OPEN_PR_COUNT: ${{ steps.queue.outputs.count }}\n        run: |\n",
        "        env:\n          GH_TOKEN: ${{ github.token }}\n          OPEN_PR_COUNT: ${{ steps.queue.outputs.count }}\n        run: |\n",
        "development decision token",
    )
    text = replace_once(
        text,
        "      - name: Dispatch one buyer-visible product gap\n        if: steps.development.outputs.decision == 'dispatch'\n        run: |\n",
        "      - name: Dispatch one buyer-visible product gap\n        if: steps.development.outputs.decision == 'dispatch'\n        env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || '' }}\n        run: |\n",
        "development dispatch token",
    )
    for marker in (
        "fix-payload.json",
        "merge-payload.json",
        "development-payload.json",
    ):
        old = f'          set -euo pipefail\n          cat >"$RUNNER_TEMP/{marker}"'
        new = (
            '          set -euo pipefail\n'
            '          if [ -z "${GH_TOKEN:-}" ]; then\n'
            '            echo "::error::No central dispatch credential is available."\n'
            '            exit 1\n'
            '          fi\n'
            f'          cat >"$RUNNER_TEMP/{marker}"'
        )
        text = replace_once(text, old, new, f"{marker} credential gate")
    HOURLY.write_text(text, encoding="utf-8")


def finalize_development() -> None:
    """Remove agent credentials and enforce a staged bounded-change policy."""
    text = DEVELOPMENT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    permissions:\n      actions: write\n      contents: write\n      id-token: write\n",
        "    permissions:\n      contents: read\n      id-token: write\n",
        "development permissions",
    )
    text = replace_once(
        text,
        '          target_token="$PAT_TOKEN"\n          if [ -z "$target_token" ]; then\n            target_token="$APP_TOKEN"\n          fi\n',
        '          target_token="$APP_TOKEN"\n          if [ -z "$target_token" ]; then\n            target_token="$PAT_TOKEN"\n          fi\n',
        "App token priority",
    )
    text = remove_once(
        text,
        "          GITHUB_TOKEN: ${{ steps.target_credential.outputs.token }}\n",
        "agent target credential",
    )
    text = remove_once(
        text,
        '          USE_GITHUB_TOKEN: "true"\n',
        "agent GitHub integration flag",
    )
    old_guard = '''          git add -N -- .
          mapfile -t changed_files < <(
            { git diff --name-only; git ls-files --others --exclude-standard; } \
              | sort -u
          )
          if [ "${#changed_files[@]}" -eq 0 ]; then
            echo "has_changes=false" >>"$GITHUB_OUTPUT"
            echo "Agent produced no safe repository change."
            exit 0
          fi
          echo "has_changes=true" >>"$GITHUB_OUTPUT"

          changed_file_count="${#changed_files[@]}"
          changed_lines="$(
            git diff --numstat \
              | awk '{added += $1; deleted += $2} END {print added + deleted + 0}'
          )"
'''
    new_guard = '''          git add -A -N
          git add -A
          mapfile -t changed_files < <(
            git diff --cached --name-only | sort -u
          )
          if [ "${#changed_files[@]}" -eq 0 ]; then
            echo "has_changes=false" >>"$GITHUB_OUTPUT"
            echo "Agent produced no safe repository change."
            exit 0
          fi
          echo "has_changes=true" >>"$GITHUB_OUTPUT"

          if git diff --cached --numstat \
            | awk '$1 == "-" || $2 == "-" {found=1} END {exit !found}'; then
            echo "::error::Binary changes are outside the bounded autonomous product-edit contract."
            exit 1
          fi
          changed_file_count="${#changed_files[@]}"
          new_file_count="$(
            git diff --cached --name-only --diff-filter=A \
              | awk 'NF {count += 1} END {print count + 0}'
          )"
          changed_lines="$(
            git diff --cached --numstat \
              | awk '{added += $1; deleted += $2} END {print added + deleted + 0}'
          )"
'''
    text = replace_once(text, old_guard, new_guard, "bounded change accounting")
    old_regex = '''          if grep -Eq \
            '(^\\.github/workflows/|^\\.env|(^|/)(AGENTS|CLAUDE)\\.md$|(^|/)opencode\\.jsonc$|(^|/)agent-prompt\\.md$|\\.(pem|key|p12|pfx)$|(^|/)(package\\.json|pnpm-lock\\.yaml|pyproject\\.toml|uv\\.lock|requirements[^/]*)$)' \
            "$RUNNER_TEMP/changed-files.txt"; then
'''
    new_regex = '''          if grep -Eq \
            '(^\\.github/|^\\.env|^infra/|^deploy/|^k8s/|^SECURITY\\.md$|^\\.gitmodules$|(^|/)CODEOWNERS$|(^|/)(AGENTS|CLAUDE)\\.md$|(^|/)opencode\\.jsonc$|(^|/)agent-prompt\\.md$|(^|/)(Dockerfile|Containerfile)(\\..*)?$|(^|/)docker-compose.*\\.ya?ml$|^render\\.yaml$|\\.(pem|key|p12|pfx)$|(^|/)(package(-lock)?\\.json|pnpm-lock\\.yaml|yarn\\.lock|bun\\.lockb|pyproject\\.toml|uv\\.lock|requirements[^/]*|Cargo\\.toml|Cargo\\.lock|go\\.mod|go\\.sum|pom\\.xml|build\\.gradle(\\.kts)?)$)' \
            "$RUNNER_TEMP/changed-files.txt"; then
'''
    text = replace_once(text, old_regex, new_regex, "control-plane exclusion")
    text = replace_once(
        text,
        "          if git diff --unified=0 | grep -Eqi \\\n",
        "          if git diff --cached --unified=0 | grep -Eqi \\\n",
        "cached secret scan",
    )
    text = replace_once(
        text,
        "          git diff --check\n",
        "          git diff --cached --check\n",
        "cached diff check",
    )
    text = replace_once(
        text,
        '            echo "changed_file_count=$changed_file_count"\n            echo "changed_lines=$changed_lines"\n',
        '            echo "changed_file_count=$changed_file_count"\n            echo "new_file_count=$new_file_count"\n            echo "changed_lines=$changed_lines"\n',
        "new-file evidence",
    )
    text = replace_once(
        text,
        "          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}\n          PR_NUMBER:",
        "          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || '' }}\n          PR_NUMBER:",
        "trusted central dispatch token",
    )
    text = replace_once(
        text,
        "          set -euo pipefail\n          jq -n \\\n",
        "          set -euo pipefail\n          if [ -z \"${GH_TOKEN:-}\" ]; then\n            echo \"::error::No central review-dispatch credential is available.\"\n            exit 1\n          fi\n          jq -n \\\n",
        "central dispatch credential gate",
    )
    DEVELOPMENT.write_text(text, encoding="utf-8")


def finalize_contract() -> None:
    """Update static assertions to the exact retained workflow syntax."""
    text = CONTRACT.read_text(encoding="utf-8")
    replacements = {
        "assert 'review_dispatch_limit: \"-1\"' in workflow": (
            "assert '\"review_dispatch_limit\": \"-1\"' in workflow"
        ),
        "assert 'stale_opencode_minutes: \"60\"' in workflow": (
            "assert '\"stale_opencode_minutes\": \"60\"' in workflow"
        ),
        "assert 'merge_mode: \"direct_or_auto\"' in workflow": (
            "assert '\"merge_mode\": \"direct_or_auto\"' in workflow"
        ),
        'assert "^\\\\.github/workflows/" in workflow': (
            'assert "^\\\\.github/" in workflow'
        ),
        'assert "git diff --check" in workflow': (
            'assert "git diff --cached --check" in workflow'
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    append = '''


def test_hourly_loop_has_bounded_runtime_and_step_scoped_credentials() -> None:
    """The hourly queue loop must be bounded and expose no job-wide write token."""
    workflow = workflow_text("naruon-commercial-readiness-hourly.yml")

    assert "timeout-minutes: 15" in workflow
    assert "actions: write" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "No central dispatch credential is available" in workflow


def test_development_agent_has_no_target_write_credential() -> None:
    """Untrusted implementation receives neither a target token nor GitHub tools."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")
    agent_block = workflow.split(
        "- name: Run one commercial-readiness implementation slice", 1
    )[1].split("- name: Validate bounded changed-file", 1)[0]

    assert "GITHUB_TOKEN:" not in agent_block
    assert "USE_GITHUB_TOKEN:" not in agent_block
    assert 'target_token="$APP_TOKEN"' in workflow
    assert 'target_token="$PAT_TOKEN"' in workflow


def test_development_guard_stages_untracked_and_rejects_binary_control_plane_edits() -> None:
    """The bounded guard must account for untracked, binary, and control files."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "git add -A -N" in workflow
    assert "git diff --cached --numstat" in workflow
    assert 'new_file_count="$(' in workflow
    assert "Binary changes are outside" in workflow
    assert "(^|/)CODEOWNERS$" in workflow
    assert "(^|/)(AGENTS|CLAUDE)\\\\.md$" in workflow
'''
    if "test_hourly_loop_has_bounded_runtime_and_step_scoped_credentials" not in text:
        text += append
    CONTRACT.write_text(text, encoding="utf-8")


def remove_temporary_artifacts() -> None:
    """Delete every one-shot helper so only retained runtime assets remain."""
    for relative in (
        ".github/workflows/pr709-commercial-readiness-hardening-v2.yml",
        ".github/workflows/pr709-least-privilege-repair.yml",
        ".github/workflows/pr709-finalize-commercial-readiness.yml",
        "scripts/ci/bootstrap_naruon_commercial_readiness_hardening_v2.py",
        "scripts/ci/pr709_finalize.py",
    ):
        (ROOT / relative).unlink(missing_ok=True)


def main() -> None:
    """Apply all finalization transformations and remove temporary files."""
    finalize_hourly()
    finalize_development()
    finalize_contract()
    remove_temporary_artifacts()


if __name__ == "__main__":
    main()
