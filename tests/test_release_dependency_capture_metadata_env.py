"""Licence metadata must come from the lock-only environment's own inspect capture.

``release_dependency_capture_raw.sh`` inspects a ``--without-pip`` virtual
environment that holds exactly the hash-pinned lock. Its earlier metadata step ran
``python3 -m pip show`` *without* the ``--python`` target that the neighbouring
``pip inspect`` and ``pip download`` calls use, so it read the runner's global
interpreter instead: under ``set -e``/``pipefail`` that aborts the capture when the
distribution is absent globally, and silently reports a different version's licence
when some other version happens to be installed there.

The metadata is now derived from the already-collected ``python/installed.json``,
so identity and licence cannot disagree. These tests run the script's real jq
program — extracted from the script, so the assertions cannot drift from it — over
synthetic ``pip inspect`` documents. They need jq only; no runner, no network, and
no release dependency is installed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path("scripts/ci/release_dependency_capture_raw.sh")

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="jq is required to exercise the capture transform"
)


def _metadata_program() -> str:
    """Extract the metadata jq program the capture script actually runs."""
    text = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"jq --exit-status --arg name \"\$name\" --arg version \"\$version\" '(.*?)' "
        r"\"\$CAPTURE_ROOT/python/installed\.json\"",
        text,
        re.DOTALL,
    )
    assert match is not None, "the metadata jq program is no longer where the test expects"
    return match.group(1)


def _run(installed: dict[str, object], name: str, version: str) -> subprocess.CompletedProcess[str]:
    """Run the extracted jq program against one synthetic pip inspect document."""
    return subprocess.run(
        [
            "jq",
            "--exit-status",
            "--arg",
            "name",
            name,
            "--arg",
            "version",
            version,
            _metadata_program(),
        ],
        input=json.dumps(installed),
        capture_output=True,
        text=True,
        check=False,
    )


def _inspect(*entries: dict[str, object]) -> dict[str, object]:
    """Wrap metadata mappings as a pip inspect document."""
    return {"installed": [{"metadata": entry} for entry in entries]}


# ---------------------------------------------------------------------------
# The script never re-queries the global environment
# ---------------------------------------------------------------------------


def _executable_lines() -> list[str]:
    """Return the script's executable lines, with comments removed.

    The prose above the metadata transform names ``pip show`` deliberately, to
    record why it was removed; only executable lines are scanned for it.
    """
    return [
        line for line in _SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


def test_the_capture_script_never_runs_pip_show() -> None:
    """A second `pip show` would reintroduce the global-environment inconsistency."""
    assert not [line for line in _executable_lines() if "pip show" in line]


def test_every_pip_invocation_uses_the_target_interpreter_arguments() -> None:
    """pip inspect and pip download both describe the lock-only environment."""
    invocations = [line for line in _executable_lines() if "python3 -m pip " in line]
    # Exactly two pip invocations remain: inspect and download. The metadata step
    # no longer runs pip at all, so it cannot address a different environment.
    assert len(invocations) == 2, invocations
    assert any("inspect" in line for line in invocations)
    assert any("download" in line for line in invocations)
    for line in invocations:
        assert '"${PIP_TARGET_ARGS[@]}"' in line, line


# ---------------------------------------------------------------------------
# Positive regressions: version and licence come from the inspected environment
# ---------------------------------------------------------------------------


def test_the_declared_licence_expression_is_carried_through() -> None:
    """A PEP 639 License-Expression in the inspected environment is preserved."""
    result = _run(
        _inspect({"name": "greenlib", "version": "1.0.0", "license_expression": "MIT"}),
        "greenlib",
        "1.0.0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["license_expression"] == "MIT"
    assert payload["name"] == "greenlib"
    assert payload["version"] == "1.0.0"
    assert payload["ecosystem"] == "pypi"


def test_the_matching_version_is_selected_when_several_are_inspected() -> None:
    """The licence reported is the licence of the version the lock installed.

    This is the defect the global `pip show` produced: a different version's
    metadata answering for the locked one.
    """
    document = _inspect(
        {"name": "greenlib", "version": "0.9.0", "license_expression": "GPL-3.0-only"},
        {"name": "greenlib", "version": "1.0.0", "license_expression": "MIT"},
    )
    result = _run(document, "greenlib", "1.0.0")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == "1.0.0"
    assert payload["license_expression"] == "MIT"


def test_a_copyleft_licence_is_carried_through_verbatim() -> None:
    """The transform never sanitizes a licence; the gate makes the decision."""
    result = _run(
        _inspect(
            {"name": "redlib", "version": "2.0.0", "license_expression": "GPL-3.0-only"}
        ),
        "redlib",
        "2.0.0",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["license_expression"] == "GPL-3.0-only"


def test_legacy_license_and_classifiers_are_preserved() -> None:
    """A distribution with no License-Expression still yields its legacy signals."""
    result = _run(
        _inspect(
            {
                "name": "oldlib",
                "version": "1.2.3",
                "license": "Apache-2.0",
                "classifier": [
                    "License :: OSI Approved :: Apache Software License",
                    "Programming Language :: Python :: 3",
                ],
            }
        ),
        "oldlib",
        "1.2.3",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["license"] == "Apache-2.0"
    assert payload["license_expression"] == ""
    # Only licence classifiers are carried; the rest are irrelevant to the gate.
    assert payload["classifiers"] == ["License :: OSI Approved :: Apache Software License"]


def test_the_plural_classifiers_key_is_also_accepted() -> None:
    """pip's metadata key has varied; both spellings are read."""
    result = _run(
        _inspect(
            {
                "name": "oldlib",
                "version": "1.2.3",
                "classifiers": ["License :: OSI Approved :: MIT License"],
            }
        ),
        "oldlib",
        "1.2.3",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["classifiers"] == [
        "License :: OSI Approved :: MIT License"
    ]


def test_absent_licence_fields_become_empty_rather_than_null() -> None:
    """The gate's UNKNOWN hold needs empty strings, not nulls, to classify."""
    result = _run(_inspect({"name": "barelib", "version": "1.0.0"}), "barelib", "1.0.0")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["license_expression"] == ""
    assert payload["license"] == ""
    assert payload["classifiers"] == []


# ---------------------------------------------------------------------------
# Negative regressions: a missing or ambiguous entry is an error, not a default
# ---------------------------------------------------------------------------


def test_a_version_absent_from_the_inspected_environment_is_an_error() -> None:
    """The locked version must be the inspected version; no silent fallback."""
    document = _inspect(
        {"name": "greenlib", "version": "0.9.0", "license_expression": "MIT"}
    )
    result = _run(document, "greenlib", "1.0.0")
    assert result.returncode != 0
    assert "greenlib==1.0.0" in result.stderr


def test_a_name_absent_from_the_inspected_environment_is_an_error() -> None:
    """A dependency the environment does not hold cannot be given metadata."""
    result = _run(
        _inspect({"name": "greenlib", "version": "1.0.0"}), "ghostlib", "1.0.0"
    )
    assert result.returncode != 0
    assert "ghostlib==1.0.0" in result.stderr


def test_a_duplicated_entry_is_an_error_rather_than_a_first_match() -> None:
    """Two entries for one identity make the licence ambiguous, so the capture fails."""
    document = _inspect(
        {"name": "greenlib", "version": "1.0.0", "license_expression": "MIT"},
        {"name": "greenlib", "version": "1.0.0", "license_expression": "GPL-3.0-only"},
    )
    result = _run(document, "greenlib", "1.0.0")
    assert result.returncode != 0
    assert "got 2" in result.stderr


def test_an_empty_inspected_environment_is_an_error() -> None:
    """An environment holding nothing cannot answer for any dependency."""
    result = _run({"installed": []}, "greenlib", "1.0.0")
    assert result.returncode != 0
