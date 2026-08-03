#!/usr/bin/env python3
"""Harden PR 709's autonomous Naruon loop, then remove bootstrap files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = ROOT / ".github/workflows/naruon-commercial-readiness-development.yml"
HOURLY = ROOT / ".github/workflows/naruon-commercial-readiness-hourly.yml"
CONTRACT = ROOT / "tests/test_naruon_commercial_readiness_hourly_contract.py"
OLD_BOOTSTRAP = ROOT / ".github/workflows/pr709-least-privilege-repair.yml"
NEW_BOOTSTRAP = ROOT / ".github/workflows/pr709-commercial-readiness-hardening-v2.yml"
SELF = ROOT / "scripts/ci/bootstrap_naruon_commercial_readiness_hardening_v2.py"


def replace_once_or_accept(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    """Replace one exact fragment, or accept an already-applied replacement."""
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old fragment, found {count}")
    return text.replace(old, new, 1)


def remove_once_or_accept(text: str, fragment: str, label: str) -> str:
    """Remove at most one exact fragment and reject duplicate unsafe state."""
    count = text.count(fragment)
    if count > 1:
        raise RuntimeError(f"{label}: expected at most one fragment, found {count}")
    return text.replace(fragment, "", 1) if count else text


def append_test_once(text: str, marker: str, test_source: str) -> str:
    """Append one test block only when its function marker is absent."""
    if marker in text:
        return text
    return text.rstrip() + "\n\n" + test_source.strip() + "\n"


def patch_development(text: str) -> str:
    """Apply least-privilege, lifecycle, and bounded-content invariants."""
    text = replace_once_or_accept(
        text,
        """    permissions:
      actions: write
      contents: write
      id-token: write
""",
        """    permissions:
      actions: write
      contents: read
      id-token: write
      models: read
""",
        "development job permissions",
    )
    text = replace_once_or_accept(
        text,
        """      MAX_CHANGED_FILES: 12
      MAX_CHANGED_LINES: 1200
""",
        """      MAX_CHANGED_FILES: 12
      MAX_CHANGED_LINES: 1200
      MAX_CHANGED_BYTES: 2000000
""",
        "change budget",
    )
    text = replace_once_or_accept(
        text,
        """          target_token="$PAT_TOKEN"
          if [ -z "$target_token" ]; then
            target_token="$APP_TOKEN"
          fi
""",
        """          # Prefer the short-lived, repository-scoped App credential.
          # A broad PAT is an explicit availability fallback, never the default.
          target_token="$APP_TOKEN"
          if [ -z "$target_token" ]; then
            target_token="$PAT_TOKEN"
          fi
""",
        "App-first target credential",
    )
    text = replace_once_or_accept(
        text,
        """          autonomous_branch_count=0
          while IFS= read -r autonomous_ref; do
            [ -n "$autonomous_ref" ] || continue
            autonomous_sha="$(git -C "$target_workspace" rev-parse "$autonomous_ref")"
            if ! git -C "$target_workspace" merge-base --is-ancestor \
              "$autonomous_sha" "$BASE_SHA"; then
              autonomous_branch_count=$((autonomous_branch_count + 1))
              echo "Unmerged autonomous branch: ${autonomous_ref#refs/remotes/origin/}"
            fi
          done < <(
            git -C "$target_workspace" for-each-ref \
              --format='%(refname)' \
              'refs/remotes/origin/autonomous/commercial-readiness-*'
          )
""",
        """          autonomous_branch_count=0
          while IFS= read -r autonomous_ref; do
            [ -n "$autonomous_ref" ] || continue
            autonomous_sha="$(git -C "$target_workspace" rev-parse "$autonomous_ref")"
            if git -C "$target_workspace" merge-base --is-ancestor \
              "$autonomous_sha" "$BASE_SHA"; then
              continue
            fi

            autonomous_branch="${autonomous_ref#refs/remotes/origin/}"
            branch_pr_state="$(
              gh pr list \
                --repo "$TARGET_REPOSITORY" \
                --state all \
                --base "$TARGET_BASE_BRANCH" \
                --head "$autonomous_branch" \
                --limit 20 \
                --json state,mergedAt \
                --jq 'if length == 0 then "missing" elif any(.[]; .state == "OPEN") then "open" elif any(.[]; .mergedAt != null) then "merged" else "closed" end'
            )"
            case "$branch_pr_state" in
              merged | closed)
                echo "Ignoring completed autonomous branch: ${autonomous_branch} (${branch_pr_state})."
                ;;
              *)
                autonomous_branch_count=$((autonomous_branch_count + 1))
                echo "Unfinished autonomous branch: ${autonomous_branch} (${branch_pr_state})."
                ;;
            esac
          done < <(
            git -C "$target_workspace" for-each-ref \
              --format='%(refname)' \
              'refs/remotes/origin/autonomous/commercial-readiness-*'
          )
""",
        "squash-safe autonomous branch guard",
    )
    text = remove_once_or_accept(
        text,
        "          GITHUB_TOKEN: ${{ steps.target_credential.outputs.token }}\n",
        "agent write token",
    )
    text = remove_once_or_accept(
        text,
        '          USE_GITHUB_TOKEN: "true"\n',
        "agent GitHub-token mode",
    )
    text = replace_once_or_accept(
        text,
        """          mapfile -t changed_files < <(
            { git diff --name-only; git ls-files --others --exclude-standard; } \
              | sort -u
          )
""",
        """          mapfile -d '' -t changed_files < <(
            { git diff --name-only -z; git ls-files -z --others --exclude-standard; } \
              | sort -zu
          )
""",
        "NUL-delimited changed paths",
    )
    old_validation = """          changed_file_count="${#changed_files[@]}"
          changed_lines="$(
            git diff --numstat \
              | awk '{added += $1; deleted += $2} END {print added + deleted + 0}'
          )"
          if [ "$changed_file_count" -gt "$MAX_CHANGED_FILES" ]; then
            echo "::error::Changed-file count ${changed_file_count} exceeds ${MAX_CHANGED_FILES}."
            exit 1
          fi
          if [ "$changed_lines" -gt "$MAX_CHANGED_LINES" ]; then
            echo "::error::Changed-line count ${changed_lines} exceeds ${MAX_CHANGED_LINES}."
            exit 1
          fi

          printf '%s\\n' "${changed_files[@]}" >"$RUNNER_TEMP/changed-files.txt"
          if grep -Eq \
            '(^\\.github/workflows/|^\\.env|(^|/)(AGENTS|CLAUDE)\\.md$|(^|/)opencode\\.jsonc$|(^|/)agent-prompt\\.md$|\\.(pem|key|p12|pfx)$|(^|/)(package\\.json|pnpm-lock\\.yaml|pyproject\\.toml|uv\\.lock|requirements[^/]*)$)' \
            "$RUNNER_TEMP/changed-files.txt"; then
"""
    new_validation = """          changed_file_count="${#changed_files[@]}"
          for changed_file in "${changed_files[@]}"; do
            if [ -z "$changed_file" ] \
              || [[ "$changed_file" == *$'\\n'* ]] \
              || [[ "$changed_file" == *$'\\r'* ]] \
              || [[ "$changed_file" == *$'\\t'* ]]; then
              echo "::error::Changed path contains unsupported control characters."
              exit 1
            fi
          done
          printf '%s\\n' "${changed_files[@]}" >"$RUNNER_TEMP/changed-files.txt"

          if git diff --numstat \
            | awk '$1 == "-" || $2 == "-" {found=1} END {exit !found}'; then
            echo "::error::Binary changes are outside the bounded autonomous product-edit contract."
            exit 1
          fi
          changed_lines="$(
            git diff --numstat \
              | awk '{added += $1; deleted += $2} END {print added + deleted + 0}'
          )"
          changed_bytes="$(
            python3 - "$RUNNER_TEMP/changed-files.txt" <<'PY'
          from pathlib import Path
          import os
          import sys

          root = Path.cwd().resolve(strict=True)
          total = 0
          for raw_path in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
              if not raw_path:
                  continue
              relative = Path(raw_path)
              if relative.is_absolute() or ".." in relative.parts:
                  raise SystemExit(f"unsafe changed path: {raw_path}")
              candidate = root / relative
              if not os.path.lexists(candidate):
                  continue
              if candidate.is_symlink() or not candidate.is_file():
                  raise SystemExit(f"changed path is not a regular file: {raw_path}")
              candidate.resolve(strict=True).relative_to(root)
              total += candidate.stat().st_size
          print(total)
          PY
          )"
          if [ "$changed_file_count" -gt "$MAX_CHANGED_FILES" ]; then
            echo "::error::Changed-file count ${changed_file_count} exceeds ${MAX_CHANGED_FILES}."
            exit 1
          fi
          if [ "$changed_lines" -gt "$MAX_CHANGED_LINES" ]; then
            echo "::error::Changed-line count ${changed_lines} exceeds ${MAX_CHANGED_LINES}."
            exit 1
          fi
          if [ "$changed_bytes" -gt "$MAX_CHANGED_BYTES" ]; then
            echo "::error::Changed-file bytes ${changed_bytes} exceed ${MAX_CHANGED_BYTES}."
            exit 1
          fi

          if grep -Eq \
            '(^\\.github/|^\\.env|^infra/|^deploy/|^k8s/|^SECURITY\\.md$|^\\.gitmodules$|(^|/)(AGENTS|CLAUDE|CODEOWNERS)\\.md$|(^|/)opencode\\.jsonc$|(^|/)agent-prompt\\.md$|(^|/)(Dockerfile|Containerfile)(\\..*)?$|(^|/)docker-compose.*\\.ya?ml$|^render\\.yaml$|\\.(pem|key|p12|pfx)$|(^|/)(package(-lock)?\\.json|pnpm-lock\\.yaml|yarn\\.lock|bun\\.lockb|pyproject\\.toml|uv\\.lock|requirements[^/]*|Cargo\\.toml|Cargo\\.lock|go\\.mod|go\\.sum|pom\\.xml|build\\.gradle(\\.kts)?)$)' \
            "$RUNNER_TEMP/changed-files.txt"; then
"""
    text = replace_once_or_accept(
        text,
        old_validation,
        new_validation,
        "bounded changed-content validation",
    )
    text = replace_once_or_accept(
        text,
        """            echo "changed_lines=$changed_lines"
            echo "backend_changed=$(grep -Eq '^backend/' "$RUNNER_TEMP/changed-files.txt" && echo true || echo false)"
""",
        """            echo "changed_lines=$changed_lines"
            echo "changed_bytes=$changed_bytes"
            echo "backend_changed=$(grep -Eq '^backend/' "$RUNNER_TEMP/changed-files.txt" && echo true || echo false)"
""",
        "changed byte output",
    )
    text = replace_once_or_accept(
        text,
        """        env:
          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
          PR_NUMBER: ${{ steps.publish.outputs.pr_number }}
""",
        """        env:
          # This is a same-repository Actions dispatch; keep broad cross-repo
          # credentials confined to target repository read/write steps.
          GH_TOKEN: ${{ github.token }}
          PR_NUMBER: ${{ steps.publish.outputs.pr_number }}
""",
        "same-repository dispatch credential",
    )
    text = replace_once_or_accept(
        text,
        "uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v6",
        "uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0",
        "checkout version comment",
    )
    text = replace_once_or_accept(
        text,
        """            curl -fsS \
              -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
""",
        """            curl -fsS \
              --connect-timeout 5 \
              --max-time 20 \
              -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
""",
        "OIDC request timeout",
    )
    text = replace_once_or_accept(
        text,
        """            curl -fsS \
              -X POST \
              -H "Authorization: Bearer ${oidc_token}" \
""",
        """            curl -fsS \
              --connect-timeout 5 \
              --max-time 20 \
              -X POST \
              -H "Authorization: Bearer ${oidc_token}" \
""",
        "App token exchange timeout",
    )
    text = replace_once_or_accept(
        text,
        """          curl -fsSL \
            -o "$archive" \
""",
        """          curl -fsSL \
            --connect-timeout 5 \
            --max-time 120 \
            --retry 3 \
            --retry-all-errors \
            -o "$archive" \
""",
        "OpenCode download retry budget",
    )
    return text


def patch_hourly(text: str) -> str:
    """Confine cross-repository credentials and remove unnecessary write scope."""
    text = replace_once_or_accept(
        text,
        """    permissions:
      actions: write
      contents: write
      pull-requests: read
""",
        """    permissions:
      actions: write
      contents: read
""",
        "hourly job permissions",
    )
    text = remove_once_or_accept(
        text,
        "      GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}\n",
        "hourly job-wide credential",
    )
    text = replace_once_or_accept(
        text,
        """      - name: Read live pull request queue
        id: queue
        run: |
""",
        """      - name: Read live pull request queue
        id: queue
        env:
          # Cross-repository queue inspection is the only step that receives
          # the target-repository credential in this orchestrator.
          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
        run: |
""",
        "queue-read credential scope",
    )
    for step_name in (
        "Dispatch review feedback fixes",
        "Dispatch current-head review and merge processing",
        "Decide whether product development may run",
        "Dispatch one buyer-visible product gap",
    ):
        text = replace_once_or_accept(
            text,
            f"""      - name: {step_name}
        run: |
""",
            f"""      - name: {step_name}
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
""",
            f"{step_name} workflow-token scope",
        )
    return text


def patch_contract(text: str) -> str:
    """Pin the new least-privilege and bounded-content guarantees in tests."""
    text = replace_once_or_accept(
        text,
        '    assert "^\\\\.github/workflows/" in workflow\n',
        '    assert "^\\\\.github/" in workflow\n',
        "expanded control-plane assertion",
    )
    text = append_test_once(
        text,
        "def test_development_worker_handles_squash_merged_agent_branches()",
        r'''
def test_development_worker_handles_squash_merged_agent_branches() -> None:
    """Completed squash/rebase branches never deadlock later development cycles."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "gh pr list" in workflow
    assert "--state all" in workflow
    assert 'merged | closed)' in workflow
    assert "Ignoring completed autonomous branch:" in workflow
    assert "Unfinished autonomous branch:" in workflow
''',
    )
    text = append_test_once(
        text,
        "def test_development_worker_enforces_content_and_path_budgets()",
        r'''
def test_development_worker_enforces_content_and_path_budgets() -> None:
    """Binary, oversized, irregular, and control-plane edits fail closed."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "MAX_CHANGED_BYTES: 2000000" in workflow
    assert "git diff --name-only -z" in workflow
    assert "git ls-files -z --others" in workflow
    assert "Binary changes are outside" in workflow
    assert "changed path is not a regular file" in workflow
    assert "^infra/" in workflow
    assert "^deploy/" in workflow
    assert "^k8s/" in workflow
    assert "changed_bytes=$changed_bytes" in workflow
''',
    )
    text = append_test_once(
        text,
        "def test_agent_has_no_repository_write_credential()",
        r'''
def test_agent_has_no_repository_write_credential() -> None:
    """Untrusted-context-driven model execution receives inference access only."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")
    agent_step = workflow.split(
        "- name: Run one commercial-readiness implementation slice", 1
    )[1].split("- name: Validate bounded changed-file", 1)[0]

    assert "GITHUB_TOKEN:" not in agent_step
    assert "USE_GITHUB_TOKEN:" not in agent_step
    assert "STRIX_GITHUB_MODELS_TOKEN:" in agent_step
    assert "contents: write" not in workflow.split("steps:", 1)[0]
    assert "models: read" in workflow
''',
    )
    text = append_test_once(
        text,
        "def test_scoped_app_token_precedes_pat_fallback()",
        r'''
def test_scoped_app_token_precedes_pat_fallback() -> None:
    """Target publication prefers the short-lived repository-scoped App token."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")
    credential_step = workflow.split("- name: Resolve target credential", 1)[1].split(
        "- name: Revalidate empty queue", 1
    )[0]

    assert credential_step.index('target_token="$APP_TOKEN"') < credential_step.index(
        'target_token="$PAT_TOKEN"'
    )
''',
    )
    text = append_test_once(
        text,
        "def test_same_repo_dispatches_do_not_use_cross_repo_pat()",
        r'''
def test_same_repo_dispatches_do_not_use_cross_repo_pat() -> None:
    """Same-repository dispatches use github.token; broad tokens stay read-scoped."""
    development = workflow_text("naruon-commercial-readiness-development.yml")
    hourly = workflow_text("naruon-commercial-readiness-hourly.yml")
    development_dispatch = development.split(
        "- name: Dispatch immediate current-head review and merge processing", 1
    )[1].split("- name: Summarize development cycle", 1)[0]
    queue_step = hourly.split("- name: Read live pull request queue", 1)[1].split(
        "- name: Dispatch review feedback fixes", 1
    )[0]
    remaining_hourly = hourly.split("- name: Dispatch review feedback fixes", 1)[1]

    assert "GH_TOKEN: ${{ github.token }}" in development_dispatch
    assert "PR_REVIEW_MERGE_TOKEN" in queue_step
    assert "PR_REVIEW_MERGE_TOKEN" not in remaining_hourly
    assert "contents: write" not in hourly
''',
    )
    return text


def main() -> None:
    """Patch both workflows and tests atomically, then remove bootstrap artifacts."""
    development = patch_development(DEVELOPMENT.read_text(encoding="utf-8"))
    hourly = patch_hourly(HOURLY.read_text(encoding="utf-8"))
    contract = patch_contract(CONTRACT.read_text(encoding="utf-8"))
    DEVELOPMENT.write_text(development, encoding="utf-8")
    HOURLY.write_text(hourly, encoding="utf-8")
    CONTRACT.write_text(contract, encoding="utf-8")
    for path in (OLD_BOOTSTRAP, NEW_BOOTSTRAP, SELF):
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
