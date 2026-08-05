"""Exact-source pin contract for the shared contextual fallback policy."""

from __future__ import annotations

import json

from scripts.ci import contextual_fallback_policy as policy


INTEGRATED_SOURCE_COMMIT = "40c6a4b419cdf8fa90c422acb5443a0e1cca5d16"


def test_vendor_receipt_targets_the_integrated_security_and_lock_commit() -> None:
    """Central policy evidence must pin the reviewed integrated upstream head."""

    receipt = json.loads(policy.VENDOR_RECEIPT_PATH.read_text(encoding="utf-8"))

    assert policy.SOURCE_COMMIT == INTEGRATED_SOURCE_COMMIT
    assert receipt["source_commit"] == INTEGRATED_SOURCE_COMMIT
