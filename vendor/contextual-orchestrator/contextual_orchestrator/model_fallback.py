"""Pinned integration facade for contextual-orchestrator fallback policy."""

from ._fallback_manifest import load_fallback_manifest
from ._fallback_plan import build_fallback_plan
from ._fallback_types import FallbackContext

__all__ = ["FallbackContext", "build_fallback_plan", "load_fallback_manifest"]
