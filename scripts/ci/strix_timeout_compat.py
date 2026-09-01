#!/usr/bin/env python3
"""Run Strix 1.5.3 with consistent zero-timeout preflight semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import importlib
from importlib import metadata
from types import ModuleType
from typing import Any, TypeVar, cast

SUPPORTED_DISTRIBUTION = "strix-agent"
SUPPORTED_VERSION = "1.5.3"
_PATCH_MODULES = ("strix.interface.scan_setup", "strix.interface.main")
_ResultT = TypeVar("_ResultT")


class UnsupportedStrixVersion(RuntimeError):
    """Raised when the compatibility launcher sees an unreviewed Strix version."""


class AsyncioTimeoutProxy:
    """Delegate asyncio while translating non-positive ``wait_for`` limits to none."""

    def __init__(self, delegate: Any) -> None:
        """Keep the real asyncio module or a test double as the delegate."""
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        """Delegate every asyncio attribute except the patched ``wait_for`` call."""
        return getattr(self._delegate, name)

    async def wait_for(
        self,
        awaitable: Awaitable[_ResultT],
        timeout: float | None = None,
    ) -> _ResultT:
        """Preserve positive deadlines and disable zero or negative deadlines."""
        return await self._delegate.wait_for(
            awaitable,
            timeout=normalize_wait_timeout(timeout),
        )


def normalize_wait_timeout(timeout: float | None) -> float | None:
    """Match Strix request settings, where non-positive means no deadline."""
    if timeout is None or timeout > 0:
        return timeout
    return None


def install_preflight_compatibility(
    *,
    version_getter: Callable[[str], str] = metadata.version,
    module_loader: Callable[[str], ModuleType] = importlib.import_module,
    asyncio_delegate: Any = asyncio,
) -> tuple[ModuleType, ...]:
    """Patch only the two Strix 1.5.3 modules with inconsistent warm-up waits."""
    installed_version = version_getter(SUPPORTED_DISTRIBUTION)
    if installed_version != SUPPORTED_VERSION:
        raise UnsupportedStrixVersion(
            f"Strix timeout compatibility supports {SUPPORTED_DISTRIBUTION} "
            f"{SUPPORTED_VERSION}, found {installed_version}."
        )

    modules = tuple(module_loader(name) for name in _PATCH_MODULES)
    proxy = AsyncioTimeoutProxy(asyncio_delegate)
    for module in modules:
        if not hasattr(module, "asyncio"):
            raise RuntimeError(f"{module.__name__} no longer exposes its asyncio dependency.")
        module.asyncio = proxy  # type: ignore[attr-defined]
    return modules


def load_strix_main(
    module_loader: Callable[[str], ModuleType] = importlib.import_module,
) -> Callable[[], None]:
    """Load the reviewed Strix console entry point after compatibility is installed."""
    entrypoint = getattr(module_loader("strix.interface.main"), "main", None)
    if not callable(entrypoint):
        raise RuntimeError("strix.interface.main.main is unavailable.")
    return cast(Callable[[], None], entrypoint)


def main(
    *,
    installer: Callable[[], object] = install_preflight_compatibility,
    entrypoint_loader: Callable[[], Callable[[], None]] = load_strix_main,
) -> None:
    """Install the bounded compatibility layer, then run the original Strix CLI."""
    installer()
    entrypoint_loader()()


if __name__ == "__main__":  # pragma: no cover - exercised through the installed wrapper.
    main()
