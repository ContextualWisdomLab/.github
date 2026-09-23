"""Execute the fixed-source guards with inert synthetic git responses."""
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = "00c6551183cca101cfc97c43656a17cc2491c1b4"
CASES = [("release-dependency-license-strix-gate.yml", "trusted-gate"),
         ("exact-artifact-sbom-attestation.yml", "trusted-intake"),
         ("exact-artifact-sbom-attestation.yml", "trusted-signer")]


def _parts(filename, destination):
    text = (ROOT / ".github/workflows" / filename).read_text()
    checkout = text.split(f"          path: {destination}\n", 1)[0].rsplit("      - name:", 1)[1]
    after = text.split(f"          HELPER_ROOT: {destination}\n", 1)[1]
    step = after.split("\n      - ", 1)[0]
    script = step.split("        run: |\n", 1)[1]
    return checkout, "\n".join(line[10:] for line in script.splitlines())


@pytest.mark.parametrize("filename,destination", CASES)
def test_literal_source_pin_and_sibling_scope(filename, destination):
    checkout, script = _parts(filename, destination)
    assert f"ref: {PIN}" in checkout
    assert "repository: ContextualWisdomLab/.github" in checkout
    assert "${{" not in checkout
    assert f"expected={PIN}" in script
    text = (ROOT / ".github/workflows" / filename).read_text()
    following = text.split(f"          path: {destination}\n", 1)[1]
    scope = following.split("      - name: Verify fixed helper checkout identity", 1)[0]
    assert "scripts/ci/" in scope and "requirements-strix-ci-hashes.txt" in scope


@pytest.mark.parametrize("filename,destination", CASES)
@pytest.mark.parametrize("case", ["ok", "caller_changed", "foreign", "missing", "pin", "tree", "dirty", "file"])
def test_actual_guard_rejects_bad_source(tmp_path, filename, destination, case):
    _, script = _parts(filename, destination)
    helper = tmp_path / destination
    (helper / "scripts/ci").mkdir(parents=True)
    for name in ("scripts/ci/release_dependency_gate.py", "scripts/ci/verify_exact_artifact_sbom_handoff.py", "requirements-strix-ci-hashes.txt"):
        if not (case == "file" and name.endswith("release_dependency_gate.py")):
            (helper / name).write_text("inert fixture")
    fake = '''git() {
      if [ "$CASE" = missing ]; then return 128; fi
      case "$*" in
        *"rev-parse HEAD:scripts/ci") [ "$CASE" = tree ] && echo bad || echo bf26d3eefdb71fe79b855d941ffb46eb432b2f76 ;;
        *"rev-parse HEAD:requirements-strix-ci-hashes.txt") echo 9e705850b5ce53c7fe836bc3df3a18771151e3f6 ;;
        *"rev-parse HEAD") [ "$CASE" = pin ] && echo bad || echo 00c6551183cca101cfc97c43656a17cc2491c1b4 ;;
        *"remote get-url origin") [ "$CASE" = foreign ] && echo https://github.com/caller/repo || echo https://github.com/ContextualWisdomLab/.github ;;
        *"diff --exit-code"*) [ "$CASE" != dirty ] ;;
        *) return 99 ;;
      esac
    }
'''
    result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", fake + script],
        env={**os.environ, "HELPER_ROOT": str(helper), "CASE": case,
             "CALLER_WORKFLOW_SHA": ("b" if case == "caller_changed" else "a") * 40},
        capture_output=True, text=True)
    assert (result.returncode == 0) is (case in ("ok", "caller_changed")), result.stderr
    if result.returncode == 0:
        assert f"helper_sha={PIN}" in result.stdout
