"""Regression coverage for the autofix context package-import fallback."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

from scripts.ci import pr_review_autofix_context as context
from scripts.ci import pr_review_fix_scheduler as scheduler


def test_package_import_fallback_uses_package_scheduler(monkeypatch: Any) -> None:
    """A package import still resolves the exact failed-check helper."""
    real_import = builtins.__import__

    def import_with_missing_top_level(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "pr_review_fix_scheduler" and level == 0:
            raise ModuleNotFoundError("forced top-level import miss")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_with_missing_top_level)
    module_path = Path(context.__file__)
    namespace: dict[str, Any] = {
        "__builtins__": builtins,
        "__file__": str(module_path),
        "__name__": "scripts.ci.pr_review_autofix_context_fallback_probe",
        "__package__": "scripts.ci",
    }

    exec(compile(module_path.read_text(encoding="utf-8"), str(module_path), "exec"), namespace)

    assert namespace["current_head_failed_checks"] is scheduler.current_head_failed_checks
