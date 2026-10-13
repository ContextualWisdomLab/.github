"""공개 exact-head 전달은 quota에 의존하지 않고 private 경로는 보존한다."""
from pathlib import Path
import os
import subprocess

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def _step(job: dict, name: str) -> dict:
    """실제 YAML의 고유한 named step을 반환한다."""
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1, name
    return matches[0]


def test_public_transfer_does_not_require_an_artifact_upload() -> None:
    """Private archive 전달만 artifact quota를 소비한다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    upload = _step(jobs["validate-pr-metadata"], "Upload materialized pull request merge tree")
    assert upload.get("if") == "steps.validate.outputs.is_private == 'true'"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 1
    download = _step(jobs["coverage-evidence"], "Download materialized pull request merge tree")
    assert download.get("if") == "needs.validate-pr-metadata.outputs.is_private == 'true'"
    assert download["with"]["name"] == upload["with"]["name"]


def test_public_source_is_reconstructed_in_the_credential_free_coverage_job() -> None:
    """공개 경로도 검증한 base/head와 격리된 기존 destination에 결속한다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    coverage = jobs["coverage-evidence"]
    public = _step(coverage, "Materialize public pull request merge tree without artifacts")
    assert public.get("if") == "needs.validate-pr-metadata.outputs.is_private == 'false'"
    env = public["env"]
    assert env["TARGET_REPOSITORY"] == "${{ needs.validate-pr-metadata.outputs.target_repository }}"
    assert env["PR_BASE_SHA"] == "${{ needs.validate-pr-metadata.outputs.base_sha }}"
    assert env["PR_HEAD_SHA"] == "${{ needs.validate-pr-metadata.outputs.head_sha }}"
    assert not any("TOKEN" in key or "KEY" in key for key in env)
    assert "${{ secrets." not in str(public)
    assert "materialize_public_review_source.py" in public["run"]
    assert coverage["permissions"] == {"actions": "read"}
    private = _step(coverage, "Prepare pull request merge tree for coverage measurement")
    assert private.get("if") == "needs.validate-pr-metadata.outputs.is_private == 'true'"
    names = [step.get("name") for step in coverage["steps"]]
    assert names.index(public["name"]) < names.index("Enforce post-merge stale agent replay guard")
    assert public["env"]["COVERAGE_SOURCE_WORKDIR"] == private["env"]["COVERAGE_SOURCE_WORKDIR"]


def test_coverage_bootstrap_requires_immutable_source_and_narrow_context() -> None:
    """Helper bootstrap은 moving main fallback이나 전체 token context를 받지 않는다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    coverage = jobs["coverage-evidence"]
    resolve = _step(coverage, "Resolve trusted OpenCode source ref")
    assert "toJSON(github)" not in str(resolve)
    assert resolve["env"]["TRUSTED_WORKFLOW_SHA"] == "${{ github.workflow_sha }}"
    assert 'trusted_ref = "main"' not in resolve["run"]
    assert 're.fullmatch(r"[0-9a-f]{40}"' in resolve["run"]
    bootstrap = _step(coverage, "Materialize trusted OpenCode coverage contract without a repository token")
    assert "GIT_CONFIG_NOSYSTEM" in bootstrap["run"]
    assert "http.followRedirects=false" in bootstrap["run"]
    assert "env=environment" in bootstrap["run"]
    assert 'git("rev-parse", "HEAD")' in bootstrap["run"]


def test_visibility_is_rejected_if_neither_transport_is_admissible() -> None:
    """양 경로가 모두 skip인 metadata 변조를 별도 guard로 거부한다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    gate = _step(jobs["coverage-evidence"], "Require explicit coverage source visibility")
    assert gate["env"]["IS_PRIVATE"] == "${{ needs.validate-pr-metadata.outputs.is_private }}"
    assert "true|false)" in gate["run"]
    assert "exit 1" in gate["run"]
    tokens = [s for s in jobs["validate-pr-metadata"]["steps"] if s.get("id") == "coverage_read_app_token"]
    assert len(tokens) == 1
    assert "steps.validate.outputs.is_private == 'true'" in tokens[0]["if"]
    assert "steps.validate.outputs.target_repository != github.repository" in tokens[0]["if"]


def test_new_transport_is_connected_to_the_existing_quality_suite() -> None:
    """소스와 테스트만 추가하고 실제 CI의 실행 목록에서 빠뜨리지 않는다."""
    path = WORKFLOW.with_name("agent-review-runtime-quality-ci.yml")
    text = path.read_text(encoding="utf-8")
    for name in ("scripts/ci/materialize_public_review_source.py",
                 "tests/test_materialize_public_review_source.py",
                 "tests/test_opencode_public_source_transport.py"):
        assert text.count(name) >= 2, name
    run = _step(yaml.safe_load(text)["jobs"]["agent_review_runtime_quality"], "Verify public coverage source transport")["run"]
    assert "tests/test_materialize_public_review_source.py" in run
    assert "tests/test_opencode_public_source_transport.py" in run
    assert "--cov-branch" in run
    assert "--cov-fail-under=100" in run


@pytest.mark.parametrize("visibility,success", [("false", True), ("true", True), ("", False), ("False", False), ("unknown", False)])
def test_actual_visibility_guard(visibility, success, tmp_path):
    """실제 run block이 unknown을 성공 skip으로 바꾸지 않는다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    script = _step(jobs["coverage-evidence"], "Require explicit coverage source visibility")["run"]
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, check=False,
                            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "IS_PRIVATE": visibility})
    assert (result.returncode == 0) is success


@pytest.mark.parametrize("sha,workflow,success", [
    ("a" * 40, "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main", True),
    ("main", "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main", False),
    ("", "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main", False),
    ("a" * 40 + "\n", "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main", False),
    ("a" * 40, "other/repo/.github/workflows/opencode-review-dispatch.yml@refs/heads/main", False),
])
def test_actual_trusted_source_resolver(sha, workflow, success, tmp_path):
    """실제 trusted resolver를 실행해 exactSHA 및 중앙identity를 확인한다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    script = _step(jobs["coverage-evidence"], "Resolve trusted OpenCode source ref")["run"]
    output = tmp_path / "output"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, check=False,
                            env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                                 "TRUSTED_WORKFLOW_SHA": sha, "TRUSTED_WORKFLOW_REF": workflow,
                                 "GITHUB_OUTPUT": str(output)})
    assert (result.returncode == 0) is success
    if success:
        assert output.read_text() == f"ref={sha}\n"
    else:
        assert not output.read_text()
