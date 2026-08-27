#!/usr/bin/env python3
"""Allow same-job loopback for the vendored contextual-orchestrator Noema path.

Mutates scripts/ci/noema_review_gate.py in the trusted materialization only when
NOEMA_LLM_VIA_ORCHESTRATOR=1. Private/link-local/multicast/unspecified stay blocked.
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    """Apply the loopback allow to the materialized Noema gate."""
    if os.environ.get("NOEMA_LLM_VIA_ORCHESTRATOR", "").strip() != "1":
        raise SystemExit("NOEMA_LLM_VIA_ORCHESTRATOR must be 1 before patching loopback")
    path = Path("scripts/ci/noema_review_gate.py")
    text = path.read_text(encoding="utf-8")
    old_host = (
        '    if hostname in {"localhost", "localhost.localdomain"} or '
        'hostname.endswith(".localhost"):\n'
        '        raise ValueError("URL cannot target localhost")\n'
    )
    new_host = (
        "    # Loopback allowed only when NOEMA_LLM_VIA_ORCHESTRATOR=1 "
        "(set only by noema-review.yml sidecar routing).\n"
    )
    old_ip = (
        "            if ip.is_private or ip.is_loopback or ip.is_link_local "
        "or ip.is_multicast or ip.is_unspecified:"
    )
    new_ip = (
        "            if ip.is_loopback:\n"
        "                continue\n"
        "            if ip.is_private or ip.is_link_local or ip.is_multicast "
        "or ip.is_unspecified:"
    )
    if old_host not in text or old_ip not in text:
        raise SystemExit("noema_review_gate.py SSRF block shape unexpected")
    text = text.replace(old_host, new_host, 1).replace(old_ip, new_ip, 1)
    path.write_text(text, encoding="utf-8")
    print("patched noema_review_gate.py for orchestrator loopback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
