# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 OmniSecure Inc.
# Modified file: test-only module excerpt; authentication function is unchanged.
# License: strix_login_as_guest_1_5_3.LICENSE.txt
# Source wheel SHA256: ba0b6b13f13f41e45f3eb4dba515641d1bc71363ca6e758d0cd05c20ff56b6ea
# Upstream source: https://github.com/usestrix/strix/blob/7cc9fa9faa0179fc7e35111102fe3d20a9028393/strix/runtime/caido_bootstrap.py
from __future__ import annotations

import asyncio
import json
import logging
logger = logging.getLogger(__name__)

_LOGIN_AS_GUEST_BODY = (
    '{"query":"mutation LoginAsGuest { loginAsGuest { token { accessToken } } }"}'
)

async def _login_as_guest(
    session: BaseSandboxSession,
    *,
    container_url: str,
    attempts: int = 10,
) -> str:
    """``session.exec`` curl to fetch a guest token; retry until ready.

    Caido's GraphQL listener may not be up the instant the container
    starts. The retry loop also doubles as the Caido readiness probe —
    no separate TCP healthcheck needed.
    """
    last_err: str | None = None
    for i in range(1, attempts + 1):
        result = await session.exec(
            "curl",
            "-fsS",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            _LOGIN_AS_GUEST_BODY,
            f"{container_url}/graphql",
            timeout=15,
        )
        if result.ok():
            try:
                payload = json.loads(result.stdout)
                token = (
                    payload.get("data", {})
                    .get("loginAsGuest", {})
                    .get("token", {})
                    .get("accessToken")
                )
                if token:
                    return str(token)
                last_err = f"loginAsGuest returned no token: {payload}"
            except json.JSONDecodeError as exc:
                last_err = f"unparseable response: {exc}: {result.stdout!r}"
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")[:200]
            last_err = f"curl exit {result.exit_code}: {stderr}"
        logger.debug("loginAsGuest attempt %d/%d failed: %s", i, attempts, last_err)
        await asyncio.sleep(min(2.0 * i, 8.0))

    raise RuntimeError(f"loginAsGuest failed after {attempts} attempts: {last_err}")
