"""공개 exact-head 전달은 quota에 의존하지 않고 private 경로는 보존한다."""
from pathlib import Path
import json
import os
import subprocess
import sys

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


def test_private_source_refuses_public_artifact_destination_before_transport(tmp_path) -> None:
    """비공개 PR 원문이 공개 리뷰 저장소의 artifact 저장소에 전달되지 않음을 검증한다."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    steps = jobs["validate-pr-metadata"]["steps"]
    names = [step.get("name") for step in steps]
    guard = _step(jobs["validate-pr-metadata"], "Refuse private source on a public artifact destination")
    assert names.index(guard["name"]) < names.index("Exchange OpenCode app token for target repository coverage reads")
    assert names.index(guard["name"]) < names.index("Materialize pull request merge tree for coverage measurement")
    assert names.index(guard["name"]) < names.index("Upload materialized pull request merge tree")
    assert "if" not in guard
    assert guard.get("continue-on-error", False) is False
    assert guard["env"]["SOURCE_REPOSITORY_PRIVATE"] == "${{ steps.validate.outputs.is_private }}"
    assert guard["env"]["ARTIFACT_REPOSITORY"] == "${{ github.repository }}"
    assert guard["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "ARTIFACT_REPOSITORY_PRIVATE" not in guard["env"]
    for index, (source, destination, allowed) in enumerate((
        ("true", "false", False), ("true", "", False), ("true", "unknown", False),
        ("true", "true", True), ("false", "false", True), ("false", "true", True),
        ("true", '"true"', False), ("true", "null", False),
        ("", "true", False), ("unknown", "true", False), ("True", "true", False),
    )):
        response = '{"full_name":"Fixture/review","private":' + (destination or "null") + '}'
        result, _ = _run_receiving_guard(guard, tmp_path / str(index), source, response)
        assert (result.returncode == 0) is allowed, (source, destination, result.stderr)


@pytest.mark.parametrize("destination, reaches_git", [("false", False), ("", False), ("true", True)])
def test_private_destination_guard_stops_actual_materialization(destination, reaches_git, tmp_path):
    """실제 guard와 materialize shell을 연결해 Git 진입 전 거부를 검증한다."""
    metadata = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate-pr-metadata"]
    guard = _step(metadata, "Refuse private source on a public artifact destination")["run"]
    materialize = _step(metadata, "Materialize pull request merge tree for coverage measurement")["run"]
    binary = tmp_path / "bin"
    binary.mkdir()
    marker = tmp_path / "git-called"
    git = binary / "git"
    git.write_text(
        f"#!{sys.executable}\nimport os\nfrom pathlib import Path\n"
        "Path(os.environ['GIT_MARKER']).write_text('synthetic git boundary')\n"
        "raise SystemExit(37)\n"
    )
    git.chmod(0o755)
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\nimport os\n"
        "print(os.environ['API_RESPONSE'])\n"
    )
    gh.chmod(0o755)
    runner = tmp_path / "runner"
    runner.mkdir()
    result = subprocess.run(
        ["/bin/bash", "-c", guard + "\n" + materialize],
        capture_output=True, text=True, check=False, timeout=15,
        env={"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(tmp_path),
             "SOURCE_REPOSITORY_PRIVATE": "true", "ARTIFACT_REPOSITORY": "Fixture/review",
             "API_RESPONSE": '{"full_name":"Fixture/review","private":' + (destination or "null") + '}',
             "RUNNER_TEMP": str(runner), "COVERAGE_SOURCE_WORKDIR": str(runner / "source"),
             "COVERAGE_SOURCE_ARCHIVE": str(runner / "source.tar"), "GH_TOKEN": "synthetic-only",
             "TARGET_REPOSITORY": "Fixture/private", "PR_NUMBER": "1",
             "PR_BASE_SHA": "a" * 40, "PR_HEAD_SHA": "b" * 40,
             "GITHUB_SERVER_URL": "https://fixture.invalid", "GIT_MARKER": str(marker)},
    )
    assert marker.exists() is reaches_git
    assert result.returncode == (37 if reaches_git else 1)
    assert not list(runner.iterdir())


def _run_receiving_guard(guard, tmp_path, source, response, status=0, event_private="true"):
    """실제 guard를 합성 GitHub metadata 경계와 실행하고 API argv를 보존한다."""
    binary = tmp_path / "bin"
    binary.mkdir(parents=True)
    calls = tmp_path / "api-calls"
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "Path(os.environ['API_CALLS']).write_text(json.dumps(sys.argv[1:]))\n"
        "print(os.environ['API_RESPONSE'])\n"
        "raise SystemExit(int(os.environ['API_STATUS']))\n"
    )
    gh.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", "-c", guard["run"]], capture_output=True, text=True,
        check=False, timeout=15,
        env={"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(tmp_path),
             "SOURCE_REPOSITORY_PRIVATE": source, "ARTIFACT_REPOSITORY_PRIVATE": event_private,
             "ARTIFACT_REPOSITORY": "Fixture/review", "GH_TOKEN": "synthetic-only",
             "API_CALLS": str(calls), "API_RESPONSE": response, "API_STATUS": str(status)},
    )
    return result, json.loads(calls.read_text()) if calls.exists() else None


def test_live_receiving_visibility_rejects_stale_private_event(tmp_path):
    """이벤트가 private였어도 현재 수신 저장소가 public이면 전송 전에 거부한다."""
    metadata = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate-pr-metadata"]
    guard = _step(metadata, "Refuse private source on a public artifact destination")
    result, calls = _run_receiving_guard(
        guard, tmp_path, "true", '{"full_name":"Fixture/review","private":false}'
    )
    assert result.returncode != 0
    assert calls == ["api", "repos/Fixture/review"]


@pytest.mark.parametrize("source,response,status,allowed,query", [
    ("true", '{"full_name":"Fixture/review","private":true}', 0, True, True),
    ("true", '{"full_name":"Fixture/review","private":false}', 0, False, True),
    ("true", '{"full_name":"Fixture/review","private":"true"}', 0, False, True),
    ("true", '{"full_name":"Fixture/review","private":null}', 0, False, True),
    ("true", '{"full_name":"Fixture/review"}', 0, False, True),
    ("true", '{"full_name":"Other/review","private":true}', 0, False, True),
    ("true", '{"full_name":"Fixture/review","private":true}', 1, False, True),
    ("true", 'invalid-json', 0, False, True),
    ("true", '', 0, False, True),
    ("true", '{"full_name":"Fixture/review","private":false}\n'
     '{"full_name":"Fixture/review","private":true}', 0, False, True),
    ("false", 'invalid-json', 1, True, False),
    ("unknown", '{"full_name":"Fixture/review","private":true}', 0, False, False),
])
def test_receiving_guard_uses_typed_live_metadata(source, response, status, allowed, query, tmp_path):
    """현재 API의 저장소 identity와 Boolean을 확인하며 public 경로는 조회하지 않는다."""
    metadata = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate-pr-metadata"]
    guard = _step(metadata, "Refuse private source on a public artifact destination")
    result, calls = _run_receiving_guard(guard, tmp_path, source, response, status)
    assert (result.returncode == 0) is allowed
    assert calls == (["api", "repos/Fixture/review"] if query else None)


def test_private_upload_rechecks_live_receiving_visibility(tmp_path):
    """archive 생성 뒤 업로드 직전에 동일한 fail-closed 조회를 다시 실행한다."""
    metadata = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate-pr-metadata"]
    names = [step.get("name") for step in metadata["steps"]]
    name = "Recheck private artifact destination before upload"
    assert name in names
    recheck = _step(metadata, name)
    early = _step(metadata, "Refuse private source on a public artifact destination")
    assert recheck["if"] == "steps.validate.outputs.is_private == 'true'"
    assert recheck.get("continue-on-error", False) is False
    assert names.index(name) + 1 == names.index("Upload materialized pull request merge tree")
    assert recheck["env"] == early["env"]
    assert recheck["run"] == early["run"]
    result, calls = _run_receiving_guard(
        recheck, tmp_path, "true", '{"full_name":"Fixture/review","private":false}'
    )
    assert result.returncode != 0
    assert calls == ["api", "repos/Fixture/review"]


def test_private_to_public_transition_stops_upload_witness(tmp_path):
    """전송 전 private 양성 뒤 public 전환을 재조회하여 upload witness 전에 거부한다."""
    metadata = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate-pr-metadata"]
    early = _step(metadata, "Refuse private source on a public artifact destination")
    late = _step(metadata, "Recheck private artifact destination before upload")
    binary = tmp_path / "bin"
    binary.mkdir()
    calls = tmp_path / "calls"
    upload = tmp_path / "upload-called"
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:] == ['api', 'repos/Fixture/review']\n"
        "calls = Path(os.environ['API_CALLS'])\n"
        "n = int(calls.read_text()) if calls.exists() else 0\n"
        "calls.write_text(str(n + 1))\n"
        "print(json.dumps({'full_name': 'Fixture/review', 'private': n == 0}))\n"
    )
    gh.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", "-c", early["run"] + "\n" + late["run"] + '\ntouch "$UPLOAD_MARKER"'],
        capture_output=True, text=True, check=False, timeout=15,
        env={"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(tmp_path),
             "SOURCE_REPOSITORY_PRIVATE": "true", "ARTIFACT_REPOSITORY": "Fixture/review",
             "GH_TOKEN": "synthetic-only", "API_CALLS": str(calls), "UPLOAD_MARKER": str(upload)},
    )
    assert result.returncode == 1
    assert calls.read_text() == "2"
    assert not upload.exists()


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
