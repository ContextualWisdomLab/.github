"""Central CGC admission is executable, fixed-repository, and fail closed."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/context-graph-contracts-ci.yml"
)
REPOSITORY = "ContextualWisdomLab/context-graph-contracts"


def workflow():
    """Load Actions YAML without YAML 1.1's boolean interpretation of on."""
    assert WORKFLOW.exists(), "central CGC workflow is missing"
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def producer_jobs():
    """Return the five source-executing gates, excluding the result-only aggregate."""
    return {name: job for name, job in workflow()["jobs"].items() if name != "required"}


@pytest.mark.parametrize(
    "event,repository,head,sha,expected",
    [
        ("push", REPOSITORY, "", "a" * 40, 0),
        ("pull_request", REPOSITORY, REPOSITORY, "b" * 40, 0),
        ("push", "ContextualWisdomLab/other", "", "a" * 40, 1),
        ("pull_request", REPOSITORY, "attacker/context-graph-contracts", "a" * 40, 1),
        ("pull_request", REPOSITORY, "", "a" * 40, 1),
        ("pull_request_target", REPOSITORY, REPOSITORY, "a" * 40, 1),
        ("workflow_dispatch", REPOSITORY, REPOSITORY, "a" * 40, 1),
        ("repository_dispatch", REPOSITORY, REPOSITORY, "a" * 40, 1),
        ("schedule", REPOSITORY, REPOSITORY, "a" * 40, 1),
        ("push", REPOSITORY, "", "main", 1),
        ("pull_request", REPOSITORY, REPOSITORY, "", 1),
        ("push", REPOSITORY.lower(), "", "a" * 40, 1),
    ],
)
def test_parsed_admission_shell(event, repository, head, sha, expected):
    """Execute each actual job admission script, not a test-side reimplementation."""
    for job in producer_jobs().values():
        step = job["steps"][0]
        assert step["name"] == "Admit candidate before checkout"
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]],
            env={
                **os.environ,
                "EVENT_NAME": event,
                "REPOSITORY": repository,
                "HEAD_REPOSITORY": head,
                "EXPECTED_SHA": sha,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr


def test_private_state_and_success_only_uploads():
    """Fresh private tool state is cleaned even when candidate execution fails."""
    for job in producer_jobs().values():
        steps = job["steps"]
        private = next((step for step in steps if step.get("id") == "private"), None)
        assert private is not None, "private job state must be initialized"
        assert "umask 077" in private["run"]
        assert "mktemp -d" in private["run"]
        assert "UV_CACHE_DIR" in private["run"]
        assert "UV_PROJECT_ENVIRONMENT" in private["run"]
        assert (
            steps[-1]["if"] == "${{ always() && steps.private.outcome == 'success' }}"
        )
        assert "PRIVATE_ROOT" in steps[-1]["run"]
        for step in steps:
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                assert step.get("if") == "${{ success() }}"
                assert step["with"]["if-no-files-found"] == "error"


def test_all_source_gates_retained_without_release_signing():
    """The producer keeps five non-signing gates and no privileged signer."""
    data = workflow()
    assert set(producer_jobs()) == {
        "test",
        "package",
        "installed-wheel",
        "release-package-reproducibility",
        "package-evidence",
    }
    runs = {
        name: "\n".join(step.get("run", "") for step in job["steps"])
        for name, job in producer_jobs().items()
    }
    test = runs["test"]
    for gate in (
        "uv lock --check",
        "uv sync --frozen --extra dev",
        "compileall -q src",
        "ruff check .",
        "coverage run -m pytest",
        "coverage report",
    ):
        assert gate in test
    assert "coverage report --fail-under=100" in test
    assert data["jobs"]["test"]["strategy"]["matrix"]["python-version"] == [
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    ]
    for job in producer_jobs().values():
        assert any(
            step.get("with", {}).get("version") == "0.11.32" for step in job["steps"]
        )
    package = runs["package"]
    for gate in (
        "uv build --wheel --sdist",
        "required_suffixes",
        "--no-index",
        "cwl-context-conformance-verify",
        "cwl-context-conformance-admit",
    ):
        assert gate in package
    assert (
        "verify_reproducible_package_builds.py"
        in runs["release-package-reproducibility"]
    )
    assert "verify_reproducible_package_builds.py" in runs["package-evidence"]
    assert "cwl-context-package-evidence-verify" in runs["package-evidence"]
    assert "cwl-context-release-evidence-admit" in runs["installed-wheel"]
    for job in producer_jobs().values():
        assert not any(
            "actions/attest@" in step.get("uses", "") for step in job["steps"]
        )
        assert job.get("permissions", {}).get("id-token") is None


def test_private_shell_creates_and_removes_mode_0700_state(tmp_path):
    """Execute initialization/cleanup with seeded stale outputs in a scratch workspace."""
    for job in producer_jobs().values():
        workspace = tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
        runner = tmp_path / "runner"
        runner.mkdir(exist_ok=True)
        env_file = tmp_path / "env"
        env_file.write_text("")
        stale = workspace / "dist"
        stale.mkdir(exist_ok=True)
        (stale / "stale.whl").write_text("stale fixture")
        env = {
            **os.environ,
            "GITHUB_WORKSPACE": str(workspace),
            "RUNNER_TEMP": str(runner),
            "GITHUB_ENV": str(env_file),
        }
        for step in job["steps"]:
            if step.get("id") == "private":
                subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", step["run"]], env=env, check=True
                )
        values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        private = Path(values["PRIVATE_ROOT"])
        assert private.stat().st_mode & 0o777 == 0o700
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", job["steps"][-1]["run"]],
            env={**env, **values},
            check=True,
        )
        assert not private.exists()
        assert not stale.exists()


def test_minimal_call_interface():
    """No caller-selected execution, credentials, or hosted fallback is exposed."""
    data = workflow()
    assert data["on"] == {"workflow_call": "null"}
    assert data["permissions"] == {"contents": "read"}
    assert "concurrency" not in data, "concurrency belongs only to the caller"
    for job in producer_jobs().values():
        assert job["runs-on"] == {
            "group": "CWL CI isolated",
            "labels": ["self-hosted", "Linux", "X64", "cwlab-ci-isolated"],
        }
        for step in job["steps"]:
            if "actions/checkout@" in step.get("uses", ""):
                assert step["with"]["repository"] == REPOSITORY
                assert step["with"]["persist-credentials"] == "false"
                assert (
                    step["with"]["ref"]
                    == "${{ github.event.pull_request.head.sha || github.sha }}"
                )


def test_cleanup_requires_successful_private_initialization():
    """Rejected admission must never clean another candidate's workspace."""
    for job in producer_jobs().values():
        assert (
            job["steps"][-1]["if"]
            == "${{ always() && steps.private.outcome == 'success' }}"
        )


def test_private_environment_records_have_no_indentation(tmp_path):
    """GitHub environment keys must remain exact after YAML block parsing."""
    runner = tmp_path / "runner"
    runner.mkdir()
    for job in producer_jobs().values():
        env_file = tmp_path / "environment"
        env_file.write_text("")
        step = next(step for step in job["steps"] if step.get("id") == "private")
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]],
            env={**os.environ, "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(env_file)},
            check=True,
        )
        records = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        assert set(records) >= {
            "PRIVATE_ROOT",
            "UV_CACHE_DIR",
            "UV_PROJECT_ENVIRONMENT",
            "TMPDIR",
            "XDG_CACHE_HOME",
        }


def test_private_state_overrides_inherited_home_and_python_paths(tmp_path):
    """Persistent runner home/config and import paths cannot reach tool commands."""
    for job in producer_jobs().values():
        env_file = tmp_path / "environment"
        env_file.write_text("")
        step = next(step for step in job["steps"] if step.get("id") == "private")
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]],
            env={
                **os.environ,
                "RUNNER_TEMP": str(tmp_path),
                "GITHUB_ENV": str(env_file),
                "HOME": "/inherited/home",
                "PYTHONPATH": "/inherited/source",
                "PYTHONHOME": "/inherited/python",
                "PYTHONOPTIMIZE": "2",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        records = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        assert records["HOME"] == records["PRIVATE_ROOT"] + "/home"
        assert Path(records["HOME"]).is_dir()
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"):
            assert records[key] == ""
        assert records["PYTHONNOUSERSITE"] == "1"


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("escape", ["traversal", "symlink", "nested"])
def test_cleanup_never_follows_private_root_escape(tmp_path, phase, escape):
    """Actual cleanup refuses glob-matching traversal and linked private parents."""
    for index, job in enumerate(producer_jobs().values()):
        base = tmp_path / str(index)
        workspace = base / "workspace"
        runner = base / "runner"
        victim = base / "victim"
        for path in (workspace, runner, victim):
            path.mkdir(parents=True)
        marker = victim / "keep"
        marker.write_text("unrelated state")
        if escape == "traversal":
            (runner / "cgc-ci.12345678").mkdir()
            private = str(runner / "cgc-ci.12345678/../../victim")
        elif escape == "symlink":
            (runner / "cgc-ci.12345678").symlink_to(base, target_is_directory=True)
            private = str(runner / "cgc-ci.12345678/victim")
        else:
            (runner / "cgc-ci.12345678").mkdir()
            (runner / "cgc-ci.12345678/victim").symlink_to(
                victim, target_is_directory=True
            )
            private = str(runner / "cgc-ci.12345678/victim") + "/"
        step = job["steps"][1] if phase == "before" else job["steps"][-1]
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]],
            env={
                **os.environ,
                "GITHUB_WORKSPACE": str(workspace),
                "RUNNER_TEMP": str(runner),
                "PRIVATE_ROOT": private,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert marker.exists(), (result.returncode, result.stderr, private)
        if phase == "after":
            assert result.returncode != 0, "unsafe private cleanup must fail closed"


@pytest.mark.parametrize(
    "job_name,step_name,venv_name",
    [
        (
            "package",
            "Smoke-test installed contracts, schemas, and conformance fixtures",
            ".package-smoke",
        ),
        (
            "package",
            "Smoke-test installed conformance evidence commands",
            ".package-smoke",
        ),
        (
            "installed-wheel",
            "Exercise Context Assertion admission SDK from installed wheel",
            ".receipt-smoke",
        ),
        (
            "installed-wheel",
            "Exercise release evidence from installed wheel",
            ".receipt-smoke",
        ),
    ],
)
def test_installed_smoke_ignores_source_imports(
    tmp_path, job_name, step_name, venv_name
):
    """Actual smoke shell reaches installed modules despite poisoned source paths."""
    import sys

    venv = tmp_path / venv_name
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
    )
    purelib = subprocess.run(
        [
            str(venv / "bin/python"),
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    installed = Path(purelib) / "cwl_context_contracts"
    installed.mkdir()
    (installed / "__init__.py").write_text("raise RuntimeError('INSTALLED_WITNESS')\n")
    source = tmp_path / "cwl_context_contracts"
    source.mkdir()
    (source / "__init__.py").write_text("raise RuntimeError('SOURCE_LEAK')\n")
    for command in ("cwl-context-conformance", "cwl-context-conformance-manifest"):
        script = venv / "bin" / command
        script.write_text(f"#!{venv}/bin/python\nimport cwl_context_contracts\n")
        script.chmod(0o700)
    step = next(
        step
        for step in workflow()["jobs"][job_name]["steps"]
        if step.get("name") == step_name
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "PRIVATE_ROOT": str(tmp_path),
            "PYTHONPATH": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "INSTALLED_WITNESS" in result.stderr, result.stderr
    assert "SOURCE_LEAK" not in result.stderr


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", ""])
def test_required_aggregate_refuses_any_non_success(result):
    """Required result fails closed across every producer dependency result."""
    jobs = workflow()["jobs"]
    required = jobs.get("required")
    assert required is not None, "one stable required result must cover all five gates"
    gates = set(jobs) - {"required"}
    assert set(required["needs"]) == gates
    assert required["if"] == "${{ always() }}"
    for failed_gate in gates:
        env = {
            **os.environ,
            **{name.upper().replace("-", "_") + "_RESULT": "success" for name in gates},
        }
        env[failed_gate.upper().replace("-", "_") + "_RESULT"] = result
        actual = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", required["steps"][0]["run"]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert actual.returncode == (0 if result == "success" else 1), actual.stderr


def test_private_initialization_accepts_symlinked_runner_parent(tmp_path):
    """Platform aliases of RUNNER_TEMP are canonicalized before cleanup admission."""
    runner = tmp_path / "real"
    runner.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(runner, target_is_directory=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for job in producer_jobs().values():
        env_file = tmp_path / "environment"
        env_file.write_text("")
        env = {
            **os.environ,
            "RUNNER_TEMP": str(alias),
            "GITHUB_ENV": str(env_file),
            "GITHUB_WORKSPACE": str(workspace),
        }
        private = next(step for step in job["steps"] if step.get("id") == "private")
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", private["run"]], env=env, check=True
        )
        records = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", job["steps"][-1]["run"]],
            env={**env, **records},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert not Path(records["PRIVATE_ROOT"]).exists()
