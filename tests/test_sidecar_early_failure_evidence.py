"""Early sidecar failures cannot publish a previous job's evidence."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OWNED = (
    "contextual-orchestrator-preflight.json",
    "contextual-orchestrator-sidecar.stdout.log",
    "contextual-orchestrator-sidecar.stderr.log",
    "contextual-orchestrator-discovery.json",
    "contextual-orchestrator-agents.json",
    "contextual-orchestrator-policy.json",
)


@pytest.mark.parametrize("failure", ["credentials", "dependencies", "launcher", "symlink", "staging-symlink", "work-symlink"])
def test_early_failure_resets_owned_evidence_without_touching_other_files(tmp_path, failure):
    """Run the real shell, preserve an unrelated file and reject linked outputs."""
    workspace = tmp_path / "workspace"
    evidence = workspace / "strix_runs"
    evidence.mkdir(parents=True)
    for name in OWNED:
        (evidence / name).write_text("previous job evidence")
    sentinel = evidence / "user-file.txt"
    sentinel.write_text("preserve me")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data")
    if failure == "symlink":
        (evidence / OWNED[0]).unlink()
        (evidence / OWNED[0]).symlink_to(outside)
    staging = tmp_path / "temp" / "contextual-orchestrator-review"
    staging.mkdir(parents=True)
    staging_names = ("discovery-free.json", "agents.review.json", "policy-report.json")
    for name in staging_names:
        (staging / name).write_text("previous job evidence")
    if failure == "staging-symlink":
        (staging / staging_names[0]).unlink()
        (staging / staging_names[0]).symlink_to(outside)
    if failure == "work-symlink":
        linked = tmp_path / "linked-work"
        staging.rename(linked)
        staging.symlink_to(linked, target_is_directory=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pin = "a" * 40
    scripts = {
        "python3": "#!/bin/sh\nexit 37\n",
        "chmod": "#!/bin/sh\nmode=$1; shift\nif [ \"$1\" = -- ]; then shift; fi\nexec /bin/chmod \"$mode\" \"$@\"\n",
        "git": f'''#!/bin/sh
if [ "$1" = "clone" ]; then
    for destination; do :; done
    mkdir -p "$destination"
    touch "$destination/requirements.lock"
elif [ "$3" = "rev-parse" ]; then
    echo {pin}
fi
''',
    }
    if failure == "launcher":
        scripts["python3"] = f'''#!/bin/sh
case "$1" in
  -m)
    if [ "$2" = venv ]; then
      mkdir -p "$3/bin"
      cp "$0" "$3/bin/python"
    fi
    ;;
  -S|-u) exec "{sys.executable}" "$@" ;;
  */launch_sidecar.py) exit 37 ;;
  -) cat >/dev/null ;;
esac
exit 0
'''
        scripts["curl"] = "#!/bin/sh\nsleep 0.05\nexit 7\n"
    for name, script in scripts.items():
        path = bin_dir / name
        path.write_text(script)
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in (
        "BYTEZ_API_KEY", "NVIDIA_NIM_API_KEY", "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "GITHUB_ENV",
    )}
    env.update(PATH=f"{bin_dir}:{env.get('PATH', '')}", GITHUB_WORKSPACE=str(workspace),
               RUNNER_TEMP=str(tmp_path / "temp"), ORCHESTRATOR_TOKEN="synthetic",
               ORCHESTRATOR_PIN_SHA=pin)
    if failure != "credentials":
        env["OPENAI_API_KEY"] = "synthetic"
    startup_marker = tmp_path / "site-startup.txt"
    if failure == "launcher":
        (bin_dir / "sitecustomize.py").write_text(
            f"from pathlib import Path; Path({str(startup_marker)!r}).write_text('unexpected site startup')\n")
        env["PYTHONPATH"] = str(bin_dir)
    result = subprocess.run(["bash", str(ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh")],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert sentinel.read_text() == "preserve me"
    assert outside.read_text() == "outside data"
    if "symlink" in failure:
        assert "symbolic link" in result.stderr
    else:
        assert all((evidence / name).read_text() == "" for name in OWNED)
        assert all((staging / name).read_text() == "" for name in staging_names)
        assert result.returncode == (37 if failure == "dependencies" else 1)
        if failure == "launcher":
            assert "sidecar exited before healthz (status 37)" in result.stderr
            assert not startup_marker.exists()
