"""Execute the fixed-source guards with inert synthetic git responses."""
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PIN = "00c6551183cca101cfc97c43656a17cc2491c1b4"
EXACT_SET_PIN = "7cb4be4c5cfef406fae065eb4697018fe956b18c"
CASES = [
    ("release-dependency-license-strix-gate.yml", "trusted-gate",
     EXACT_SET_PIN, "30720a6a86fc0ee7f836bd7905fc62e7122e0b6d"),
    ("exact-artifact-sbom-attestation.yml", "trusted-intake",
     LEGACY_PIN, "bf26d3eefdb71fe79b855d941ffb46eb432b2f76"),
    ("exact-artifact-sbom-attestation.yml", "trusted-signer",
     LEGACY_PIN, "bf26d3eefdb71fe79b855d941ffb46eb432b2f76"),
]


def _parts(filename, destination):
    text = (ROOT / ".github/workflows" / filename).read_text()
    checkout = text.split(f"          path: {destination}\n", 1)[0].rsplit("      - name:", 1)[1]
    after = text.split(f"          HELPER_ROOT: {destination}\n", 1)[1]
    step = after.split("\n      - ", 1)[0]
    script = step.split("        run: |\n", 1)[1]
    return checkout, "\n".join(line[10:] for line in script.splitlines())


@pytest.mark.parametrize("filename,destination,pin,tree", CASES)
def test_literal_source_pin_and_sibling_scope(filename, destination, pin, tree):
    checkout, script = _parts(filename, destination)
    assert f"ref: {pin}" in checkout
    assert "repository: ContextualWisdomLab/.github" in checkout
    assert "${{" not in checkout
    assert f"expected={pin}" in script
    assert f"rev-parse HEAD:scripts/ci)\" = {tree}" in script
    text = (ROOT / ".github/workflows" / filename).read_text()
    following = text.split(f"          path: {destination}\n", 1)[1]
    scope = following.split("      - name: Verify fixed helper checkout identity", 1)[0]
    assert "scripts/ci/" in scope and "requirements-strix-ci-hashes.txt" in scope


@pytest.mark.parametrize("filename,destination,pin,tree", CASES)
@pytest.mark.parametrize("case", ["ok", "caller_changed", "foreign", "missing", "pin", "tree", "dirty", "file"])
def test_actual_guard_rejects_bad_source(tmp_path, filename, destination, pin, tree, case):
    _, script = _parts(filename, destination)
    helper = tmp_path / destination
    (helper / "scripts/ci").mkdir(parents=True)
    for name in (
        "scripts/ci/release_dependency_gate.py",
        "scripts/ci/verify_release_distribution_set.py",
        "scripts/ci/verify_exact_artifact_sbom_handoff.py",
        "requirements-strix-ci-hashes.txt",
    ):
        if not (case == "file" and name.endswith("release_dependency_gate.py")):
            (helper / name).write_text("inert fixture")
    fake = '''git() {
      if [ "$CASE" = missing ]; then return 128; fi
      case "$*" in
        *"rev-parse HEAD:scripts/ci") [ "$CASE" = tree ] && echo bad || echo "$EXPECTED_TREE" ;;
        *"rev-parse HEAD:requirements-strix-ci-hashes.txt") echo 9e705850b5ce53c7fe836bc3df3a18771151e3f6 ;;
        *"rev-parse HEAD") [ "$CASE" = pin ] && echo bad || echo "$EXPECTED_PIN" ;;
        *"remote get-url origin") [ "$CASE" = foreign ] && echo https://github.com/caller/repo || echo https://github.com/ContextualWisdomLab/.github ;;
        *"diff --exit-code"*) [ "$CASE" != dirty ] ;;
        *) return 99 ;;
      esac
    }
'''
    result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", fake + script],
        env={**os.environ, "HELPER_ROOT": str(helper), "CASE": case,
             "EXPECTED_PIN": pin, "EXPECTED_TREE": tree,
             "CALLER_WORKFLOW_SHA": ("b" if case == "caller_changed" else "a") * 40},
        capture_output=True, text=True)
    assert (result.returncode == 0) is (case in ("ok", "caller_changed")), result.stderr
    if result.returncode == 0:
        assert f"helper_sha={pin}" in result.stdout
