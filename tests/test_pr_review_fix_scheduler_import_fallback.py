"""Coverage contract for the PR review-fix scheduler import fallback."""

from __future__ import annotations

import builtins
import runpy
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest


def test_fix_scheduler_supports_package_qualified_import_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct-module absence loads the reviewed package-qualified scheduler."""

    real_import: Callable[..., ModuleType] = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> ModuleType:
        """Reject only the direct sibling import and preserve normal imports."""

        if name == "pr_review_merge_scheduler":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    namespace = runpy.run_path(
        "scripts/ci/pr_review_fix_scheduler.py",
        run_name="pr_review_fix_scheduler_package_fallback_probe",
    )

    assert callable(namespace["fetch_open_prs"])
    assert callable(namespace["run"])
    assert callable(namespace["unresolved_thread_count"])
