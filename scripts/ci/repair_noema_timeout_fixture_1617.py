#!/usr/bin/env python3
"""Update the existing Noema repair fixture for the repair-only timeout contract."""

from pathlib import Path


TEST = Path(__file__).resolve().parents[2] / "tests/test_noema_review_gate.py"


def main() -> None:
    """Require no primary timeout and the bounded timeout on the one repair call."""
    text = TEST.read_text(encoding="utf-8")
    old = '''        def open(self, request, timeout=None):
            assert timeout is None
            payloads.append(json.loads(request.data))
            return Response(invalid if len(payloads) == 1 else valid)
'''
    new = '''        def open(self, request, timeout=None):
            if payloads:
                assert timeout == noema.NOEMA_REPAIR_TIMEOUT_SECONDS
            else:
                assert timeout is None
            payloads.append(json.loads(request.data))
            return Response(invalid if len(payloads) == 1 else valid)
'''
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one repair-timeout fixture, found {count}")
    TEST.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
