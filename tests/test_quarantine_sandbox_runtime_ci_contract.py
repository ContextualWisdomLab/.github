"""Static contracts for the future dedicated QSR reusable CI lane."""

from pathlib import Path
import os
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/quarantine-sandbox-runtime-ci.yml"
DOCTORING = ROOT / "docs/doctoring/quarantine-sandbox-runtime-self-hosted-ci.md"


def workflow():
    """Read YAML without coercing GitHub's on key to a boolean."""
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_reusable_workflow_exists_and_is_call_only():
    """Require the owned workflow before testing any YAML mechanics."""
    assert WORKFLOW.is_file(), "central QSR reusable workflow is missing"
    assert workflow()["on"] == {"workflow_call": ""}


# Frozen from the actual source workflow; never load a sibling checkout in tests.
EXPECTED_MECHANICS = {
    "verify": {
        "steps": [
            {
                "uses": "dtolnay/rust-toolchain@4be7066ada62dd38de10e7b70166bc74ed198c30",
                "with": {"toolchain": "1.97.1", "components": "clippy, rustfmt"},
            },
            {
                "name": "Verify dependency lock",
                "run": "cargo metadata --locked --no-deps --format-version 1 > /dev/null",
            },
            {
                "name": "Validate repository policy",
                "run": "python3 scripts/validate_repository.py",
            },
            {
                "name": "Test coverage evidence parser",
                "run": "python3 -m unittest scripts/test_check_coverage.py",
            },
            {"name": "Check formatting", "run": "cargo fmt --check"},
            {"name": "Test", "run": "cargo test --locked --workspace --all-targets"},
            {
                "name": "Lint",
                "run": "cargo clippy --locked --workspace --all-targets -- -D warnings",
            },
            {
                "name": "Build documentation",
                "env": {"RUSTDOCFLAGS": "-D warnings"},
                "run": "cargo doc --locked --workspace --no-deps",
            },
        ],
        "env": {},
    },
    "coverage": {
        "steps": [
            {
                "uses": "dtolnay/rust-toolchain@4be7066ada62dd38de10e7b70166bc74ed198c30",
                "with": {"toolchain": "1.97.1", "components": "llvm-tools-preview"},
            },
            {
                "name": "Verify dependency lock",
                "run": "cargo metadata --locked --no-deps --format-version 1 > /dev/null",
            },
            {
                "name": "Install pinned coverage tool",
                "run": "cargo +1.97.1 install cargo-llvm-cov --locked --version 0.8.6",
            },
            {
                "name": "Generate production coverage evidence",
                "run": "cargo llvm-cov --workspace --lib --tests --json --output-path "
                "coverage.json",
            },
            {
                "name": "Upload production coverage evidence",
                "uses": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
                "with": {
                    "name": "coverage-json-${{ github.event.pull_request.head.sha || "
                    "github.sha }}",
                    "path": "coverage.json",
                    "if-no-files-found": "error",
                },
            },
            {
                "name": "Explain and enforce complete production coverage",
                "run": "python3 scripts/check_coverage.py coverage.json",
            },
        ],
        "env": {},
    },
    "branch-coverage": {
        "steps": [
            {
                "uses": "dtolnay/rust-toolchain@4be7066ada62dd38de10e7b70166bc74ed198c30",
                "with": {
                    "toolchain": "nightly-2026-07-01",
                    "components": "llvm-tools-preview",
                },
            },
            {
                "name": "Verify dependency lock",
                "run": "cargo +nightly-2026-07-01 metadata --locked --no-deps "
                "--format-version 1 > /dev/null",
            },
            {
                "name": "Install pinned coverage tool",
                "run": "cargo +nightly-2026-07-01 install cargo-llvm-cov --locked "
                "--version 0.8.6",
            },
            {
                "name": "Generate branch coverage evidence",
                "run": "cargo +nightly-2026-07-01 llvm-cov --branch --workspace "
                "--lib --tests --json --output-path branch-coverage.json",
            },
            {
                "name": "Print missing branch coverage lines",
                "run": "cargo +nightly-2026-07-01 llvm-cov report --branch "
                "--show-missing-lines",
            },
            {
                "name": "Upload branch coverage evidence",
                "uses": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
                "with": {
                    "name": "branch-coverage-json-${{ "
                    "github.event.pull_request.head.sha || github.sha "
                    "}}",
                    "path": "branch-coverage.json",
                    "if-no-files-found": "error",
                },
            },
            {
                "name": "Enforce complete production branch coverage",
                "run": "python3 scripts/check_coverage.py --require-branches "
                "branch-coverage.json",
            },
        ],
        "env": {},
    },
    "podman-e2e-positive-lsm": {
        "steps": [
            {
                "uses": "dtolnay/rust-toolchain@4be7066ada62dd38de10e7b70166bc74ed198c30",
                "with": {"toolchain": "1.97.1"},
            },
            {
                "name": "Verify dedicated positive LSM runner contract",
                "run": 'test -n "$RUNNER_NAME"\n'
                'test "$(podman --version)" = "podman version '
                '5.8.4"\n'
                "podman info --format json > podman-info.json\n"
                "python3 - <<'PY'\n"
                "import json\n"
                'with open("podman-info.json", encoding="utf-8") as '
                "handle:\n"
                "    security = "
                'json.load(handle)["host"]["security"]\n'
                'assert security["rootless"] is True\n'
                'assert security["selinuxEnabled"] is True\n'
                "print(f\"selinuxEnabled={security['selinuxEnabled']}\")\n"
                "PY\n",
            },
            {
                "name": "Pre-pull immutable fixture outside the "
                "application launch path",
                "run": 'podman pull --quiet "$QSR_PODMAN_E2E_IMAGE"\n'
                'podman image inspect "$QSR_PODMAN_E2E_IMAGE" '
                ">/dev/null\n",
            },
            {
                "name": "Execute real positive LSM isolation and cleanup acceptance",
                "run": "cargo test --locked --test podman_rootless_e2e -- "
                "--ignored --exact "
                "rootless_podman_effective_isolation_and_cleanup "
                "--nocapture",
            },
            {
                "name": "Reject leaked runtime-owned resources",
                "if": "always()",
                "run": 'leaked_containers="$(podman ps -a --filter '
                "label=org.contextualwisdomlab.sandbox.identity "
                "--format '{{.ID}}')\"\n"
                'test -z "$leaked_containers"\n'
                'leaked_networks="$(podman network ls --format '
                "'{{.Name}}' | grep '^qsr-net-' || true)\"\n"
                'test -z "$leaked_networks"\n',
            },
        ],
        "env": {
            "QSR_PODMAN_E2E_IMAGE": "docker.io/library/python@sha256:94457973ea8a27a799f0b8ea1fe3e3147fcbebaed63497a8af63b28195a08108",
            "QSR_HOST_SECRET_CANARY": "must-not-enter-the-isolated-application",
        },
    },
}


RETAINED_JOB_NAMES = tuple(EXPECTED_MECHANICS)


def test_preserves_all_four_job_mechanics():
    """Preserve each required lane and keep admission evidence separate."""
    jobs = workflow()["jobs"]
    assert set(jobs) == {"admission", "acceptance", *EXPECTED_MECHANICS}, (
        "admission, evidence result and four source lanes required"
    )
    for name, expected in EXPECTED_MECHANICS.items():
        job = jobs[name]
        steps = [
            step
            for step in job["steps"]
            if not step.get("uses", "").startswith("actions/checkout@")
            and step.get("name") != "Verify exact checkout"
        ]
        if name == "podman-e2e-positive-lsm":
            # Only the independently reproduced baseline cleanup error is repaired.
            assert steps[:-1] == expected["steps"][:-1], name
            assert steps[-1]["name"] == expected["steps"][-1]["name"]
            assert steps[-1]["if"] == "always()"
            assert steps[-1]["run"].startswith(
                expected["steps"][-1]["run"].split("leaked_networks=", 1)[0]
            )
        else:
            assert steps == expected["steps"], name
        assert job.get("env", {}) == expected["env"], name


CANDIDATE = "${{ github.event.pull_request.head.sha || github.sha }}"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def test_exact_event_candidate_is_checked_before_any_source_execution():
    """Do not accept caller-selected SHAs or execute code before checking HEAD."""
    for name in RETAINED_JOB_NAMES:
        job = workflow()["jobs"][name]
        assert job["steps"][0] == {
            "uses": CHECKOUT,
            "with": {"ref": CANDIDATE, "persist-credentials": "false"},
        }, f"{name} needs exact checkout first"
        assert job["steps"][1] == {
            "name": "Verify exact checkout",
            "env": {"EXPECTED_HEAD_SHA": CANDIDATE},
            "run": 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"',
        }, f"{name} needs fail-closed HEAD verification"


def test_admission_job_rejects_unsupported_callers_before_product_checkout():
    """Rejected callers must fail instead of making every required lane skip green."""
    jobs = workflow()["jobs"]
    assert "admission" in jobs, "explicit failed admission is missing"
    admission = jobs["admission"]
    assert "if" not in admission
    assert admission["runs-on"] == {
        "group": "CWL QSR hostile workload",
        "labels": ["self-hosted", "linux", "cwl-hostile-workload"],
    }
    assert admission["permissions"] == {"contents": "read"}
    assert set(admission) == {"runs-on", "permissions", "steps"}
    assert len(admission["steps"]) == 1
    step = admission["steps"][0]
    assert step["name"] == "Reject unsupported caller or event"
    assert step["env"] == {
        "CALLER_REPOSITORY": "${{ github.repository }}",
        "EVENT_NAME": "${{ github.event_name }}",
        "PR_HEAD_REPOSITORY": "${{ github.event.pull_request.head.repo.full_name || '' }}",
    }
    script = step["run"]
    assert "exit 1" in script
    assert "ContextualWisdomLab/quarantine-sandbox-runtime" in script
    assert "pull_request_target" not in script


def test_token_is_contents_read_only_without_secret_or_write_surfaces():
    """No credential inheritance, token escalation, environment or output channel."""
    data = workflow()
    assert data.get("permissions") == {"contents": "read"}
    assert set(data) <= {"name", "on", "permissions", "concurrency", "jobs"}
    for job in data["jobs"].values():
        assert set(job) <= {"if", "runs-on", "steps", "env", "needs", "permissions"}
        for step in job["steps"]:
            assert set(step) <= {"name", "uses", "with", "run", "env", "if"}
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "secrets:",
        "secrets.",
        "inputs.",
        "github.token",
        "github-script@",
        "GITHUB_TOKEN:",
        "id-token:",
        "write",
        "continue-on-error:",
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "gh api",
        "git push",
    ):
        assert forbidden not in text


def test_all_jobs_require_the_operator_requested_dedicated_group():
    """No hosted fallback, control pool or user-controlled runner selection."""
    for name, job in workflow()["jobs"].items():
        labels = ["self-hosted", "linux", "cwl-hostile-workload"]
        if name == "podman-e2e-positive-lsm":
            labels.append("selinux")
        assert job["runs-on"] == {
            "group": "CWL QSR hostile workload",
            "labels": labels,
        }, name


ADMISSION = (
    "github.repository == 'ContextualWisdomLab/quarantine-sandbox-runtime' && "
    "(github.event_name == 'push' || "
    "(github.event_name == 'pull_request' && "
    "github.event.pull_request.head.repo.full_name == github.repository))"
)


def test_admission_excludes_forks_other_repositories_and_privileged_events():
    """The original positive guard is retained and narrowed on every job."""
    for name in RETAINED_JOB_NAMES:
        job = workflow()["jobs"][name]
        assert job.get("if") == ADMISSION, name
        assert job.get("needs") == "admission", name


def test_network_enumeration_failure_is_not_zero_leak_evidence():
    """Exercise the actual cleanup shell with a synthetic Podman failure."""
    script = workflow()["jobs"]["podman-e2e-positive-lsm"]["steps"][-1]["run"]
    stub = """podman() {
      if [ "$1" = "ps" ]; then return 0; fi
      if [ "$1" = "network" ]; then return 42; fi
      return 99
    }
    """
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", stub + script],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 42, "network enumeration error was accepted as clean"


def test_actual_admission_shell_accepts_only_native_push_or_pull_request():
    """Reject unsupported tuples by executing trusted shell, without checking out code."""
    script = workflow()["jobs"]["admission"]["steps"][0]["run"]
    repo = "ContextualWisdomLab/quarantine-sandbox-runtime"
    cases = [
        (repo, "push", "", 0),
        (repo, "pull_request", repo, 0),
        (repo, "pull_request", "foreign/fork", 1),
        ("foreign/repo", "push", "", 1),
        (repo, "workflow_dispatch", "", 1),
        (repo, "pull_request_target", repo, 1),
        (repo, "", "", 1),
        (repo, "repository_dispatch", "", 1),
    ]
    for caller, event, head, code in cases:
        env = {
            "PATH": os.defpath,
            "CALLER_REPOSITORY": caller,
            "EVENT_NAME": event,
            "PR_HEAD_REPOSITORY": head,
        }
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            env=env,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == code, (caller, event, head)


def test_cleanup_positive_leak_and_query_error_controls():
    """No-match is valid; actual leaks or either query failure are nonpassing."""
    script = workflow()["jobs"]["podman-e2e-positive-lsm"]["steps"][-1]["run"]
    stub = """podman() {
      case "$1" in
        ps) printf '%s' "$CONTAINERS"; return "$CONTAINER_EXIT" ;;
        network) printf '%s' "$NETWORKS"; return "$NETWORK_EXIT" ;;
        *) return 99 ;;
      esac
    }
    """
    cases = [
        ("", "", "0", "0", 0),
        ("", "ordinary-net", "0", "0", 0),
        ("owned-container", "", "0", "0", 1),
        ("", "qsr-net-synthetic", "0", "0", 1),
        ("", "ordinary\nqsr-net-synthetic\nother", "0", "0", 1),
        ("", "", "41", "0", 41),
        ("", "", "0", "42", 42),
    ]
    for containers, networks, container_code, network_code, expected in cases:
        env = {
            "PATH": os.defpath,
            "CONTAINERS": containers,
            "NETWORKS": networks,
            "CONTAINER_EXIT": container_code,
            "NETWORK_EXIT": network_code,
        }
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", stub + script],
            env=env,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == expected, (containers, networks, expected)


def test_acceptance_requires_success_from_admission_and_all_four_product_jobs():
    """A terminal result must reject missing, skipped, failed or cancelled evidence."""
    jobs = workflow()["jobs"]
    assert "acceptance" in jobs, "required terminal evidence result is missing"
    job = jobs["acceptance"]
    assert job["if"] == "always()"
    assert set(job["needs"]) == {"admission", *RETAINED_JOB_NAMES}
    assert len(job["steps"]) == 1
    step = job["steps"][0]
    assert step["env"] == {
        "ADMISSION_RESULT": "${{ needs.admission.result }}",
        "VERIFY_RESULT": "${{ needs.verify.result }}",
        "COVERAGE_RESULT": "${{ needs.coverage.result }}",
        "BRANCH_RESULT": "${{ needs.branch-coverage.result }}",
        "LSM_RESULT": "${{ needs.podman-e2e-positive-lsm.result }}",
    }
    script = step["run"]
    keys = tuple(step["env"])
    for changed in keys:
        for state in ("success", "skipped", "failure", "cancelled", "", "SUCCESS"):
            env = {"PATH": os.defpath, **dict.fromkeys(keys, "success"), changed: state}
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script],
                env=env,
                capture_output=True,
                check=False,
                timeout=10,
            )
            assert result.returncode == (0 if state == "success" else 1), (
                changed,
                state,
            )


def test_workflow_concurrency_coalesces_before_runner_admission_without_caller_collision():
    """Namespace the reusable group while cancelling obsolete PR heads."""
    assert workflow().get("concurrency") == {
        "group": "qsr-central-${{ github.workflow }}-${{ github.repository }}-${{ "
        "github.event_name == 'pull_request' && github.event.pull_request.number "
        "|| github.run_id }}",
        "cancel-in-progress": "true",
    }


def test_doctoring_exposes_capacity_loss_and_unresolved_activation_gates():
    """A static source contract must not masquerade as operational acceptance."""
    assert DOCTORING.is_file(), "QSR capacity and lost-capability record is missing"
    text = DOCTORING.read_text(encoding="utf-8")
    for required in (
        "NOT_PROVISIONED",
        "CWL QSR hostile workload",
        "#1590",
        "#2083",
        "Native fork PR product execution: NOT_RUN",
        "DISABLED",
        "podman-e2e-negative-rootless-apparmor",
        "100%",
        "security review authorization",
        "prelease",
        "custody",
        "ACL",
        "candidate_sha",
        "lane",
        "immutable",
        "aggregate",
        "branch protection",
        "ci / verify",
        "ci / coverage",
        "ci / branch-coverage",
        "ci / podman-e2e-positive-lsm",
        "production_gated_command_execution_kills_and_reports_a_command_that_exceeds_its_timeout",
    ):
        assert required in text, required
