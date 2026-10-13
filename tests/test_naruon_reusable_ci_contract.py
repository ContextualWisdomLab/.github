"""TDD contracts for the Naruon central reusable CI suppliers."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


EXPECTED = {
    "backend": WORKFLOWS / "naruon-backend-ci.yml",
    "frontend": WORKFLOWS / "naruon-frontend-ci.yml",
    "bandit": WORKFLOWS / "naruon-bandit-ci.yml",
}
RUNNER = {
    "group": "CWL CI isolated",
    "labels": ["self-hosted", "linux", "x64", "cwlab-ci-isolated"],
}
CHECKOUT_RE = re.compile(r"^actions/checkout@[0-9a-f]{40}$")


def load(name: str) -> dict:
    return yaml.load(EXPECTED[name].read_text(), Loader=yaml.BaseLoader)


def assert_sha_pins(workflow: dict) -> None:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.search(r"@[0-9a-f]{40}(?:\s+#.*)?$", step["uses"])


def test_suppliers_exist_and_are_workflow_call_only() -> None:
    for path in EXPECTED.values():
        assert path.is_file()
    for data in map(load, EXPECTED):
        assert data["on"] == {"workflow_call": ""}
        assert "inputs" not in data["on"]["workflow_call"]
        assert "secrets" not in data["on"]["workflow_call"]
        assert data["permissions"] == {"contents": "read"}
        assert "concurrency" not in data
        assert_sha_pins(data)


@pytest.mark.parametrize("name", EXPECTED)
def test_fixed_isolated_runner_and_no_executable_inputs(name: str) -> None:
    data = load(name)
    for job in data["jobs"].values():
        assert job["runs-on"] == RUNNER
        assert "with" not in job
        assert "secrets" not in job
        assert "strategy" not in job
        assert job["steps"][0]["name"] == "Admit fixed caller before checkout"
        assert "uses" not in job["steps"][0]
        assert job["steps"][0]["shell"] == "bash --noprofile --norc -e -o pipefail {0}"
        checkout = next(step for step in job["steps"] if step.get("name") == "Checkout repository")
        assert CHECKOUT_RE.fullmatch(checkout["uses"])
        assert checkout["with"]["persist-credentials"] == "false"
        assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"


def _admission_script(name: str) -> str:
    return load(name)["jobs"][next(iter(load(name)["jobs"]))]["steps"][0]["run"]


@pytest.mark.parametrize("name", EXPECTED)
@pytest.mark.parametrize(
    "event,repository,head,base,base_ref,ref,expected",
    [
        ("pull_request", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "develop", "refs/pull/1/merge", 0),
        ("pull_request", "ContextualWisdomLab/naruon", "fork/naruon", "ContextualWisdomLab/naruon", "develop", "refs/pull/1/merge", 1),
        ("pull_request", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "release/2026.10", "refs/pull/1/merge", "app-only"),
        ("pull_request", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "feature", "refs/pull/1/merge", 1),
        ("push", "ContextualWisdomLab/naruon", "", "", "", "refs/heads/develop", 0),
        ("push", "ContextualWisdomLab/naruon", "", "", "", "refs/heads/master", 0),
        ("push", "ContextualWisdomLab/naruon", "", "", "", "refs/heads/release/2026.10", 1),
        ("workflow_dispatch", "ContextualWisdomLab/naruon", "", "", "", "refs/heads/develop", "bandit-only"),
        ("workflow_dispatch", "ContextualWisdomLab/naruon", "", "", "", "refs/heads/feature", 1),
        ("pull_request_target", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "ContextualWisdomLab/naruon", "develop", "refs/heads/develop", 1),
        ("push", "ContextualWisdomLab/.github", "", "", "", "refs/heads/develop", 1),
    ],
)
def test_actual_precheckout_admission(name, event, repository, head, base, base_ref, ref, expected):
    step = load(name)["jobs"][next(iter(load(name)["jobs"]))]["steps"][0]
    env = {
        "PATH": "/usr/bin:/bin",
        "CALLER_REPOSITORY": repository,
        "CALLER_EVENT": event,
        "PR_HEAD_REPOSITORY": head,
        "PR_BASE_REPOSITORY": base,
        "PR_BASE_REF": base_ref,
        "CALLER_REF": ref,
    }
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if expected == "app-only":
        expected = int(name == "bandit")
    elif expected == "bandit-only":
        expected = int(name != "bandit")
    assert result.returncode == expected, result.stderr
    assert "fork" not in result.stdout + result.stderr


def _all_run_text(name: str) -> str:
    return "\n".join(step.get("run", "") for job in load(name)["jobs"].values() for step in job["steps"])


def test_backend_preserves_workloads_and_private_venv() -> None:
    text = _all_run_text("backend")
    for command in (
        "python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-hashes.txt",
        "-r backend/requirements-agent.txt",
        "python -m ruff check .",
        "python -m pytest -q 2>&1 | tee pytest_output.log",
        "grep -qiE 'timeout|fatal|warn|denied' pytest_output.log",
    ):
        assert command in text
    assert "python -m venv" in text
    assert "PIP_NO_CACHE_DIR" in text
    assert "HOME=" in text and "TMPDIR=" in text
    assert "trap " in text and " EXIT" in text


def test_frontend_preserves_workloads_and_safe_node_order() -> None:
    data = load("frontend")
    steps = data["jobs"]["frontend"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Enable Corepack pnpm") < names.index("Set up Node.js")
    setup = next(step for step in steps if step.get("name") == "Set up Node.js")
    assert setup["with"]["node-version"] == "24"
    assert setup["with"]["cache"] == "pnpm"
    assert setup["with"]["cache-dependency-path"] == "frontend/pnpm-lock.yaml"
    text = _all_run_text("frontend")
    for command in (
        "pnpm install --frozen-lockfile",
        "pnpm test",
        "pnpm run lint",
        "pnpm run build",
        "pnpm exec playwright install --with-deps chromium",
        "pnpm run full:smoke",
    ):
        assert command in text
    assert 'rm -f ~/package-lock.json' not in text
    assert 'rm -f -- "$HOME/package-lock.json"' in text
    assert "NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE" in text
    assert "NARUON_FULL_PRODUCT_SCREENSHOT_DIR" not in text
    assert data["jobs"]["frontend"]["env"]["NODE_ENV"] == "test"
    build = next(step for step in steps if step.get("name") == "Build frontend")
    assert build["env"]["NODE_ENV"] == "production"


def test_bandit_preserves_sarif_gate_and_private_environment() -> None:
    data = load("bandit")
    job = data["jobs"]["security"]
    assert job["permissions"] == {"contents": "read", "security-events": "write"}
    text = _all_run_text("bandit")
    assert "python -m pip install --disable-pip-version-check --require-hashes -r requirements-bandit-ci-hashes.txt" in text
    assert "bandit -r backend/ -x backend/tests/ -f sarif -o bandit-results.sarif" in text
    upload = next(step for step in job["steps"] if step.get("name") == "Upload SARIF file")
    assert "always()" in upload["if"]
    assert all(not step.get("continue-on-error") for step in job["steps"])
    assert "python -m venv" in text and "HOME=" in text and "TMPDIR=" in text


def test_bandit_upload_requires_successful_admission_but_survives_scan_failure():
    job = load("bandit")["jobs"]["security"]
    assert job["steps"][0]["id"] == "admission"
    upload = next(step for step in job["steps"] if step.get("name") == "Upload SARIF file")
    assert upload["if"] == "${{ always() && steps.admission.outcome == 'success' }}"


def test_guard_precedes_all_checkouts_and_has_no_secrets() -> None:
    for name, path in EXPECTED.items():
        data = load(name)
        for job in data["jobs"].values():
            steps = job["steps"]
            checkout_index = next(i for i, step in enumerate(steps) if "actions/checkout@" in step.get("uses", ""))
            assert checkout_index > 0
            assert steps[0]["name"] == "Admit fixed caller before checkout"
            assert all(not step.get("continue-on-error") for step in steps)
            assert all("secrets." not in str(step) for step in steps)
            assert "secrets." not in path.read_text()


def step_named(name, title):
    return next(s for j in load(name)["jobs"].values() for s in j["steps"] if s.get("name") == title)


def shell(script, cwd, env):
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=10,
    )


def executable(path, text):
    path.write_text("#!/bin/bash\nset -eu\n" + text)
    path.chmod(0o755)


@pytest.mark.parametrize("name,title", [
    ("backend", "Verify backend in a job-private environment"),
    ("bandit", "Run Bandit in a job-private environment"),
])
@pytest.mark.parametrize("failure,output,expected", [
    ("", "clean", 0), ("install", "clean", 17),
    ("lint", "clean", 17), ("test", "clean", 17),
    ("", "Warn", 1), ("", "Fatal", 1), ("", "Timeout", 1), ("", "Denied", 1),
])
def test_actual_python_workload_order_failure_and_cleanup(tmp_path, name, title, failure, output, expected):
    if name == "bandit":
        expected = 17 if failure in ("install", "test") else 0
    checkout = tmp_path / "checkout"; checkout.mkdir()
    (checkout / "backend").mkdir()
    shared = tmp_path / "shared-home"; shared.mkdir()
    sentinel = shared / "package-lock.json"; sentinel.write_text("keep")
    temporary = tmp_path / "runner"; temporary.mkdir()
    unrelated = temporary / "unrelated"; unrelated.write_text("keep")
    tools = tmp_path / "tools"; tools.mkdir()
    trace = tmp_path / "trace"
    python = tools / "python"
    executable(python, '''printf 'python %s HOME=%s TMPDIR=%s\\n' "$*" "$HOME" "$TMPDIR" >> "$TRACE"
if [ "$1 $2" = '-m venv' ]; then
  mkdir -p "$3/bin"
  ln -s "$PYTHON_STUB" "$3/bin/python"
  ln -s "$BANDIT_STUB" "$3/bin/bandit"
elif [ "$1 $2" = '-m pip' ]; then
  [ "$FAILURE" != install ] || exit 17
elif [ "$1 $2" = '-m ruff' ]; then
  [ "$FAILURE" != lint ] || exit 17
elif [ "$1 $2" = '-m pytest' ]; then
  printf '%s\\n' "$TEST_OUTPUT"
  [ "$FAILURE" != test ] || exit 17
fi
''')
    bandit = tools / "bandit"
    executable(bandit, '''printf 'bandit %s HOME=%s TMPDIR=%s\\n' "$*" "$HOME" "$TMPDIR" >> "$TRACE"
printf '{}\\n' > bandit-results.sarif
[ "$FAILURE" != test ] || exit 17
''')
    env = {"PATH": f"{tools}:/usr/bin:/bin", "HOME": str(shared), "TMPDIR": str(tmp_path),
           "RUNNER_TEMP": str(temporary), "TRACE": str(trace), "PYTHON_STUB": str(python),
           "BANDIT_STUB": str(bandit), "FAILURE": failure, "TEST_OUTPUT": output}
    result = shell(step_named(name, title)["run"], checkout, env)
    assert result.returncode == expected, result.stderr
    assert sentinel.read_text() == "keep" and unrelated.read_text() == "keep"
    assert list(temporary.iterdir()) == [unrelated]
    rows = trace.read_text().splitlines()
    assert rows[0].startswith("python -m venv ")
    assert all(f"HOME={shared}" not in row and f"TMPDIR={tmp_path} " not in row for row in rows)
    if failure == "install":
        assert not any(row.startswith("python -m ruff ") or row.startswith("python -m pytest ") or row.startswith("bandit ") for row in rows)
    if name == "backend" and failure == "lint":
        assert not any(row.startswith("python -m pytest ") for row in rows)
    if name == "bandit" and failure != "install":
        assert (checkout / "bandit-results.sarif").is_file()


def frontend_fixture(tmp_path):
    checkout = tmp_path / "checkout"; checkout.mkdir()
    (checkout / "frontend").mkdir()
    runner = tmp_path / "runner"; runner.mkdir()
    (runner / "unrelated").write_text("keep")
    shared = tmp_path / "shared"; shared.mkdir()
    (shared / "package-lock.json").write_text("keep")
    tools = tmp_path / "tools"; tools.mkdir()
    env = {"PATH": f"{tools}:/usr/bin:/bin", "HOME": str(shared), "RUNNER_TEMP": str(runner), "GITHUB_WORKSPACE": str(checkout)}
    for key in ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH"):
        env[key] = str(tmp_path / key)
        Path(env[key]).touch()
    result = shell(step_named("frontend", "Prepare job-private runtime")["run"], checkout, env)
    assert result.returncode == 0, result.stderr
    result = shell(step_named("frontend", "Configure checkout-local pnpm store for setup-node post")["run"], checkout, env)
    assert result.returncode == 0, result.stderr
    env.update(dict(line.split("=", 1) for line in Path(env["GITHUB_ENV"]).read_text().splitlines()))
    root = Path(env["NARUON_JOB_ROOT"])
    assert root.stat().st_mode & 0o777 == 0o700
    for child in ("home", "tmp", "bin", "screenshots"):
        assert (root / child).stat().st_mode & 0o777 == 0o700
    env["JOB_ROOT"] = str(root)
    return checkout, env, tools, root, shared, runner


# Exact declarations from naruon@042b0c70531b229af3acbd0421a2f23098d848b3,
# frontend/scripts/full-product-ui-smoke.mjs (blob 008d612678f9497b865a296a79038c3e875d864c).
# The outer evidence runner verifies these byte slices against the complete Git blob.
FULL_PRODUCT_ARTIFACT_SOURCE = '''const DEFAULT_FULL_PRODUCT_SCREENSHOT_PROFILE = "/tmp/naruon-full-product-smoke";
const RESPONSIVE_FULL_PRODUCT_SCREENSHOT_PROFILE = "/tmp/naruon-full-product-responsive-qa";

export function resolveFullProductScreenshotProfile(environment = process.env) {
  return (
    environment.NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE ??
    environment.NARUON_FULL_PRODUCT_SCREENSHOT_DIR
  );
}

function resolveFullProductArtifactPrefix(rawProfile) {
  switch (rawProfile) {
    case undefined:
    case DEFAULT_FULL_PRODUCT_SCREENSHOT_PROFILE:
      return "naruon-full-product-smoke-";
    case RESPONSIVE_FULL_PRODUCT_SCREENSHOT_PROFILE:
      return "naruon-full-product-responsive-qa-";
    default:
      throw new Error(
        "NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE (or legacy NARUON_FULL_PRODUCT_SCREENSHOT_DIR) must select an approved artifact profile",
      );
  }
}

export async function createFullProductArtifactDirectory(rawProfile) {
  const prefix = resolveFullProductArtifactPrefix(rawProfile);
  return mkdtemp(path.join(tmpdir(), prefix));
}
'''


def artifact_directory(env, cwd):
    node = shutil.which("node")
    assert node, "Node is required for exact-consumer characterization"
    script = (
        'import { mkdtemp } from "node:fs/promises";\n'
        'import { tmpdir } from "node:os";\n'
        'import path from "node:path";\n'
        + FULL_PRODUCT_ARTIFACT_SOURCE
        + 'console.log(await createFullProductArtifactDirectory(resolveFullProductScreenshotProfile()));\n'
    )
    return subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=10,
    )


def test_frontend_emitted_profile_reaches_exact_consumer_private_mkdtemp(tmp_path):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    result = artifact_directory(env, checkout)
    assert result.returncode == 0, result.stderr
    artifact = Path(result.stdout.strip())
    assert artifact.parent == root / "tmp"
    assert artifact.name.startswith("naruon-full-product-smoke-")
    assert artifact.stat().st_mode & 0o777 == 0o700
    sentinel = artifact / "home.png"
    sentinel.write_bytes(b"owned-artifact-control")
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == 0, result.stderr
    assert not artifact.exists()
    assert (shared / "package-lock.json").read_text() == "keep"
    assert (runner / "unrelated").read_text() == "keep"


@pytest.mark.parametrize("profile,prefix", [
    (None, "naruon-full-product-smoke-"),
    ("/tmp/naruon-full-product-smoke", "naruon-full-product-smoke-"),
    ("/tmp/naruon-full-product-responsive-qa", "naruon-full-product-responsive-qa-"),
    ("arbitrary-owned-path", None), ("", None),
])
def test_exact_consumer_artifact_profile_controls(tmp_path, profile, prefix):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    env.pop("NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE", None)
    env.pop("NARUON_FULL_PRODUCT_SCREENSHOT_DIR", None)
    if profile is not None:
        env["NARUON_FULL_PRODUCT_SCREENSHOT_DIR"] = (
            str(root / "screenshots") if profile == "arbitrary-owned-path" else profile
        )
    result = artifact_directory(env, checkout)
    if prefix is None:
        assert result.returncode == 1
        assert "must select an approved artifact profile" in result.stderr
        assert list((root / "tmp").iterdir()) == []
    else:
        assert result.returncode == 0, result.stderr
        artifact = Path(result.stdout.strip())
        assert artifact.parent == root / "tmp"
        assert artifact.name.startswith(prefix)


def test_frontend_owned_home_build_screenshot_and_cleanup(tmp_path):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    executable(tools / "pnpm", 'printf "%s\\n" "$HOME $TMPDIR $NARUON_FULL_PRODUCT_SCREENSHOT_PROFILE"\n')
    (root / "home/package-lock.json").write_text("owned")
    result = shell(step_named("frontend", "Build frontend")["run"], checkout, env)
    assert result.returncode == 0, result.stderr
    assert not (root / "home/package-lock.json").exists()
    assert (shared / "package-lock.json").read_text() == "keep"
    assert result.stdout.strip() == f"{root}/home {root}/tmp /tmp/naruon-full-product-smoke"
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == 0, result.stderr
    assert not root.exists()
    assert (runner / "unrelated").read_text() == "keep"
    assert (shared / "package-lock.json").read_text() == "keep"


def corepack_adapter(tools):
    executable(tools / "node", 'if [ "$MODE" = wrong-node ]; then echo v22.1.0; else echo v24.1.0; fi\n')
    executable(tools / "corepack", '''printf 'corepack %s\\n' "$*" >> "$TRACE"
if [ "$1" = enable ]; then
  printf '#!/bin/bash\\nset -eu\\nprintf "pnpm %%s\\\\n" "$*" >> "$TRACE"\\nif [ "$1" = --version ]; then\\n  if [ "$MODE" = wrong-pnpm ]; then echo 10.0.0; else echo 11.5.3; fi\\nelif [ "$1 $2 $3" = "store path --silent" ]; then\\n  [ "$MODE" != store-fails ] || exit 17\\n  printf "%%s\\\\n" "$DISCOVERED_STORE"\\nfi\\n' > "$NARUON_JOB_ROOT/bin/pnpm"
  chmod +x "$NARUON_JOB_ROOT/bin/pnpm"
fi
if [ "$1" = prepare ] && [ "$MODE" = prepare-fails ]; then exit 17; fi
if [ "$1" = --version ]; then echo 0.35.0; fi
''')


@pytest.mark.parametrize("mode,expected", [("ok", 0), ("missing", 1), ("prepare-fails", 17), ("wrong-node", 1), ("wrong-pnpm", 1)])
def test_corepack_prerequisite_actual_order_and_failure(tmp_path, mode, expected):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    env["TRACE"] = str(tmp_path / "trace")
    env["MODE"] = mode
    env["DISCOVERED_STORE"] = str(checkout / ".naruon-pnpm-store/v11")
    corepack_adapter(tools)
    if mode == "missing":
        (tools / "corepack").unlink()
    result = shell(step_named("frontend", "Enable Corepack pnpm")["run"], checkout / "frontend", env)
    assert result.returncode == expected, result.stderr
    if mode == "ok":
        rows = Path(env["TRACE"]).read_text().splitlines()
        assert rows == [
            "corepack --version", f"corepack enable --install-directory {root}/bin pnpm",
            "corepack prepare pnpm@11.5.3 --activate", "pnpm --version",
            "pnpm store path --silent",
        ]
        assert Path(env["GITHUB_PATH"]).read_text().strip() == f"{root}/bin"
    assert (shared / "package-lock.json").read_text() == "keep"
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == 0


@pytest.mark.parametrize("store", ["home", "sibling", "traversal", "empty", "command-fails"])
def test_corepack_refuses_unowned_discovered_store_before_cache(tmp_path, store):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    env["TRACE"] = str(tmp_path / "trace")
    env["MODE"] = "store-fails" if store == "command-fails" else "ok"
    env["DISCOVERED_STORE"] = {
        "home": str(root / "home/.local/share/pnpm/store/v11"),
        "sibling": str(checkout / ".naruon-pnpm-store-foreign/v11"),
        "traversal": str(checkout / ".naruon-pnpm-store/../foreign/v11"),
        "empty": "", "command-fails": "",
    }[store]
    corepack_adapter(tools)
    result = shell(step_named("frontend", "Enable Corepack pnpm")["run"], checkout / "frontend", env)
    assert result.returncode == (17 if store == "command-fails" else 1), result.stderr
    assert "pnpm store path --silent" in Path(env["TRACE"]).read_text().splitlines()
    if store != "command-fails":
        assert "Refuse pnpm store outside checkout-local cache root" in result.stderr
    cleanup = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert cleanup.returncode == 0
    assert (shared / "package-lock.json").read_text() == "keep"
    assert (runner / "unrelated").read_text() == "keep"


@pytest.mark.parametrize("target", ["shared", "empty", "foreign"])
def test_frontend_cleanup_refuses_nonowned_paths(tmp_path, target):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    env["JOB_ROOT"] = {"shared": str(shared), "empty": "", "foreign": str(runner / "unrelated")}[target]
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == (0 if target == "empty" else 1)
    assert (shared / "package-lock.json").read_text() == "keep"
    assert (runner / "unrelated").read_text() == "keep"
    assert root.exists()


def test_node_cache_prerequisites_are_causally_ordered():
    steps = load("frontend")["jobs"]["frontend"]["steps"]
    bootstrap = next(i for i, s in enumerate(steps) if s.get("name") == "Bootstrap Node.js without package-manager cache")
    corepack = next(i for i, s in enumerate(steps) if s.get("name") == "Enable Corepack pnpm")
    cached = next(i for i, s in enumerate(steps) if s.get("name") == "Set up Node.js")
    assert bootstrap < corepack < cached
    assert steps[bootstrap]["with"] == {"node-version": "24", "package-manager-cache": "false"}
    assert all(not s.get("continue-on-error") for s in steps)


def pinned_pnpm_store(env, cwd):
    pnpm = shutil.which("pnpm")
    node = shutil.which("node")
    assert pnpm and node, "Node and locally provisioned pnpm 11.5.3 are required (no download/skip)"
    package_root = Path(pnpm).resolve().parents[1]
    assert json.loads((package_root / "package.json").read_text())["version"] == "11.5.3"
    assert hashlib.sha256((package_root / "dist/pnpm.mjs").read_bytes()).hexdigest() == (
        "db24b8f44a6438e100eab2e690464b971d35ee3c9af4638dcab3af7ee90c8cdd"
    )
    native_env = {**env, "PATH": f"{Path(node).parent}:{env['PATH']}"}
    version = subprocess.run(
        [pnpm, "--version"], cwd=cwd, env=native_env,
        capture_output=True, text=True, timeout=10,
    )
    assert version.returncode == 0 and version.stdout.strip() == "11.5.3", version.stderr
    result = subprocess.run(
        [pnpm, "store", "path", "--silent"], cwd=cwd, env=native_env,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    return Path(result.stdout.strip())


@pytest.mark.parametrize("key,selected", [
    ("PNPM_CONFIG_STORE_DIR", True), ("pnpm_config_store_dir", True),
    ("npm_config_store_dir", False),
])
def test_pnpm11_native_store_env_prefix_controls(tmp_path, key, selected):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    env.pop("PNPM_CONFIG_STORE_DIR", None)
    env.pop("npm_config_store_dir", None)
    expected = checkout / ".naruon-pnpm-store"
    env[key] = str(expected)
    store = pinned_pnpm_store(env, checkout)
    assert (expected in store.parents) is selected
    if not selected:
        assert root / "home" in store.parents


def test_corepack_shell_checks_native_pnpm_store_before_setup_node(tmp_path):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    native_pnpm = shutil.which("pnpm")
    node = shutil.which("node")
    assert native_pnpm and node
    env["PATH"] = f"{tools}:{Path(node).parent}:/usr/bin:/bin"
    env["NATIVE_PNPM"] = native_pnpm
    # Provisioning is inert/offline; the workflow's pnpm commands are the real pinned CLI.
    executable(tools / "corepack", '''if [ "$1" = enable ]; then
  ln -s "$NATIVE_PNPM" "$NARUON_JOB_ROOT/bin/pnpm"
elif [ "$1" = prepare ]; then
  [ "$2" = pnpm@11.5.3 ]
else
  echo offline-provisioning-adapter
fi
''')
    result = shell(step_named("frontend", "Enable Corepack pnpm")["run"], checkout / "frontend", env)
    assert result.returncode == 0, result.stderr
    store = pinned_pnpm_store(env, checkout)
    assert checkout / ".naruon-pnpm-store" in store.parents
    # Removing the supported key reproduces the old HOME store and the real shell refuses it.
    env.pop("PNPM_CONFIG_STORE_DIR")
    env["npm_config_store_dir"] = str(checkout / ".naruon-pnpm-store")
    (root / "bin/pnpm").unlink()
    result = shell(step_named("frontend", "Enable Corepack pnpm")["run"], checkout / "frontend", env)
    assert result.returncode == 1
    assert "Refuse pnpm store outside checkout-local cache root" in result.stderr


def test_frontend_cache_store_survives_home_cleanup_for_setup_node_post(tmp_path):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    store = pinned_pnpm_store(env, checkout)
    assert checkout / ".naruon-pnpm-store" in store.parents
    assert root not in store.parents
    assert pinned_pnpm_store(env, checkout / "frontend") == store
    store.mkdir(parents=True, exist_ok=True)
    (store / "sentinel").write_text("cache-post-input")
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == 0
    assert not root.exists()
    assert (store / "sentinel").read_text() == "cache-post-input"


@pytest.mark.parametrize("name,title", [
    ("backend", "Verify backend in a job-private environment"),
    ("bandit", "Run Bandit in a job-private environment"),
    ("frontend", "Prepare job-private runtime"),
])
def test_private_runtime_rejects_symlink_runner_temp(tmp_path, name, title):
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "sentinel").write_text("keep")
    linked = tmp_path / "linked"; linked.symlink_to(outside, target_is_directory=True)
    tools = tmp_path / "tools"; tools.mkdir()
    executable(tools / "python", 'echo invoked >> "$TRACE"\nexit 0\n')
    executable(tools / "bandit", 'echo bandit-invoked >> "$TRACE"\nexit 0\n')
    (tmp_path / "backend").mkdir()
    env = {"PATH": f"{tools}:/usr/bin:/bin", "RUNNER_TEMP": str(linked),
           "TRACE": str(tmp_path / "trace"), "GITHUB_ENV": str(tmp_path / "env"),
           "GITHUB_OUTPUT": str(tmp_path / "output")}
    result = shell(step_named(name, title)["run"], tmp_path, env)
    assert result.returncode == 1, result.stderr
    assert "Refuse untrusted runner temporary root" in result.stderr
    assert not (tmp_path / "trace").exists()
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel"]


@pytest.mark.parametrize("title", [
    "Install frontend dependencies", "Run frontend tests", "Run frontend lint",
    "Build frontend", "Install Playwright Chromium", "Run full product smoke",
])
def test_frontend_workload_failures_remain_gating(tmp_path, title):
    checkout, env, tools, root, shared, runner = frontend_fixture(tmp_path)
    executable(tools / "pnpm", 'exit 17\n')
    result = shell(step_named("frontend", title)["run"], checkout, env)
    assert result.returncode == 17
    result = shell(step_named("frontend", "Clean job-private runtime")["run"], checkout, env)
    assert result.returncode == 0
    assert not root.exists()
    assert (shared / "package-lock.json").read_text() == "keep"
