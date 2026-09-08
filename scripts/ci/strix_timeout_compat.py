#!/usr/bin/env python3
"""Launch Strix 1.5.3 with ContextualWisdomLab's unbounded inference contract.

Strix 1.5.3 models ``LLM_TIMEOUT`` as an integer and passes it both to request
settings and to ``asyncio.wait_for`` during model preflight. ``0`` therefore
cancels preflight immediately instead of meaning "no deadline". This trusted,
version-gated launcher keeps Strix's non-model operational timeouts intact while
removing only model-request and model-warm-up wall-clock deadlines.
"""

from __future__ import annotations

import importlib.metadata
import os
import sys
from collections.abc import Awaitable, MutableMapping
from functools import wraps
from typing import Any


SUPPORTED_VERSION = "1.5.3"
STRIX_DISTRIBUTION = "strix-agent"


def normalize_inference_timeout_environment(environment: MutableMapping[str, str]) -> None:
    """Disable Strix request and stream-idle deadlines before settings import."""
    environment["LLM_TIMEOUT"] = "0"
    environment["LLM_STREAM_IDLE_TIMEOUT"] = "0"


class UnboundedInferenceAsyncio:
    """Delegate asyncio except that model warm-up ``wait_for`` has no deadline."""

    def __init__(self, asyncio_module: Any) -> None:
        """Retain the real asyncio module for every operation except ``wait_for``."""
        self._asyncio_module = asyncio_module

    def __getattr__(self, attribute_name: str) -> Any:
        """Delegate non-warm-up asyncio attributes without changing semantics."""
        return getattr(self._asyncio_module, attribute_name)

    async def wait_for(self, awaitable: Awaitable[Any], timeout: object) -> Any:
        """Await model warm-up without a fixed wall-clock deadline."""
        del timeout
        return await self._asyncio_module.wait_for(awaitable, timeout=None)


def _require_supported_version() -> None:
    """Fail closed instead of applying a compatibility shim to unknown Strix code."""
    try:
        installed_version = importlib.metadata.version(STRIX_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Pinned Strix distribution is not installed.") from exc
    if installed_version != SUPPORTED_VERSION:
        raise RuntimeError(
            "Strix timeout compatibility supports exactly "
            f"{SUPPORTED_VERSION}; installed version is {installed_version}."
        )


def install_runtime_compatibility() -> Any:
    """Install narrowly scoped model-timeout compatibility and return Strix main."""
    _require_supported_version()
    normalize_inference_timeout_environment(os.environ)

    # Import only after timeout normalization so Strix settings cannot cache the
    # workflow's positive parser-compatibility value as an inference deadline.
    from strix.core import inputs as strix_inputs

    original_make_model_settings = strix_inputs.make_model_settings

    @wraps(original_make_model_settings)
    def make_model_settings_without_request_deadline(*args: Any, **kwargs: Any) -> Any:
        """Preserve every model setting except the fixed request timeout."""
        kwargs["request_timeout"] = None
        return original_make_model_settings(*args, **kwargs)

    strix_inputs.make_model_settings = make_model_settings_without_request_deadline

    # These are the two Strix 1.5.3 modules that wrap model warm-up calls in
    # asyncio.wait_for(timeout=llm.timeout). Replacing their module-local asyncio
    # references leaves proxy/MCP/UI/process timeouts elsewhere intact.
    from strix.interface import scan_setup

    scan_setup.asyncio = UnboundedInferenceAsyncio(scan_setup.asyncio)

    # strix/interface/__init__.py runs ``from .main import main``, which rebinds
    # the package attribute ``strix.interface.main`` to the *function* it
    # imports, shadowing the submodule of the same name. Both
    # ``from strix.interface import main as strix_main`` and
    # ``import strix.interface.main as strix_main`` resolve through that
    # shadowed package attribute and return the function, not the module, so
    # every ``strix_main.<attr>`` access below raised AttributeError. Look the
    # submodule up directly in sys.modules by its exact dotted path instead,
    # which the shadow never touches.
    import strix.interface.main  # noqa: F401 - imported for its sys.modules registration

    strix_main = sys.modules["strix.interface.main"]

    strix_main.asyncio = UnboundedInferenceAsyncio(strix_main.asyncio)
    return strix_main


def main() -> None:
    """Apply the version-gated compatibility boundary and enter Strix normally."""
    strix_main = install_runtime_compatibility()
    strix_main.main()


if __name__ == "__main__":
    main()
