"""Emit bounded continuation outputs after a failed Strix provider scan."""

from __future__ import annotations

import argparse
import re

from scripts.ci import noema_transport_redispatch as gate


def main() -> int:
    """Write retry outputs only for a valid head and an unspent retry budget."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        print("::error::Strix continuation requires a canonical PR head SHA.")
        return 0

    attempt = gate.current_transport_retry_attempt()
    delay = gate.transport_redispatch_delay_seconds(
        transport_retry_attempt=attempt, head_sha=args.expected_head
    )
    outputs = {
        "transport_capacity_unavailable": "true",
        "transport_retry_eligible": "true" if delay is not None else "false",
    }
    if delay is not None:
        outputs["transport_retry_delay_seconds"] = str(delay)
        outputs["transport_retry_next_attempt"] = str(attempt + 1)
        print(
            "::notice::Strix provider scan may continue on the same head "
            f"after {delay}s (attempt {attempt + 1}/"
            f"{gate.MAX_TRANSPORT_REDISPATCH_ATTEMPTS})."
        )
    else:
        print("::error::Strix provider continuation budget is exhausted; review remains required.")
    gate.append_github_output(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
