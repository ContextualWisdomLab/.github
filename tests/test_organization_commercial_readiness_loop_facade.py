"""Regression tests for the commercial-readiness compatibility facade."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import organization_commercial_readiness_ddd_contract as contract
from scripts.ci import organization_commercial_readiness_loop as coordinator


def test_facade_monkeypatches_reach_core_function_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing tests and callers patch the same module used by core functions."""
    sentinel = object()
    monkeypatch.setattr(coordinator, "build_plan", sentinel)
    assert coordinator.run_once.__globals__["build_plan"] is sentinel


def test_facade_direct_script_mode_delegates_to_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stable script path retains the original argument-validation behavior."""
    path = Path(contract.__file__).with_name(
        "organization_commercial_readiness_loop.py"
    )
    monkeypatch.setattr(sys, "argv", [str(path), "--organization", "invalid/name"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(path), run_name="__main__")
    assert raised.value.code == 2


def test_imported_facade_remains_executable_by_public_module_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the facade must not corrupt its public module identity."""
    monkeypatch.setattr(
        sys,
        "argv",
        [coordinator.__file__, "--organization", "invalid/name"],
    )
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        with pytest.raises(SystemExit) as raised:
            runpy.run_module(
                "scripts.ci.organization_commercial_readiness_loop",
                run_name="__main__",
            )
    assert raised.value.code == 2
