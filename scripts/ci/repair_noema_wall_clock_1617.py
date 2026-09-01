#!/usr/bin/env python3
"""Finish PR #1617 with a true repair wall-clock deadline.

Temporary one-shot branch repair helper. The repair workflow removes this file
before committing the production change.
"""

from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TEST = ROOT / "tests/test_noema_model_output_failure_classification.py"
CHANGELOG = ROOT / "CHANGELOG.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
DOCTORING = ROOT / "docs/doctoring/noema-model-output-repair-boundary.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def update_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_once(text, "import base64\n", "import base64\nimport contextlib\n", "contextlib import")
    text = replace_once(text, "import re\n", "import re\nimport signal\n", "signal import")
    text = replace_once(
        text,
        "# A repair request corrects an already-completed model verdict; it is not a\n"
        "# second unbounded full review. Fifteen minutes is the hard client-side\n"
        "# ceiling for that one corrective HTTP request. The primary review remains\n"
        "# governed by contextual-orchestrator rather than a fixed inference timeout.\n"
        "NOEMA_REPAIR_TIMEOUT_SECONDS = 15 * 60\n",
        "# A repair request corrects an already-completed model verdict; it is not a\n"
        "# second unbounded full review. Fifteen minutes is an absolute wall-clock\n"
        "# deadline for the complete corrective attempt (open/read/decode/validate),\n"
        "# not a socket inactivity timeout. The primary review remains governed by\n"
        "# contextual-orchestrator rather than a fixed inference timeout.\n"
        "NOEMA_REPAIR_DEADLINE_SECONDS = 15 * 60\n",
        "repair deadline constant",
    )
    marker = '''class NoemaTransportError(RuntimeError):
    """Raised when the bounded review transport cannot produce usable evidence."""
'''
    addition = marker + '''\n\nclass NoemaRepairDeadlineExceeded(TimeoutError):
    """Raised when the corrective attempt exceeds its total wall-clock budget."""
'''
    text = replace_once(text, marker, addition, "deadline error class")

    stale_marker = '''class StaleHeadDuringRepairRetryError(RuntimeError):
    """Raised when the PR head moves before ``call_llm``'s repair-retry request fires."""
'''
    deadline_helper = '''@contextlib.contextmanager
def _repair_wall_clock_deadline(seconds: float):
    """Interrupt the entire corrective attempt after ``seconds`` of wall time.

    ``urllib``'s timeout is a socket-operation timeout and can be extended by
    trickling bytes. Required Noema Review runs on Linux, so ITIMER_REAL gives
    the repair attempt one process-level wall-clock budget across open, read,
    decode, and deterministic validation. An existing process alarm is not
    overwritten; that condition fails closed instead.
    """
    if seconds <= 0:
        raise ValueError("repair wall-clock deadline must be positive")
    if not hasattr(signal, "setitimer") or not hasattr(signal, "ITIMER_REAL"):
        raise RuntimeError("repair wall-clock deadline requires POSIX setitimer support")
    previous_remaining, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    if previous_remaining > 0 or previous_interval > 0:
        raise RuntimeError("repair wall-clock deadline refused to overwrite an active process alarm")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum, _frame):
        raise NoemaRepairDeadlineExceeded(
            f"Noema repair exceeded {seconds:g}-second absolute wall-clock deadline"
        )

    try:
        signal.signal(signal.SIGALRM, expire)
    except ValueError as exc:
        raise RuntimeError("repair wall-clock deadline must run on the process main thread") from exc
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


''' + stale_marker
    text = replace_once(text, stale_marker, deadline_helper, "deadline helper")

    old_open = '''        if is_retry:
            response_context = opener.open(  # nosec B310
                request, timeout=NOEMA_REPAIR_TIMEOUT_SECONDS
            )
        else:
            response_context = opener.open(request)  # nosec B310
        with response_context as response:
            raw_bytes = response.read()
'''
    plain_open = '''        with opener.open(request) as response:  # nosec B310
            raw_bytes = response.read()
'''
    text = replace_once(text, old_open, plain_open, "remove socket timeout")

    try_marker = "    try:\n        with opener.open(request) as response:  # nosec B310\n"
    start = text.index(try_marker)
    body_start = start + len("    try:\n")
    except_marker = "    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:\n"
    end = text.index(except_marker, body_start)
    body = text[body_start:end]
    wrapped = (
        "        deadline_context = (\n"
        "            _repair_wall_clock_deadline(NOEMA_REPAIR_DEADLINE_SECONDS)\n"
        "            if is_retry\n"
        "            else contextlib.nullcontext()\n"
        "        )\n"
        "        with deadline_context:\n"
        + textwrap.indent(body, "    ")
    )
    text = text[:body_start] + wrapped + text[end:]
    SOURCE.write_text(text, encoding="utf-8")


def update_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    assert requests[1][1]["timeout"] == gate.NOEMA_REPAIR_TIMEOUT_SECONDS\n',
        '    assert requests[1][1] == {}\n',
        "socket-timeout assertion",
    )
    marker = "def test_total_repair_wall_clock_deadline_interrupts_slow_read"
    if marker in text:
        raise RuntimeError("wall-clock regression already present")
    text += r'''


def test_total_repair_wall_clock_deadline_interrupts_slow_read(monkeypatch) -> None:
    """Trickling/slow response activity cannot extend the one repair budget."""
    import json
    import signal
    import time

    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX process timer is required by the Linux review runner")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS", 0.05)
    head_sha = "d" * 40
    calls = 0

    class FirstResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    class SlowRepairResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            time.sleep(2)
            return b"{}"

    def open_response(_opener, _request, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs == {}
        return FirstResponse() if calls == 1 else SlowRepairResponse()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(gate, "fetch_pr", lambda _repo, _number: {"headRefOid": head_sha})

    started = time.monotonic()
    with pytest.raises(gate.NoemaTransportError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )
    elapsed = time.monotonic() - started

    message = str(exc_info.value)
    assert "outcome must be falsified or confirmed" in message
    assert "NoemaRepairDeadlineExceeded" in message
    assert "wall-clock deadline" in message
    assert elapsed < 1.0
    assert calls == 2
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
'''
    TEST.write_text(text, encoding="utf-8")


def update_docs() -> None:
    replacements = {
        CHANGELOG: (
            "The one corrective HTTP request has a 15-minute client ceiling while the primary contextual-orchestrator review remains under its no-fixed-inference-timeout contract.",
            "The one corrective attempt has a 15-minute absolute wall-clock deadline across open/read/decode/validation while the primary contextual-orchestrator review remains under its no-fixed-inference-timeout contract; unlike a urllib socket timeout, trickling response activity cannot renew that budget.",
        ),
        ARCHITECTURE: (
            "but is capped at 15 minutes because it repairs an\nalready-completed verdict rather than performing a second unbounded full\nreview.",
            "but has one 15-minute process-level wall-clock deadline across open, read,\ndecode, and deterministic validation because it repairs an already-completed\nverdict rather than performing a second unbounded full review. This is not a\nsocket inactivity timeout, so response activity cannot renew the budget.",
        ),
        BASELINE: (
            "the one corrective request has a 900-second hard client ceiling;",
            "the one corrective attempt has a 900-second absolute wall-clock deadline across open/read/decode/validation (not a renewable socket timeout);",
        ),
        DOCTORING: (
            "The *single corrective request* is different: it repairs an already-completed verdict and therefore has a hard 900-second `urllib` client timeout.",
            "The *single corrective attempt* is different: it repairs an already-completed verdict and therefore has one 900-second process-level wall-clock deadline across open/read/decode/validation. It deliberately does not use `urllib`'s renewable socket-operation timeout.",
        ),
    }
    for path, (old, new) in replacements.items():
        text = path.read_text(encoding="utf-8")
        text = replace_once(text, old, new, str(path))
        path.write_text(text, encoding="utf-8")


def main() -> None:
    update_source()
    update_tests()
    update_docs()


if __name__ == "__main__":
    main()
