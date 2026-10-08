"""Offline contracts for the staged BandScope Linux reusable producer.

Execute the exact parsed YAML admission shell, never BandScope build hooks or
runner APIs. Synthetic event environments are unit fixtures, not attestation.
"""

from pathlib import Path
import os
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/bandscope-ci.yml"


def workflow():
    """Parse GitHub's on key without YAML 1.1's boolean coercion."""
    assert WORKFLOW.is_file(), "BandScope reusable producer is absent"
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_producer_is_call_only_read_only_and_has_one_required_gate():
    """An additive producer cannot trigger itself or accept arbitrary commands."""
    data = workflow()
    assert set(data["on"]) == {"workflow_call"}
    call = data["on"]["workflow_call"]
    assert set(call) == {"inputs"}
    assert set(call["inputs"]) == {"gate"}
    gate = call["inputs"]["gate"]
    assert gate["type"] == "string"
    assert gate["required"] is True
    assert "default" not in gate
    assert data["permissions"] == {"contents": "read"}


def admission():
    """Return the first step, which must reject contexts before checkout."""
    step = workflow()["jobs"]["linux"]["steps"][0]
    assert step["name"] == "Admit fixed BandScope Linux gate"
    assert step["shell"] == "bash"
    assert step["working-directory"] == "${{ github.workspace }}"
    assert "${{" not in step["run"]
    assert step["env"] == {
        "CALLER_REPOSITORY": "${{ github.repository }}",
        "CALLER_EVENT": "${{ github.event_name }}",
        "CALLER_REF": "${{ github.ref }}",
        "CALLER_SHA": "${{ github.sha }}",
        "PR_HEAD_REPOSITORY": "${{ github.event.pull_request.head.repo.full_name }}",
        "PR_BASE_REPOSITORY": "${{ github.event.pull_request.base.repo.full_name }}",
        "PR_BASE_REF": "${{ github.event.pull_request.base.ref }}",
        "PR_NUMBER": "${{ github.event.pull_request.number }}",
        "SELECTED_GATE": "${{ inputs.gate }}",
    }
    return step["run"]


def run_admission(tmp_path, **changes):
    """Run exact YAML bash in a bounded synthetic event environment."""
    env = {
        "PATH": os.environ["PATH"],
        "CALLER_REPOSITORY": "ContextualWisdomLab/bandscope",
        "CALLER_EVENT": "push",
        "CALLER_REF": "refs/heads/main",
        "CALLER_SHA": "a" * 40,
        "PR_HEAD_REPOSITORY": "",
        "PR_BASE_REPOSITORY": "",
        "PR_BASE_REF": "",
        "PR_NUMBER": "",
        "SELECTED_GATE": "lock-validation",
    }
    env.update(changes)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", admission()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("gate", ["lock-validation", "verify"])
@pytest.mark.parametrize("branch", ["main", "develop"])
def test_admission_accepts_fixed_push_and_gate(tmp_path, gate, branch):
    """Both exact gates accept only the two named push branches."""
    result = run_admission(
        tmp_path, SELECTED_GATE=gate, CALLER_REF=f"refs/heads/{branch}"
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("gate", ["lock-validation", "verify"])
@pytest.mark.parametrize("base", ["main", "develop"])
def test_admission_accepts_same_repository_pr_merge_context(tmp_path, gate, base):
    """PRs retain merge-SHA semantics rather than checking out mutable head refs."""
    result = run_admission(
        tmp_path,
        SELECTED_GATE=gate,
        CALLER_EVENT="pull_request",
        CALLER_REF="refs/pull/42/merge",
        PR_NUMBER="42",
        PR_BASE_REF=base,
        PR_HEAD_REPOSITORY="ContextualWisdomLab/bandscope",
        PR_BASE_REPOSITORY="ContextualWisdomLab/bandscope",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "changes",
    [
        {"SELECTED_GATE": ""},
        {"SELECTED_GATE": "anything"},
        {"SELECTED_GATE": "verify; touch injected"},
        {"SELECTED_GATE": "$(touch injected)"},
        {"SELECTED_GATE": "verify\n touch injected"},
        {"CALLER_REPOSITORY": "attacker/bandscope"},
        {"CALLER_REPOSITORY": "ContextualWisdomLab/BandScope"},
        {"CALLER_REPOSITORY": ""},
        {"CALLER_REPOSITORY": "$(touch injected)"},
        {"CALLER_EVENT": "pull_request_target"},
        {"CALLER_EVENT": "workflow_dispatch"},
        {"CALLER_EVENT": "schedule"},
        {"CALLER_EVENT": "workflow_call"},
        {"CALLER_EVENT": ""},
        {"CALLER_REF": "refs/heads/feature/attack"},
        {"CALLER_REF": "refs/tags/main"},
        {"CALLER_REF": "refs/heads/main; touch injected"},
        {"CALLER_SHA": ""},
        {"CALLER_SHA": "a" * 39},
        {"CALLER_SHA": "a" * 41},
        {"CALLER_SHA": "G" * 40},
        {"CALLER_SHA": "$(touch injected)"},
        {
            "CALLER_EVENT": "pull_request",
            "CALLER_REF": "refs/pull/42/merge",
            "PR_NUMBER": "42",
            "PR_BASE_REF": "main",
            "PR_HEAD_REPOSITORY": "attacker/bandscope",
            "PR_BASE_REPOSITORY": "ContextualWisdomLab/bandscope",
        },
        {
            "CALLER_EVENT": "pull_request",
            "CALLER_REF": "refs/pull/42/merge",
            "PR_NUMBER": "42",
            "PR_BASE_REF": "main",
            "PR_HEAD_REPOSITORY": "ContextualWisdomLab/bandscope",
            "PR_BASE_REPOSITORY": "attacker/bandscope",
        },
        {
            "CALLER_EVENT": "pull_request",
            "CALLER_REF": "refs/pull/42/merge",
            "PR_NUMBER": "42",
            "PR_BASE_REF": "feature/unsafe",
            "PR_HEAD_REPOSITORY": "ContextualWisdomLab/bandscope",
            "PR_BASE_REPOSITORY": "ContextualWisdomLab/bandscope",
        },
        {
            "CALLER_EVENT": "pull_request",
            "CALLER_REF": "refs/pull/42/head",
            "PR_NUMBER": "42",
            "PR_BASE_REF": "main",
            "PR_HEAD_REPOSITORY": "ContextualWisdomLab/bandscope",
            "PR_BASE_REPOSITORY": "ContextualWisdomLab/bandscope",
        },
        {
            "CALLER_EVENT": "pull_request",
            "CALLER_REF": "refs/pull/42/merge",
            "PR_NUMBER": "43",
            "PR_BASE_REF": "main",
            "PR_HEAD_REPOSITORY": "ContextualWisdomLab/bandscope",
            "PR_BASE_REPOSITORY": "ContextualWisdomLab/bandscope",
        },
        {
            "CALLER_EVENT": "pull_request",
            "PR_BASE_REF": "main",
            "PR_HEAD_REPOSITORY": "",
            "PR_BASE_REPOSITORY": "ContextualWisdomLab/bandscope",
        },
    ],
)
def test_admission_fails_closed_without_shell_injection(tmp_path, changes):
    """Untrusted env values never become commands, success, or leaked diagnostics."""
    result = run_admission(tmp_path, **changes)
    assert result.returncode != 0
    assert "BandScope admission rejected" in result.stderr
    assert not (tmp_path / "injected").exists()
    for value in changes.values():
        if len(value) > 10:
            assert value not in result.stdout + result.stderr


def test_routing_and_prelease_filter_are_fixed_not_gate_skipping():
    """The job-level filter is defense-in-depth, not evidence of runner admission."""
    data = workflow()
    assert set(data["jobs"]) == {"linux"}
    job = data["jobs"]["linux"]
    assert job["runs-on"] == {
        "group": "CWL CI isolated",
        "labels": ["self-hosted", "Linux", "X64", "cwlab-ci-isolated", "bandscope-ci"],
    }
    predicate = " ".join(job["if"].split())
    assert predicate == (
        "${{ github.repository == 'ContextualWisdomLab/bandscope' && "
        "((github.event_name == 'push' && (github.ref == 'refs/heads/main' || "
        "github.ref == 'refs/heads/develop')) || (github.event_name == 'pull_request' && "
        "github.event.pull_request.head.repo.full_name == 'ContextualWisdomLab/bandscope' && "
        "github.event.pull_request.base.repo.full_name == 'ContextualWisdomLab/bandscope' && "
        "(github.event.pull_request.base.ref == 'main' || "
        "github.event.pull_request.base.ref == 'develop'))) }}"
    )
    assert "inputs.gate" not in predicate  # Unknown input must fail, not skip green.
    assert (
        data["concurrency"]["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    )
    group = data["concurrency"]["group"]
    assert "github.repository" in group and "github.event.pull_request.number" in group
    assert "github.sha" not in group and "inputs.gate" in group


CHECKOUT = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
NODE = "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"
UV = "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990"
VERIFY_ONLY = "${{ inputs.gate == 'verify' }}"
LOCK_ONLY = "${{ inputs.gate == 'lock-validation' }}"


def test_fixed_commands_versions_checkout_and_step_sequence():
    """Mirror source Linux commands and pins, except fresh numeric wheel output."""
    data = workflow()
    job = data["jobs"]["linux"]
    assert job["defaults"] == {
        "run": {"shell": "bash", "working-directory": "bandscope-source"}
    }
    assert data["env"] == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "init.defaultBranch",
        "GIT_CONFIG_VALUE_0": "develop",
        "EXPECTED_NPM_VERSION": "10.9.9",
    }
    steps = job["steps"]
    assert [step["name"] for step in steps] == [
        "Admit fixed BandScope Linux gate",
        "Checkout BandScope source",
        "Set up pinned Node",
        "Activate pinned npm runtime",
        "Verify exact npm lockfile generator and bundled tar",
        "Validate the frozen package lock without lifecycle execution",
        "Reject manifest or lockfile drift",
        "Set up pinned uv",
        "Install node dependencies",
        "Sync Python dependencies",
        "Install stable Rust toolchain",
        "Build and install Rust numeric extension",
        "Run quickcheck",
    ]
    assert steps[1]["uses"] == CHECKOUT
    assert steps[1]["with"] == {
        "repository": "ContextualWisdomLab/bandscope",
        "ref": "${{ github.sha }}",
        "path": "bandscope-source",
        "persist-credentials": False,
        "clean": True,
    }
    assert steps[2]["uses"] == NODE
    assert steps[2]["with"] == {
        "node-version": "22.22.3",
        "package-manager-cache": False,
    }
    assert steps[7]["uses"] == UV
    assert steps[7]["with"] == {"version": "0.8.6", "enable-cache": False}
    expected = {
        3: "corepack enable npm",
        4: 'test "$(npm --version)" = "$EXPECTED_NPM_VERSION"\nnpm run check:npm-runtime\n',
        5: "npm ci --ignore-scripts --no-audit --no-fund",
        6: "git diff --exit-code -- package.json package-lock.json",
        8: "npm ci",
        9: "uv sync --project services/analysis-engine --group dev --frozen",
        10: "rustup toolchain install stable --profile minimal",
        12: "./scripts/harness/quickcheck.sh",
    }
    for index, command in expected.items():
        assert steps[index]["run"] == command
    for index in (5, 6):
        assert steps[index]["if"] == LOCK_ONLY
    for index in range(7, 13):
        assert steps[index]["if"] == VERIFY_ONLY
    for index in (0, 1, 2, 3, 4):
        assert "if" not in steps[index]
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "secrets.",
        "secrets: inherit",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "github.token",
        "continue-on-error",
        "eval ",
        "bash -c",
        "ubuntu-latest",
    ):
        assert forbidden not in text
    assert "permissions" not in job
    assert all("env" not in step for step in steps[1:])
    assert all("${{" not in step["run"] for step in steps if "run" in step)


def numeric_shell():
    """Read the real YAML numeric build script rather than a copied oracle."""
    steps = workflow()["jobs"]["linux"]["steps"]
    matches = [
        step
        for step in steps
        if step["name"] == "Build and install Rust numeric extension"
    ]
    assert len(matches) == 1, "numeric build/install step is absent"
    script = matches[0]["run"]
    assert "uvx maturin@1.9.6 build --release" in script
    assert "--manifest-path services/analysis-engine/rust/Cargo.toml" in script
    assert 'VENV_PY="$PWD/services/analysis-engine/.venv/bin/python"' in script
    assert '--interpreter "$VENV_PY"' in script
    assert '--out "$wheel_dir"' in script
    assert 'uv pip install --python "$VENV_PY" "${wheels[0]}"' in script
    assert "rust/dist" not in script
    assert "${{" not in script
    return script


@pytest.mark.parametrize(
    "mode,expected_exit",
    [
        ("one", 0),
        ("zero", 1),
        ("two", 1),
        ("build-fail", 23),
        ("install-fail", 24),
    ],
)
def test_numeric_shell_owns_fresh_output_cleans_and_preserves_failure(
    tmp_path, mode, expected_exit
):
    """Synthetic tool doubles check temp ownership, not wheel/native correctness."""
    source = tmp_path / "bandscope-source"
    stale = source / "services/analysis-engine/rust/dist"
    stale.mkdir(parents=True)
    stale_wheel = stale / "stale.whl"
    stale_wheel.write_text("DO NOT INSTALL")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    sibling = runner_temp / "peer-output"
    sibling.mkdir()
    (sibling / "keep").write_text("peer")
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "tool-log"
    uvx = tools / "uvx"
    uvx.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
assert args[:4] == ["maturin@1.9.6", "build", "--release", "--manifest-path"]
assert args[4] == "services/analysis-engine/rust/Cargo.toml"
assert args[5:6] == ["--interpreter"]
assert args[6] == str(pathlib.Path.cwd() / "services/analysis-engine/.venv/bin/python")
assert args[7] == "--out"
out = pathlib.Path(args[8])
assert out.is_dir() and not list(out.iterdir())
assert out.parent == pathlib.Path(os.environ["RUNNER_TEMP"])
assert out.name.startswith("bandscope-numeric.")
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write(str(out) + "\\n")
mode = os.environ["TEST_MODE"]
if mode == "build-fail": sys.exit(23)
if mode != "zero": (out / "numeric.whl").write_text("unit fixture, not real wheel")
if mode == "two": (out / "extra.whl").write_text("unit fixture")
""")
    uv = tools / "uv"
    uv.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
assert args[:3] == ["pip", "install", "--python"]
assert args[3] == str(pathlib.Path.cwd() / "services/analysis-engine/.venv/bin/python")
assert len(args) == 5
wheel = pathlib.Path(args[4])
assert wheel.name == "numeric.whl" and wheel.is_file()
assert wheel.parent.parent == pathlib.Path(os.environ["RUNNER_TEMP"])
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write("installed:" + str(wheel) + "\\n")
if os.environ["TEST_MODE"] == "install-fail": sys.exit(24)
""")
    uvx.chmod(0o755)
    uv.chmod(0o755)
    env = {
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEMP": str(runner_temp),
        "TOOL_LOG": str(log),
        "TEST_MODE": mode,
    }
    for _ in range(2):
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", numeric_shell()],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == expected_exit, result.stdout + result.stderr
        assert list(runner_temp.iterdir()) == [sibling]
        assert stale_wheel.read_text() == "DO NOT INSTALL"
        assert (sibling / "keep").read_text() == "peer"
    lines = log.read_text().splitlines()
    outputs = [line for line in lines if not line.startswith("installed:")]
    assert len(outputs) == 2 and len(set(outputs)) == 2
    installs = [line for line in lines if line.startswith("installed:")]
    assert len(installs) == (2 if mode in ("one", "install-fail") else 0)


def test_doctoring_requires_prelease_attestation_and_live_canary_not_fake_success():
    """Staging documentation must not turn unit green into activation approval."""
    path = ROOT / "docs/doctoring/bandscope-central-ci.md"
    assert path.is_file(), "staging and activation security record is absent"
    text = path.read_text(encoding="utf-8")
    for marker in (
        "NO ACTIVATION",
        "#326",
        "#136",
        "caller ACL",
        "staging-not-runnable",
        "Security Notes",
        "pre-lease",
        "in-job",
        "fork",
        "secrets: inherit",
        "synthetic success",
        "live-canary",
        "gate / ci / npm-lock-validation",
        "ci / build-and-test",
        "gate / build / windows",
        "gate / build / macos",
        "CycloneDX JSON",
        "supply-chain/supplemental-component-inventory.json",
        "22.22.3",
        "10.9.9",
        "0.8.6",
        "1.9.6",
        "quickcheck",
        "7554587c2e3106a388998bcad048a3d7121de25e",
        "64211c7d5a9ff4efa1567e0169cef5e7eadb8fbe6e13fd34f3f2748f594caa76",
    ):
        assert marker in text
