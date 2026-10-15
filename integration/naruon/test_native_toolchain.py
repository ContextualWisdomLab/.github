"""Native Node/pnpm integration, executed by naruon-supplier-quality-ci."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "naruon_supplier_contract", ROOT / "tests/test_naruon_reusable_ci_contract.py"
)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)
frontend_fixture = CONTRACT.frontend_fixture
shell = CONTRACT.shell
step_named = CONTRACT.step_named
executable = CONTRACT.executable


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


