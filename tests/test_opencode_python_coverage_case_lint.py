"""Exercise the actual Python-coverage case without redundant alternatives."""

import fnmatch
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def _case_script():
    """Extract only the shipped basename case, retaining its loop break."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('              case "$changed_basename" in')
    end = text.index("              esac", start) + len("              esac")
    return (
        "#!/bin/bash\npython_coverage_required=0\n"
        "while IFS= read -r changed_basename; do\n"
        + text[start:end]
        + '\ndone\nprintf "%s\\n" "$python_coverage_required"\n'
    )


def test_python_coverage_case_has_no_shadowed_alternative():
    """Reject literal alternatives already admitted by an earlier glob."""
    case = _case_script().split('case "$changed_basename" in', 1)[1]
    alternatives = case.split(")", 1)[0].replace("\\\n", "").strip().split("|")
    earlier = []
    for alternative in alternatives:
        alternative = alternative.strip()
        if not any(character in alternative for character in "*?["):
            assert not any(fnmatch.fnmatchcase(alternative, pattern) for pattern in earlier), alternative
        earlier.append(alternative)


@pytest.mark.parametrize("name,expected", [
    ("setup.py", "1"), ("module.py", "1"), ("setup.cfg", "1"),
    ("pyproject.toml", "1"), ("requirements-dev.txt", "1"),
    ("environment.yaml", "1"), ("README.md", "0"),
    ("setup.py.bak", "0"), ("package.json", "0"),
])
def test_python_coverage_case_keeps_admission(name, expected):
    """Removing the redundant setup.py token must retain actual admission."""
    result = subprocess.run(
        ["bash", "-c", _case_script()], input=name + "\n",
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
