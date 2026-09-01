"""Tests for the Strix zero-timeout compatibility launcher."""

from __future__ import annotations

import asyncio
from types import ModuleType

import pytest

from scripts.ci import strix_timeout_compat as compat


class FakeAsyncio:
    """Capture delegated wait parameters while completing the supplied awaitable."""

    marker = object()

    def __init__(self) -> None:
        """Initialize the captured timeout."""
        self.timeout: float | None = 999

    async def wait_for(self, awaitable: object, timeout: float | None = None) -> object:
        """Record the normalized timeout and await the coroutine."""
        self.timeout = timeout
        return await awaitable  # type: ignore[misc]


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, None), (0, None), (-1, None), (0.25, 0.25)],
)
def test_normalize_wait_timeout(
    configured: float | None,
    expected: float | None,
) -> None:
    """Non-positive values disable only the wrapper deadline."""
    assert compat.normalize_wait_timeout(configured) == expected


@pytest.mark.parametrize(("configured", "expected"), [(0, None), (2, 2)])
def test_asyncio_proxy_delegates_with_normalized_timeout(
    configured: float,
    expected: float | None,
) -> None:
    """The proxy preserves other asyncio attributes and delegates the awaitable."""
    delegate = FakeAsyncio()
    proxy = compat.AsyncioTimeoutProxy(delegate)

    async def result() -> str:
        return "ok"

    assert proxy.marker is delegate.marker
    assert asyncio.run(proxy.wait_for(result(), timeout=configured)) == "ok"
    assert delegate.timeout == expected


def test_install_preflight_compatibility_patches_only_reviewed_modules() -> None:
    """The exact supported distribution patches both warm-up module globals."""
    modules: dict[str, ModuleType] = {}
    for name in ("strix.interface.scan_setup", "strix.interface.main"):
        module = ModuleType(name)
        module.asyncio = object()  # type: ignore[attr-defined]
        modules[name] = module
    delegate = FakeAsyncio()

    installed = compat.install_preflight_compatibility(
        version_getter=lambda distribution: (
            compat.SUPPORTED_VERSION
            if distribution == compat.SUPPORTED_DISTRIBUTION
            else "unexpected"
        ),
        module_loader=modules.__getitem__,
        asyncio_delegate=delegate,
    )

    assert installed == tuple(modules.values())
    assert all(
        isinstance(module.asyncio, compat.AsyncioTimeoutProxy)  # type: ignore[attr-defined]
        for module in installed
    )


def test_install_preflight_compatibility_rejects_unreviewed_version() -> None:
    """A dependency update fails closed until its warm-up behavior is reviewed."""
    with pytest.raises(compat.UnsupportedStrixVersion, match="found 1.5.4"):
        compat.install_preflight_compatibility(version_getter=lambda _: "1.5.4")


def test_install_preflight_compatibility_rejects_changed_module_shape() -> None:
    """A removed module-level asyncio dependency fails closed instead of silently bypassing."""
    missing = ModuleType("strix.interface.scan_setup")
    present = ModuleType("strix.interface.main")
    present.asyncio = object()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="no longer exposes"):
        compat.install_preflight_compatibility(
            version_getter=lambda _: compat.SUPPORTED_VERSION,
            module_loader=lambda name: missing if name.endswith("scan_setup") else present,
        )


def test_load_strix_main_returns_callable_and_rejects_changed_entrypoint() -> None:
    """The wrapper binds only the reviewed Strix console entry point."""
    called: list[str] = []
    valid = ModuleType("strix.interface.main")
    valid.main = lambda: called.append("strix")  # type: ignore[attr-defined]
    loaded = compat.load_strix_main(lambda _: valid)
    loaded()
    assert called == ["strix"]

    invalid = ModuleType("strix.interface.main")
    with pytest.raises(RuntimeError, match="main is unavailable"):
        compat.load_strix_main(lambda _: invalid)


def test_main_installs_before_invoking_strix() -> None:
    """The compatibility layer is active before the original CLI starts importing work."""
    events: list[str] = []
    compat.main(
        installer=lambda: events.append("install"),
        entrypoint_loader=lambda: lambda: events.append("run"),
    )
    assert events == ["install", "run"]
