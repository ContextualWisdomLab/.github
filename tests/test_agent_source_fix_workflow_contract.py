from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-source-fix.yml"


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_command_and_identity_contract() -> None:
    value = text()
    assert "types: [agent-source-fix]" in value
    assert "@cwl-source-fix" in value
    assert "@opencode-agent" in value and "(?:fix|repair)" in value
    assert "source comment does not belong to the claimed pull request" in value
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert association in value
    for field in ("pr_base_ref", "pr_base_sha", "pr_head_ref", "pr_head_sha", "source_comment_id", "requested_by", "invocation_key"):
        assert field in value
    assert '"command": "source-fix"' in value
    assert "hmac.compare_digest" in value
    assert "cwl-source-fix-invocation-" in value


def test_mutation_boundary() -> None:
    value = text()
    assert '[ "$TARGET_REPOSITORY" = "ContextualWisdomLab/.github" ]' in value
    assert "source-fix supports only same-repository PR heads" in value
    assert 'path.startswith(".github/")' in value
    assert 'path.startswith("scripts/ci/")' in value
    assert "source-fix has no existing PR-authored path available for a bounded edit" in value
    assert "Do not create new paths" in value


def test_authenticated_pr_file_scope() -> None:
    value = text()
    assert 'pulls/${PR_NUMBER}/files' in value
    assert "--paginate --slurp" in value
    assert 'expected = pr.get("changed_files")' in value
    assert "expected > 3000" in value and "len(files) != expected" in value
    assert "complete GitHub PR-files receipt" in value


def test_canonical_model_and_denied_tools() -> None:
    value = text()
    assert value.count("contextual-orchestrator/orchestrator/free") >= 4
    assert '"enabled_providers":["contextual-orchestrator"]' in value
    for capability in ('"bash":"deny"', '"webfetch":"deny"', '"websearch":"deny"', '"task":"deny"', '"external_directory":"deny"'):
        assert capability in value
    assert "contextual_orchestrator_review_sidecar.sh" in value


def test_workspace_restore_scope_check_and_non_force_push() -> None:
    value = text()
    snapshot = value.index('pr_review_conflict_scope.py" snapshot')
    temp_config = value.index('cat >"$TARGET_WORKSPACE/opencode.jsonc"')
    run_model = value.index("opencode run")
    restore = value.index("restore;", run_model)
    verify = value.index('pr_review_conflict_scope.py" verify', restore)
    recheck = value.index("PR head moved during source fix; refusing to push")
    push = value.index("core.hooksPath=/dev/null push")
    assert snapshot < temp_config < run_model < restore < verify < recheck < push
    assert "git diff --check" in value
    assert "python3 -m py_compile" in value
    assert "git rebase" not in value
    assert "push --force" not in value
    assert "push -f" not in value


def test_pinned_actions_and_bounded_fair_sweep() -> None:
    value = text()
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in value
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in value
    assert 'cron: "2-57/5 * * * *"' in value
    assert "rotation_offset=int(now.timestamp() // 300)" in value
    assert "deadline = time.monotonic() + 480" in value
    assert "MAX_DISPATCHES" in value
