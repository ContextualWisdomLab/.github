"""Exercise the shipped ICD selector without installing or running a GPU."""

import os
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def _adapter_function(icd_root):
    """Change only the fixed system pathname to a fixture-owned directory."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          ensure_rust_gpu_adapter() {")
    end = text.index("\n          ensure_rust_desktop_deps() {", start)
    function = text[start:end]
    assert function.count("/usr/share/vulkan/icd.d/") >= 1
    return function.replace("/usr/share/vulkan/icd.d/", str(icd_root) + "/")


@pytest.mark.parametrize("names,expected", [
    ([], None),
    (["lvp_icd.a.json"], "lvp_icd.a.json"),
    (["lvp_icd.b.json", "lvp_icd.a.json"], "lvp_icd.a.json"),
    (["lvp_icd.a b.json"], "lvp_icd.a b.json"),
    (["lvp_icd.a\nb.json"], "lvp_icd.a\nb.json"),
])
def test_adapter_keeps_complete_path(tmp_path, names, expected):
    """The actual selector retains the whole selected filename and both exports."""
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    script = "append() { :; }\n" + _adapter_function(tmp_path)
    script += '\nensure_rust_gpu_adapter\nprintf "%s\\0%s" "${VK_ICD_FILENAMES:-}" "${VK_DRIVER_FILES:-}"'
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={"PATH": os.defpath, "LC_ALL": "C"},
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    selected = str(tmp_path / expected).encode() if expected else b""
    assert result.stdout == selected + b"\0" + selected
    assert result.stderr == b""


def test_adapter_does_not_select_matching_directory(tmp_path):
    """Only a regular ICD file can be exported as a driver configuration."""
    (tmp_path / "lvp_icd.a.json").mkdir()
    (tmp_path / "lvp_icd.b.json").write_text("{}", encoding="utf-8")
    script = "append() { :; }\n" + _adapter_function(tmp_path)
    script += '\nensure_rust_gpu_adapter\nprintf "%s" "${VK_ICD_FILENAMES:-}"'
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={"PATH": os.defpath, "LC_ALL": "C"},
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(tmp_path / "lvp_icd.b.json").encode()
