"""Regression for provider bootstrap environment erasure."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


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
namespace["_scrub_provider_bootstrap_environment"](os.environ)
procfs = Path("/proc/self/environ").read_bytes() if Path("/proc/self/environ").exists() else b""
child = subprocess.run(
    [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
    check=True,
    capture_output=True,
    text=True,
    env=os.environ.copy(),
)
print(json.dumps({
    "names": list(names),
    "current": dict(os.environ),
    "procfs_hex": procfs.hex(),
    "child": json.loads(child.stdout),
}))
'''
    env = os.environ.copy()
    secrets = {name: f"secret-{index}-never-retain" for index, name in enumerate(PROVIDER_NAMES)}
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
    assert evidence["current"]["UNRELATED_BOOTSTRAP_VALUE"] == "preserved"
    assert evidence["child"]["UNRELATED_BOOTSTRAP_VALUE"] == "preserved"
    for name, secret in secrets.items():
        assert name not in evidence["current"]
        assert name not in evidence["child"]
        assert secret.encode().hex() not in evidence["procfs_hex"]
