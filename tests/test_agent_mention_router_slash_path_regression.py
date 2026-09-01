"""Regression coverage for root-relative OpenCode slash-command lookalikes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the production mention router from its script path."""

    module_name = "agent_mention_router_slash_path_regression"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_root_relative_paths_do_not_dispatch_opencode_aliases() -> None:
    """Path-like suffixes must not be accepted as standalone slash commands."""

    module = load_module()
    assert module.exact_mentions("/oc/config") == ()
    assert module.exact_mentions("/opencode/docs") == ()


def test_standalone_slash_aliases_remain_supported() -> None:
    """The path guard must preserve both documented standalone aliases."""

    module = load_module()
    assert module.exact_mentions("/oc") == ("opencode-agent",)
    assert module.exact_mentions("/opencode please review") == ("opencode-agent",)
