"""Regression for provider bootstrap environment erasure."""

from __future__ import annotations

import json
import os
import runpy
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
PROVIDER_NAMES = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)


def test_bootstrap_scrub_runs_immediately_after_kv_registration() -> None:
    """The gateway must erase transport credentials before any long-lived work."""
    source = LAUNCHER.read_text(encoding="utf-8")
    registered = source.index("registered = register_review_credentials(os.environ)")
    scrubbed = source.index("_scrub_provider_bootstrap_environment(os.environ)", registered)
    auth_lookup = source.index("auth_token = args.auth_token", registered)
    discovery = source.index("discover_all_models()", registered)

    assert registered < scrubbed < auth_lookup < discovery


def test_provider_bootstrap_secrets_leave_process_and_child_environments() -> None:
    """Registered bootstrap values must not survive in env or Linux procfs."""
    probe = r'''
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

namespace = runpy.run_path(sys.argv[1])
names = namespace["REVIEW_PROVIDER_BOOTSTRAP_ENV_NAMES"]
sentinels = [os.environ[name].encode() for name in names]
namespace["_scrub_provider_bootstrap_environment"](os.environ)
procfs = Path("/proc/self/environ").read_bytes() if Path("/proc/self/environ").exists() else b""
child = subprocess.run(
    [
        sys.executable,
        "-c",
        "import json, os, sys; "
        "names=json.loads(sys.argv[1]); "
        "print(json.dumps({'present':[n for n in names if n in os.environ], "
        "'unrelated':os.environ.get('UNRELATED_BOOTSTRAP_VALUE')}))",
        json.dumps(list(names)),
    ],
    check=True,
    capture_output=True,
    text=True,
    env=os.environ.copy(),
)
print(json.dumps({
    "names": list(names),
    "current_present": [name for name in names if name in os.environ],
    "current_unrelated": os.environ.get("UNRELATED_BOOTSTRAP_VALUE"),
    "procfs_secret_found": any(secret in procfs for secret in sentinels),
    "child": json.loads(child.stdout),
}))
'''
    env = os.environ.copy()
    secrets = {
        name: f"secret-{index}-never-retain"
        for index, name in enumerate(PROVIDER_NAMES)
    }
    env.update(secrets)
    env["UNRELATED_BOOTSTRAP_VALUE"] = "preserved"

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(LAUNCHER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)

    assert tuple(evidence["names"]) == PROVIDER_NAMES
    assert evidence["current_present"] == []
    assert evidence["current_unrelated"] == "preserved"
    assert evidence["child"]["present"] == []
    assert evidence["child"]["unrelated"] == "preserved"
    assert evidence["procfs_secret_found"] is False


def test_linux_scrub_fails_closed_without_procfs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux bootstrap must stop if original-environment proof is unavailable."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux procfs contract")

    namespace = runpy.run_path(str(LAUNCHER))
    erase_environment = namespace["_erase_linux_initial_environment"]
    monkeypatch.setattr(erase_environment.__globals__["Path"], "exists", lambda self: False)

    with pytest.raises(RuntimeError, match="/proc/self/environ"):
        erase_environment(frozenset({b"OPENAI_API_KEY"}))
