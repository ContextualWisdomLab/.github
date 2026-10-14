"""Static contracts for the future dedicated QSR reusable CI lane."""

from copy import deepcopy
import hashlib
from pathlib import Path
import os
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/quarantine-sandbox-runtime-ci.yml"
DOCTORING = ROOT / "docs/doctoring/quarantine-sandbox-runtime-self-hosted-ci.md"
CALLER_CONTRACT_COMMAND = (
    "python3 -B -m unittest scripts/test_central_ci_caller.py "
    "scripts/test_central_ci_caller_sensitivity.py"
)
CALLER_CONTRACT_STEP = {
    "name": "Test caller CI contract",
    "run": CALLER_CONTRACT_COMMAND,
}


def workflow():
    """Read YAML without coercing GitHub's on key to a boolean."""
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_reusable_workflow_exists_and_is_call_only():
    """Require the owned workflow before testing any YAML mechanics."""
    assert WORKFLOW.is_file(), "central QSR reusable workflow is missing"
    assert workflow()["on"] == {"workflow_call": ""}


# Retained source mechanics plus CALLER-CONTRACT-001; no sibling checkout reads.
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
            CALLER_CONTRACT_STEP,
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


def test_verify_runs_product_owned_caller_contract_oracles():
    """The checked-out QSR candidate must execute both caller tests in verify."""
    job = workflow()["jobs"]["verify"]
    assert "continue-on-error" not in job, "CALLER-CONTRACT-001: verify masks failure"
    steps = job["steps"]
    matches = [step for step in steps if step.get("run") == CALLER_CONTRACT_COMMAND]
    assert len(matches) == 1, (
        "CALLER-CONTRACT-001: verify does not execute the exact QSR caller oracles once"
    )
    assert matches[0] == CALLER_CONTRACT_STEP, (
        "CALLER-CONTRACT-001: caller tests must be unconditional and fail closed"
    )
    checkout_index = next(
        i for i, step in enumerate(steps) if step.get("name") == "Verify exact checkout"
    )
    assert steps.index(matches[0]) > checkout_index, (
        "CALLER-CONTRACT-001: caller tests must run after candidate HEAD verification"
    )


def caller_contract_control():
    """Derive a positive synthetic control from this producer's actual YAML."""
    data = deepcopy(workflow())
    steps = data["jobs"]["verify"]["steps"]
    steps[:] = [
        step for step in steps if step.get("name") != CALLER_CONTRACT_STEP["name"]
    ]
    index = next(
        i for i, step in enumerate(steps) if step.get("name") == "Check formatting"
    )
    steps.insert(index, dict(CALLER_CONTRACT_STEP))
    return data


def test_verify_caller_contract_accepts_exact_source_bound_control(monkeypatch):
    """The future owner repair must be accepted, not always rejected."""
    data = caller_contract_control()
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    test_verify_runs_product_owned_caller_contract_oracles()


@pytest.mark.parametrize(
    "mutation",
    (
        "removed_commands",
        "or_true",
        "alternate_path",
        "missing_sensitivity",
        "continue_on_error",
    ),
)
def test_verify_caller_contract_rejects_source_bound_mutations(monkeypatch, mutation):
    """Reject command removal, substitution, partial invocation and masked failure."""
    data = caller_contract_control()
    steps = data["jobs"]["verify"]["steps"]
    step = next(
        step for step in steps if step.get("name") == CALLER_CONTRACT_STEP["name"]
    )
    if mutation == "removed_commands":
        steps.remove(step)
    elif mutation == "or_true":
        step["run"] += " || true"
    elif mutation == "alternate_path":
        step["run"] = step["run"].replace(
            "scripts/test_central_ci_caller.py", "alternate/test_central_ci_caller.py"
        )
    elif mutation == "missing_sensitivity":
        step["run"] = step["run"].replace(
            " scripts/test_central_ci_caller_sensitivity.py", ""
        )
    else:
        step["continue-on-error"] = "true"
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    with pytest.raises(AssertionError, match="CALLER-CONTRACT-001"):
        test_verify_runs_product_owned_caller_contract_oracles()


@pytest.mark.parametrize(
    ("output", "cargo_exit", "accepted"),
    [
        (
            "\nrunning 1 test\n"
            "test rootless_podman_effective_isolation_and_cleanup ... ok\n\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; "
            "1 filtered out; finished in 0.25s\n",
            0,
            True,
        ),
        (
            "\nrunning 0 tests\n\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; "
            "2 filtered out; finished in 0.00s\n",
            0,
            False,
        ),
        ("", 0, False),
        (
            "running 1 test\ntest renamed_isolation_test ... ok\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; "
            "1 filtered out; finished in 0.00s\n",
            0,
            False,
        ),
        (
            "running 1 test\n"
            "test rootless_podman_effective_isolation_and_cleanup ... ignored\n"
            "test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; "
            "1 filtered out; finished in 0.00s\n",
            0,
            False,
        ),
        (
            "running 1 test\n"
            "test rootless_podman_effective_isolation_and_cleanup ... FAILED\n"
            "test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; "
            "1 filtered out; finished in 0.00s\n",
            101,
            False,
        ),
        (
            "running 1 test\ntest rootless_podman_effective_isolation_and_cleanup ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.25s\nrunning 1 test\ntest rootless_podman_effective_isolation_and_cleanup ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.25s\n",
            0,
            False,
        ),
        (
            "running 1 test\ntest rootless_podman_effective_isolation_and_cleanup ... ok\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.25s\n",
            0,
            False,
        ),
        (
            "running 1 test\ntest rootless_podman_effective_isolation_and_cleanup ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.25s\n",
            42,
            False,
        ),
        (
            "running 1 test\ntest rootless_podman_effective_isolation_and_cleanup ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.25s\ntest extra_test ... ok\n",
            0,
            False,
        ),
    ],
)
def test_positive_lsm_actual_shell_rejects_missing_execution(
    tmp_path, output, cargo_exit, accepted
):
    """Exercise the actual YAML command with synthetic Cargo output and exit."""
    script = next(
        step["run"]
        for step in workflow()["jobs"]["podman-e2e-positive-lsm"]["steps"]
        if step.get("name")
        == "Execute real positive LSM isolation and cleanup acceptance"
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    expected_argv = (
        "test --locked --test podman_rootless_e2e -- --ignored --exact "
        "rootless_podman_effective_isolation_and_cleanup "
        "--color never --format pretty --test-threads=1"
    )
    cargo = tools / "cargo"
    cargo.write_text(
        "#!/bin/sh\n"
        f'test "$*" = "{expected_argv}" || exit 64\n'
        'test "$RUST_TEST_NOCAPTURE" = "0" || exit 65\n'
        'printf "%s" "$CARGO_OUTPUT"\n'
        'exit "$CARGO_EXIT"\n',
        encoding="utf-8",
    )
    cargo.chmod(0o700)
    (tools / "python3").symlink_to(sys.executable)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": str(tools) + os.pathsep + os.defpath,
            "CARGO_OUTPUT": output,
            "CARGO_EXIT": str(cargo_exit),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert (result.returncode == 0) == accepted, (
        "LSM-TEST-001: execution witness was misclassified",
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if cargo_exit:
        assert result.returncode == cargo_exit, "Cargo producer failure was masked"


def test_positive_lsm_exact_filter_requires_one_passing_test_witness():
    """Require capture mode and an unconditionally executed counted witness."""
    step = next(
        step
        for step in workflow()["jobs"]["podman-e2e-positive-lsm"]["steps"]
        if step.get("name")
        == "Execute real positive LSM isolation and cleanup acceptance"
    )
    assert set(step) == {"name", "run"}
    script = step["run"]
    assert script.startswith("RUST_TEST_NOCAPTURE=0 python3 -I - <<'PY'\n")
    assert "LSM-TEST-001" in script
    assert "--nocapture" not in script
    assert "--no-capture" not in script
    assert "tee " not in script, "do not introduce a fixed evidence file"


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
            and step.get("name")
            not in {"Verify exact checkout", "Verify caller and event before checkout"}
        ]
        if name in SRC03_LANES:
            test_src03_upload_is_run_bound_and_preceded_by_admission()
            # Literal reviewed script digests, never derived from workflow() at runtime.
            # Behavioral producer/admission controls below remain mandatory supplements.
            generator_hash = "091ae4e9cb783d06138a6e62be6ad8255b9c5b47637a23da2628b419e6dacbee"
            guard_hash = "af57131f5083f77780dc66ed46d2c70679165bef149732c1309e9745132d7d82"
            generator_name, filename = SRC03_LANES[name]
            root_expression = (
                "${{ runner.temp }}/qsr-evidence-${{ github.run_id }}-"
                "${{ github.run_attempt }}-" + name + "-" + CANDIDATE
            )
            expected_steps = deepcopy(expected["steps"])
            for step in expected_steps:
                if step.get("name") == generator_name:
                    step["run"] = generator_hash
                    step["env"] = {"QSR_EVIDENCE_ROOT": root_expression}
                elif "uses" in step and step["uses"].startswith("actions/upload-artifact@"):
                    step["with"] = {
                        "name": filename.removesuffix(".json") + "-json-" + CANDIDATE
                        + "-${{ github.run_id }}-${{ github.run_attempt }}",
                        "path": root_expression + "/" + filename + "\n"
                        + root_expression + "/binding.json\n",
                        "if-no-files-found": "error",
                    }
                elif "scripts/check_coverage.py" in step.get("run", ""):
                    step["run"] = step["run"].replace(
                        filename, '"$QSR_EVIDENCE_ROOT/' + filename + '"'
                    )
                    step["env"] = {"QSR_EVIDENCE_ROOT": root_expression}
            upload_index = next(i for i, s in enumerate(expected_steps)
                                if s.get("uses", "").startswith("actions/upload-artifact@"))
            expected_steps.insert(upload_index, {
                "name": "Admit fresh bound coverage evidence before upload",
                "env": {"QSR_EVIDENCE_ROOT": root_expression}, "run": guard_hash,
            })
            observed_steps = deepcopy(steps)
            for step in observed_steps:
                if step.get("name") in (
                    generator_name, "Admit fresh bound coverage evidence before upload"
                ):
                    step["run"] = hashlib.sha256(step["run"].encode("utf-8")).hexdigest()
            # Compare actual projections, not original objects substituted for actual steps.
            assert observed_steps == expected_steps, name
        elif name == "podman-e2e-positive-lsm":
            # Only the exact-test witness and the known cleanup bug differ.
            assert len(steps) == len(expected["steps"])
            assert steps[0:3] == expected["steps"][0:3], name
            assert steps[3]["name"] == expected["steps"][3]["name"]
            test_positive_lsm_exact_filter_requires_one_passing_test_witness()
            assert steps[4]["name"] == expected["steps"][-1]["name"]
            assert steps[4]["if"] == "always()"
            assert steps[4]["run"].startswith(
                expected["steps"][-1]["run"].split("leaked_networks=", 1)[0]
            )
        else:
            assert steps == expected["steps"], name
        if name not in SRC03_LANES:
            assert job.get("env", {}) == expected["env"], name


CANDIDATE = "${{ github.event.pull_request.head.sha || github.sha }}"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def test_caller_and_event_are_checked_before_any_source_checkout():
    """Reject a wrong caller or event before the runner reads repository bytes."""
    expected = {
        "name": "Verify caller and event before checkout",
        "env": {
            "CALLER_REPOSITORY": "${{ github.repository }}",
            "EVENT_NAME": "${{ github.event_name }}",
            "PR_HEAD_REPOSITORY": "${{ github.event.pull_request.head.repo.full_name || '' }}",
            "PR_HEAD_SHA": "${{ github.event.pull_request.head.sha || '' }}",
            "PUSH_SHA": "${{ github.sha }}",
            "EXPECTED_HEAD_SHA": CANDIDATE,
        },
    }
    for name in RETAINED_JOB_NAMES:
        job = workflow()["jobs"][name]
        assert job["steps"][0].get("name") == expected["name"], name
        assert job["steps"][0]["env"] == expected["env"], name
        script = job["steps"][0]["run"]
        assert "ContextualWisdomLab/quarantine-sandbox-runtime" in script, name
        assert "pull_request_target" not in script, name
        assert 'test "$EXPECTED_HEAD_SHA" = "$PR_HEAD_SHA"' in script, name
        assert 'test "$EXPECTED_HEAD_SHA" = "$PUSH_SHA"' in script, name
        assert job["steps"][1] == {
            "uses": CHECKOUT,
            "with": {"ref": CANDIDATE, "persist-credentials": "false"},
        }, f"{name} needs exact checkout after admission"
        assert job["steps"][2]["name"] == "Verify exact checkout", name


def test_exact_event_candidate_is_checked_before_any_source_execution():
    """Do not accept caller-selected SHAs or execute code before checking HEAD."""
    for name in RETAINED_JOB_NAMES:
        job = workflow()["jobs"][name]
        assert job["steps"][2] == {
            "name": "Verify exact checkout",
            "env": {"EXPECTED_HEAD_SHA": CANDIDATE},
            "run": 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"',
        }, f"{name} needs fail-closed HEAD verification"


def test_actual_per_job_precheckout_guards_reject_invalid_contexts():
    """Execute all four trusted guards with positive and denied event tuples."""
    repo = "ContextualWisdomLab/quarantine-sandbox-runtime"
    sha = "5bb62ab87da489b52ac7a62096f6315b518d837d"
    cases = [
        (repo, "push", "", sha, 0),
        (repo, "pull_request", repo, sha, 0),
        (repo, "pull_request", "foreign/fork", sha, 1),
        ("foreign/repo", "push", "", sha, 1),
        (repo, "pull_request_target", repo, sha, 1),
        (repo, "workflow_dispatch", "", sha, 1),
        (repo, "repository_dispatch", "", sha, 1),
        (repo, "", "", sha, 1),
        (repo, "push", "", "", 1),
        (repo, "push", "", "main", 1),
        (repo, "push", "", "a" * 39, 1),
        (repo, "push", "", "a" * 41, 1),
        (repo, "push", "", "A" * 40, 1),
        (repo, "push", "", sha + "\n", 1),
    ]
    for name in RETAINED_JOB_NAMES:
        script = workflow()["jobs"][name]["steps"][0]["run"]
        for caller, event, head, candidate, code in cases:
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script],
                env={
                    "PATH": os.defpath,
                    "CALLER_REPOSITORY": caller,
                    "EVENT_NAME": event,
                    "PR_HEAD_REPOSITORY": head,
                    "PR_HEAD_SHA": candidate if event == "pull_request" else "",
                    "PUSH_SHA": candidate if event == "push" else sha,
                    "EXPECTED_HEAD_SHA": candidate,
                },
                capture_output=True,
                check=False,
                timeout=10,
            )
            assert result.returncode == code, (name, caller, event, head, candidate)


def test_missing_raw_pr_head_cannot_use_valid_push_sha_fallback():
    """Reject missing raw PR heads even when the effective fallback SHA is valid."""
    repo = "ContextualWisdomLab/quarantine-sandbox-runtime"
    sha = "5bb62ab87da489b52ac7a62096f6315b518d837d"
    other = "a" * 40
    cases = [
        ("pull_request", None, sha, sha, 1),
        ("pull_request", "", sha, sha, 1),
        ("pull_request", other, sha, sha, 1),
        ("pull_request", "a" * 39, sha, sha, 1),
        ("pull_request", "a" * 41, sha, sha, 1),
        ("pull_request", "A" * 40, sha, sha, 1),
        ("pull_request", sha + "\n", sha, sha, 1),
        ("pull_request", "A" * 40, sha, "A" * 40, 1),
        ("pull_request", "a" * 39, sha, "a" * 39, 1),
        ("pull_request", "a" * 41, sha, "a" * 41, 1),
        ("pull_request", sha + "\n", sha, sha + "\n", 1),
        ("pull_request", sha, other, sha, 0),
        ("push", sha, None, sha, 1),
        ("push", sha, "", sha, 1),
        ("push", sha, other, sha, 1),
        ("push", other, sha, sha, 0),
    ]
    for name in RETAINED_JOB_NAMES:
        script = workflow()["jobs"][name]["steps"][0]["run"]
        for event, pr_sha, push_sha, effective, expected in cases:
            env = {
                "PATH": os.defpath,
                "CALLER_REPOSITORY": repo,
                "EVENT_NAME": event,
                "PR_HEAD_REPOSITORY": repo,
                "EXPECTED_HEAD_SHA": effective,
            }
            if pr_sha is not None:
                env["PR_HEAD_SHA"] = pr_sha
            if push_sha is not None:
                env["PUSH_SHA"] = push_sha
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script],
                env=env,
                capture_output=True,
                check=False,
                timeout=10,
            )
            assert result.returncode == expected, (name, event, pr_sha, push_sha)


def test_admission_job_rejects_unsupported_callers_before_product_checkout():
    """Rejected callers must fail instead of making every required lane skip green."""
    jobs = workflow()["jobs"]
    assert "admission" in jobs, "explicit failed admission is missing"
    admission = jobs["admission"]
    assert "if" not in admission
    assert admission["runs-on"] == {
        "group": "CWL QSR hostile workload",
        "labels": ["self-hosted", "linux", "x64", "cwl-hostile-workload"],
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
        labels = ["self-hosted", "linux", "x64", "cwl-hostile-workload"]
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


SRC03_LANES = {
    "coverage": ("Generate production coverage evidence", "coverage.json"),
    "branch-coverage": ("Generate branch coverage evidence", "branch-coverage.json"),
}


def src03_boundary(tmp_path, lane, mode):
    """Replay the real YAML producer-to-upload boundary with a reached witness."""
    source = tmp_path / "source"
    tools = tmp_path / "tools"
    runner = tmp_path / "runner temp"
    for directory in (source, tools, runner):
        directory.mkdir()
    head = "a" * 40
    root = runner / f"qsr-evidence-17-2-{lane}-{head}"
    foreign = tmp_path / "foreign.json"
    foreign.write_text('{"fixture":"foreign bytes"}\n', encoding="utf-8")
    capture = tmp_path / "producer.json"
    producer = tools / "cargo"
    producer.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        "args=sys.argv[1:]\n"
        "if 'report' in args: raise SystemExit(0)\n"
        f"expected={(['+nightly-2026-07-01'] if lane == 'branch-coverage' else []) + ['llvm-cov'] + (['--branch'] if lane == 'branch-coverage' else []) + ['--workspace', '--lib', '--tests', '--json', '--output-path']!r}\n"
        "if args[:-1]!=expected: raise SystemExit(64)\n"
        "out=pathlib.Path(args[args.index('--output-path')+1])\n"
        "pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps(args))\n"
        "mode=os.environ['MODE']\n"
        "if mode=='producer_failure': raise SystemExit(42)\n"
        "if mode=='no_output': raise SystemExit(0)\n"
        "if mode=='symlink':\n"
        "    out.symlink_to(os.environ['FOREIGN'])\n"
        "elif mode=='directory': out.mkdir()\n"
        "elif mode=='fifo': os.mkfifo(out)\n"
        "elif mode=='hardlink': os.link(os.environ['FOREIGN'],out)\n"
        "else: out.write_text('' if mode=='empty' else '{\"fixture\":\"fresh bytes\"}\\n')\n",
        encoding="utf-8",
    )
    producer.chmod(0o700)
    (tools / "python3").symlink_to(sys.executable)
    git = tools / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$ACTUAL_HEAD"\n', encoding="utf-8")
    git.chmod(0o700)
    context = {
        "${{ runner.temp }}": str(runner),
        "${{ github.run_id }}": "17",
        "${{ github.run_attempt }}": "2",
        "${{ github.event.pull_request.head.sha || github.sha }}": head,
    }
    job = workflow()["jobs"][lane]

    def render(value):
        """Render only the real fixture contexts present in the parsed YAML."""
        for expression, replacement in context.items():
            value = value.replace(expression, replacement)
        assert "${{" not in value, "unrendered real YAML environment"
        return value

    env = {
        "PATH": str(tools) + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(runner),
        "ACTUAL_HEAD": head,
        "FOREIGN": str(foreign),
        "CAPTURE": str(capture),
        "MODE": mode,
    }
    for key, value in job.get("env", {}).items():
        env[key] = render(value)
    name, _ = SRC03_LANES[lane]
    steps = job["steps"]
    if mode == "stale_root":
        root.mkdir()
        (root / SRC03_LANES[lane][1]).write_text("stale sentinel", encoding="utf-8")
    elif mode == "root_symlink":
        root.symlink_to(source, target_is_directory=True)
    start = next(i for i, step in enumerate(steps) if step.get("name") == name)
    boundary = next(
        i
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    results = []
    for step in steps[start:boundary]:
        # Product coverage policy is unchanged and has its own parser suite.
        if "scripts/check_coverage.py" in step.get("run", ""):
            continue
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=source,
            env={
                **env,
                **{key: render(value) for key, value in step.get("env", {}).items()},
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        results.append(result)
        if result.returncode:
            break
    return results, capture, foreign, root


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_legitimate_current_producer_reaches_boundary(tmp_path, lane):
    """A genuine nonempty regular output must reach the synthetic upload boundary."""
    results, capture, _, _ = src03_boundary(tmp_path, lane, "regular")
    assert capture.is_file(), "producer injection did not reach Cargo"
    assert all(result.returncode == 0 for result in results), results[-1].stderr


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_successful_producer_symlink_is_rejected_before_upload(tmp_path, lane):
    """Zero-exit generation must not admit a symlink to foreign evidence bytes."""
    results, capture, foreign, _ = src03_boundary(tmp_path, lane, "symlink")
    assert capture.is_file(), "producer injection did not reach Cargo"
    assert foreign.read_text(encoding="utf-8") == '{"fixture":"foreign bytes"}\n'
    assert results[-1].returncode != 0, (
        "SRC03-EVIDENCE-001: successful producer admitted a symlink at upload boundary"
    )


@pytest.mark.parametrize("lane", SRC03_LANES)
@pytest.mark.parametrize(
    "mode",
    (
        "empty",
        "no_output",
        "directory",
        "fifo",
        "hardlink",
        "producer_failure",
        "stale_root",
        "root_symlink",
    ),
)
def test_src03_rejects_invalid_outputs_and_preserves_foreign_nodes(
    tmp_path, lane, mode
):
    """Fresh production cannot adopt old nodes, empty output or failed generation."""
    results, capture, foreign, root = src03_boundary(tmp_path, lane, mode)
    assert results[-1].returncode != 0, (lane, mode)
    if mode in ("stale_root", "root_symlink"):
        assert not capture.exists(), "stale root reached producer"
        if mode == "stale_root":
            assert (root / SRC03_LANES[lane][1]).read_text() == "stale sentinel"
        else:
            assert root.is_symlink()
    else:
        assert capture.is_file(), "injection did not reach producer"
    if mode == "producer_failure":
        assert results[-1].returncode == 42
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


@pytest.mark.parametrize("lane", SRC03_LANES)
@pytest.mark.parametrize(
    "mutation",
    (
        "run",
        "attempt",
        "head",
        "job",
        "hash",
        "bytes",
        "producer",
        "extra",
        "duplicate",
        "empty",
        "symlink",
        "hardlink",
        "root_symlink",
        "boolean_exit",
        "head_drift",
    ),
)
def test_src03_consumer_revalidates_binding_and_bytes(tmp_path, lane, mutation):
    """Execute the actual pre-upload guard against post-producer drift."""
    import json

    results, _, foreign, root = src03_boundary(tmp_path, lane, "regular")
    assert all(result.returncode == 0 for result in results)
    binding = root / "binding.json"
    receipt = json.loads(binding.read_text())
    artifact = root / SRC03_LANES[lane][1]
    if mutation in ("run", "attempt", "head", "job"):
        key = {
            "run": "QSR_RUN_ID",
            "attempt": "QSR_RUN_ATTEMPT",
            "head": "QSR_EXPECTED_HEAD",
            "job": "QSR_EVIDENCE_JOB",
        }[mutation]
        receipt[key] = "different"
    elif mutation == "hash":
        artifact.write_text("mutated evidence")
    elif mutation == "bytes":
        receipt["bytes"] += 1
    elif mutation == "producer":
        receipt["producer_exit"] = 42
    elif mutation == "boolean_exit":
        receipt["producer_exit"] = False
    elif mutation == "extra":
        receipt["unknown"] = "field"
    elif mutation in ("empty", "symlink", "hardlink"):
        artifact.unlink()
        if mutation == "empty":
            artifact.touch()
        elif mutation == "symlink":
            artifact.symlink_to(foreign)
        else:
            os.link(foreign, artifact)
    elif mutation == "root_symlink":
        saved = root.with_name("saved-root")
        root.rename(saved)
        root.symlink_to(saved, target_is_directory=True)
        binding = saved / "binding.json"
    if mutation == "duplicate":
        binding.write_text(binding.read_text()[:-1] + ',"producer_exit":0}')
    else:
        binding.write_text(json.dumps(receipt))
    script = next(
        step["run"]
        for step in workflow()["jobs"][lane]["steps"]
        if step.get("name") == "Admit fresh bound coverage evidence before upload"
    )
    env = {
        "PATH": str(tmp_path / "tools") + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(tmp_path / "runner temp"),
        "QSR_EVIDENCE_ROOT": str(root),
        "QSR_RUN_ID": "17",
        "QSR_RUN_ATTEMPT": "2",
        "QSR_EVIDENCE_JOB": lane,
        "QSR_EXPECTED_HEAD": "a" * 40,
        "ACTUAL_HEAD": "b" * 40 if mutation == "head_drift" else "a" * 40,
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path / "source",
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0, (lane, mutation)
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


def test_src03_upload_is_run_bound_and_preceded_by_admission():
    """Preserve failure suppression and connect exact evidence paths to upload."""
    for lane, (name, filename) in SRC03_LANES.items():
        job = workflow()["jobs"][lane]
        env = job["env"]
        assert env["QSR_RUN_ID"] == "${{ github.run_id }}"
        assert env["QSR_RUN_ATTEMPT"] == "${{ github.run_attempt }}"
        assert env["QSR_EVIDENCE_JOB"] == lane
        assert env["QSR_EXPECTED_HEAD"] == CANDIDATE
        root_expression = (
            "${{ runner.temp }}/qsr-evidence-${{ github.run_id }}-${{ github.run_attempt }}-"
            + lane
            + "-"
            + CANDIDATE
        )
        assert set(env) == {
            "QSR_RUN_ID",
            "QSR_RUN_ATTEMPT",
            "QSR_EVIDENCE_JOB",
            "QSR_EXPECTED_HEAD",
        }
        steps = job["steps"]
        upload = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        assert set(upload) == {"name", "uses", "with"}
        assert upload["uses"] == (
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
        )
        assert upload["with"] == {
            "name": filename.removesuffix(".json")
            + "-json-"
            + CANDIDATE
            + "-${{ github.run_id }}-${{ github.run_attempt }}",
            "path": root_expression
            + "/"
            + filename
            + "\n"
            + root_expression
            + "/binding.json\n",
            "if-no-files-found": "error",
        }
        assert (
            steps[steps.index(upload) - 1]["name"]
            == "Admit fresh bound coverage evidence before upload"
        )
        assert set(steps[steps.index(upload) - 1]) == {"name", "run", "env"}
        for step in steps:
            if (
                step.get("name") == name
                or step.get("name")
                == "Admit fresh bound coverage evidence before upload"
                or "scripts/check_coverage.py" in step.get("run", "")
            ):
                assert step["env"] == {"QSR_EVIDENCE_ROOT": root_expression}
        parser = next(
            step for step in steps if "scripts/check_coverage.py" in step.get("run", "")
        )
        flag = "--require-branches " if lane == "branch-coverage" else ""
        assert (
            parser["run"]
            == "python3 scripts/check_coverage.py "
            + flag
            + '"$QSR_EVIDENCE_ROOT/'
            + filename
            + '"'
        )
        assert steps.index(parser) > steps.index(upload)


@pytest.mark.parametrize("lane", SRC03_LANES)
@pytest.mark.parametrize(
    "mutation",
    (
        "mutable_upload", "alternate_upload", "generator_echo", "guard_echo",
        "guard_removed", "guard_if", "generator_if", "guard_env", "step_order",
    ),
)
def test_src03_review_b01_rejects_structural_substitution(monkeypatch, lane, mutation):
    """Persistent independent desired rejection; actual YAML is the control."""
    data = deepcopy(workflow())
    steps = data["jobs"][lane]["steps"]
    generator = next(s for s in steps if s.get("name") == SRC03_LANES[lane][0])
    guard = next(s for s in steps if s.get("name") ==
                 "Admit fresh bound coverage evidence before upload")
    upload = next(s for s in steps if s.get("uses", "").startswith(
        "actions/upload-artifact@"))
    if mutation == "mutable_upload":
        upload["uses"] = "actions/upload-artifact@main"
    elif mutation == "alternate_upload":
        upload["uses"] = "actions/upload-artifact@" + "b" * 40
    elif mutation == "generator_echo":
        generator["run"] = "echo substituted-generator\n"
    elif mutation == "guard_echo":
        guard["run"] = "echo substituted-guard\n"
    elif mutation == "guard_removed":
        steps.remove(guard)
    elif mutation == "guard_if":
        guard["if"] = "false"
    elif mutation == "generator_if":
        generator["if"] = "false"
    elif mutation == "guard_env":
        guard["env"]["QSR_EVIDENCE_ROOT"] = "alternate"
    else:
        index = steps.index(generator)
        steps[index - 1], steps[index] = steps[index], steps[index - 1]
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    with pytest.raises(AssertionError):
        test_preserves_all_four_job_mechanics()


def test_src03_review_b01_accepts_legitimate_literal_control():
    """The complete retained mechanics must remain accepted."""
    test_preserves_all_four_job_mechanics()


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_review_b02_producer_without_file_digest(tmp_path, monkeypatch, lane):
    """Synthetic child capability seam, NOT actual runner/minimum-version evidence."""
    import json

    data = deepcopy(workflow())
    producer = next(s for s in data["jobs"][lane]["steps"]
                    if s.get("name") == SRC03_LANES[lane][0])
    prefix = "python3 -I - <<'PY'\n"
    assert producer["run"].startswith(prefix)
    producer["run"] = producer["run"].replace(
        prefix, prefix + "import hashlib\n"
        "if hasattr(hashlib, 'file_digest'):\n    del hashlib.file_digest\n", 1
    )
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    results, capture, foreign, root = src03_boundary(tmp_path, lane, "regular")
    assert capture.is_file(), "capability seam did not reach actual producer"
    assert all(r.returncode == 0 for r in results), results[-1].stderr
    payload = (root / SRC03_LANES[lane][1]).read_bytes()
    receipt = json.loads((root / "binding.json").read_bytes())
    assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["bytes"] == len(payload)
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


def src03_review_inject(script, code):
    """Add an explicit child-only stdlib seam to real embedded Python."""
    prefix = "python3 -I - <<'PY'\n"
    assert script.startswith(prefix)
    return script.replace(prefix, prefix + code + "\n", 1)


def src03_review_guard(tmp_path, lane, root, script=None):
    """Execute actual guard with the closed legitimate fixture context."""
    if script is None:
        script = next(s["run"] for s in workflow()["jobs"][lane]["steps"]
                      if s.get("name") == "Admit fresh bound coverage evidence before upload")
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path / "source",
        env={
            "PATH": str(tmp_path / "tools") + os.pathsep + os.defpath,
            "RUNNER_TEMP": str(tmp_path / "runner temp"),
            "QSR_EVIDENCE_ROOT": str(root), "QSR_RUN_ID": "17",
            "QSR_RUN_ATTEMPT": "2", "QSR_EVIDENCE_JOB": lane,
            "QSR_EXPECTED_HEAD": "a" * 40, "ACTUAL_HEAD": "a" * 40,
        },
        capture_output=True, text=True, timeout=10, check=False,
    )


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_review_r03_manifest_reader_refuses_oversize(tmp_path, lane):
    """Valid closed binding plus whitespace cannot evade the byte bound."""
    results, _, foreign, root = src03_boundary(tmp_path, lane, "regular")
    assert all(r.returncode == 0 for r in results)
    binding = root / "binding.json"
    assert 0 < binding.stat().st_size < 4096
    binding.write_bytes(binding.read_bytes() + b" " * 4096)
    result = src03_review_guard(tmp_path, lane, root)
    assert result.returncode != 0, "oversized manifest reached upload boundary"
    assert "manifest too large" in result.stderr
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_review_r03_generator_refuses_oversized_serialization(
    tmp_path, monkeypatch, lane
):
    """Synthetic child serialization seam; refuse before publication."""
    data = deepcopy(workflow())
    generator = next(s for s in data["jobs"][lane]["steps"]
                     if s.get("name") == SRC03_LANES[lane][0])
    generator["run"] = src03_review_inject(generator["run"],
        "import json\n"
        "original_dumps = json.dumps\n"
        "def inflated_dumps(value, *args, **kwargs):\n"
        "    return original_dumps(value, *args, **kwargs) + ' ' * 4096\n"
        "def inflated_dump(value, handle, *args, **kwargs):\n"
        "    handle.write(inflated_dumps(value, *args, **kwargs))\n"
        "json.dumps = inflated_dumps\njson.dump = inflated_dump\n")
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    results, capture, foreign, root = src03_boundary(tmp_path, lane, "regular")
    assert capture.is_file(), "serialization seam did not reach producer"
    assert results[0].returncode != 0, "producer published oversized binding"
    assert "manifest too large" in results[0].stderr
    assert not (root / "binding.json").exists()
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


@pytest.mark.parametrize("lane", SRC03_LANES)
@pytest.mark.parametrize("underreported", (False, True))
def test_src03_review_r03_manifest_read_call_is_bounded(tmp_path, lane, underreported):
    """Actual guard read-call seam, including a misleading size observation."""
    results, _, _, root = src03_boundary(tmp_path, lane, "regular")
    assert all(r.returncode == 0 for r in results)
    if underreported:
        binding = root / "binding.json"
        binding.write_bytes(binding.read_bytes() + b" " * 4096)
    code = '''import os
original_open, original_fdopen, original_fstat = os.open, os.fdopen, os.fstat
manifest_fds = set()
def probe_open(path, *args, **kwargs):
    fd = original_open(path, *args, **kwargs)
    if str(path).endswith('/binding.json'):
        manifest_fds.add(fd)
    return fd
class Probe:
    def __init__(self, handle): self.handle = handle
    def __enter__(self): return self
    def __exit__(self, *args):
        manifest_fds.discard(self.fileno())
        return self.handle.__exit__(*args)
    def fileno(self): return self.handle.fileno()
    def read(self, size=-1):
        if self.fileno() in manifest_fds:
            assert 0 < size <= 4097, 'unbounded manifest read'
        return self.handle.read(size)
def probe_fdopen(*args, **kwargs): return Probe(original_fdopen(*args, **kwargs))
os.open, os.fdopen = probe_open, probe_fdopen
'''
    if underreported:
        code += '''def probe_fstat(fd):
    info = original_fstat(fd)
    if fd in manifest_fds:
        fields = list(info)
        fields[6] = 1
        return os.stat_result(fields)
    return info
os.fstat = probe_fstat
'''
    script = next(s["run"] for s in workflow()["jobs"][lane]["steps"]
                  if s.get("name") == "Admit fresh bound coverage evidence before upload")
    result = src03_review_guard(tmp_path, lane, root, src03_review_inject(script, code))
    assert "unbounded manifest read" not in result.stderr, result.stderr
    if underreported:
        assert result.returncode != 0
        assert "manifest too large" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def src03_review_stream_seam(action="regular"):
    """Large real file and observed bounded reads; controlled drift, not hostile race."""
    return '''import os, subprocess, sys
original_run = subprocess.run
original_open, original_fdopen = os.open, os.fdopen
payload_fds = {}
reads = 0
changed = False
def large_producer(command, *args, **kwargs):
    result = original_run(command, *args, **kwargs)
    if '--output-path' in command and result.returncode == 0:
        path = command[command.index('--output-path') + 1]
        with open(path, 'wb') as output:
            for _ in range(33): output.write(b'x' * 65536)
    return result
subprocess.run = large_producer
def probe_open(path, *args, **kwargs):
    fd = original_open(path, *args, **kwargs)
    if str(path).endswith('/coverage.json') or str(path).endswith('/branch-coverage.json'):
        payload_fds[fd] = path
    return fd
class Probe:
    def __init__(self, handle): self.handle = handle
    def __enter__(self): return self
    def __exit__(self, *args):
        payload_fds.pop(self.fileno(), None)
        return self.handle.__exit__(*args)
    def fileno(self): return self.handle.fileno()
    def read(self, size=-1):
        global reads, changed
        fd = self.fileno()
        if fd in payload_fds:
            assert 0 < size <= 65536, 'unbounded payload read'
            reads += 1
        data = self.handle.read(size)
        if fd in payload_fds and not changed and ACTION != 'regular':
            changed = True
            writer = original_open(payload_fds[fd], os.O_WRONLY)
            try:
                if ACTION == 'grow':
                    os.lseek(writer, 0, os.SEEK_END)
                    os.write(writer, b'x')
                else:
                    os.ftruncate(writer, 1)
            finally:
                os.close(writer)
        return data
os.open, os.fdopen = probe_open, lambda *a, **k: Probe(original_fdopen(*a, **k))
import atexit
atexit.register(lambda: print('SRC03-STREAM-READS=' + str(reads), file=sys.stderr))
'''.replace("ACTION", repr(action))


@pytest.mark.parametrize("lane", SRC03_LANES)
def test_src03_review_r03_streams_large_regular_payload(tmp_path, monkeypatch, lane):
    """Both actual bodies hash a 2MiB+ regular file with bounded multiple reads."""
    import json
    import re

    data = deepcopy(workflow())
    for step in data["jobs"][lane]["steps"]:
        if step.get("name") in (SRC03_LANES[lane][0],
                                "Admit fresh bound coverage evidence before upload"):
            step["run"] = src03_review_inject(step["run"], src03_review_stream_seam())
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    results, capture, foreign, root = src03_boundary(tmp_path, lane, "regular")
    assert capture.is_file()
    assert all(r.returncode == 0 for r in results), results[-1].stderr
    observed = [int(re.search(r"SRC03-STREAM-READS=(\d+)", r.stderr)[1])
                for r in results if "SRC03-STREAM-READS=" in r.stderr]
    assert len(observed) == 2 and all(n > 32 for n in observed), observed
    receipt = json.loads((root / "binding.json").read_bytes())
    assert receipt["bytes"] == 33 * 65536
    assert receipt["sha256"] == hashlib.sha256(b"x" * (33 * 65536)).hexdigest()
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'


@pytest.mark.parametrize("lane", SRC03_LANES)
@pytest.mark.parametrize("role", ("producer", "guard"))
@pytest.mark.parametrize("action", ("grow", "truncate"))
def test_src03_review_r03_rejects_counted_payload_drift(
    tmp_path, monkeypatch, lane, role, action
):
    """Actual descriptor reads detect controlled size changes before/after hashing."""
    data = deepcopy(workflow())
    name = SRC03_LANES[lane][0] if role == "producer" else (
        "Admit fresh bound coverage evidence before upload")
    step = next(s for s in data["jobs"][lane]["steps"] if s.get("name") == name)
    step["run"] = src03_review_inject(step["run"], src03_review_stream_seam(action))
    monkeypatch.setitem(globals(), "workflow", lambda: data)
    results, capture, foreign, _ = src03_boundary(tmp_path, lane, "regular")
    assert capture.is_file()
    result = results[0] if role == "producer" else results[-1]
    assert result.returncode != 0, "size drift accepted"
    assert "evidence changed while reading" in result.stderr, result.stderr
    assert foreign.read_text() == '{"fixture":"foreign bytes"}\n'
