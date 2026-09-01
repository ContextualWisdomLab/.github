#!/usr/bin/env python3
"""Apply the one-shot, test-first Noema model-output repair for PR #1617.

This helper exists only to make an exact, reviewable transformation on the
single-writer PR branch. The workflow that invokes it deletes this helper and
itself before committing the production repair.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/noema_review_gate.py"
TEST = ROOT / "tests/test_noema_model_output_failure_classification.py"
CHANGELOG = ROOT / "CHANGELOG.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
DOCTORING = ROOT / "docs/doctoring/noema-model-output-repair-boundary.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment and fail closed on drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_raises_between(text: str, start: str, end: str) -> str:
    """Retype model-output validation errors within one bounded source span."""
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    span = text[start_index:end_index]
    if "raise RuntimeError(" not in span:
        raise RuntimeError(f"{start.strip()}: no RuntimeError raises found")
    span = span.replace("raise RuntimeError(", "raise NoemaModelOutputError(")
    return text[:start_index] + span + text[end_index:]


def update_source() -> None:
    """Implement typed model-output failures and a bounded one-time repair call."""
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'ORCHESTRATOR_BASE_ENV = "CONTEXTUAL_ORCHESTRATOR_BASE_URL"\n',
        'ORCHESTRATOR_BASE_ENV = "CONTEXTUAL_ORCHESTRATOR_BASE_URL"\n'
        '# A repair request corrects an already-completed model verdict; it is not a\n'
        '# second unbounded full review. Fifteen minutes is the hard client-side\n'
        '# ceiling for that one corrective HTTP request. The primary review remains\n'
        '# governed by contextual-orchestrator rather than a fixed inference timeout.\n'
        'NOEMA_REPAIR_TIMEOUT_SECONDS = 15 * 60\n\n\n'
        'class NoemaModelOutputError(RuntimeError):\n'
        '    """Raised when untrusted model output violates the trusted verdict contract."""\n\n\n'
        'class NoemaTransportError(RuntimeError):\n'
        '    """Raised when the bounded review transport cannot produce usable evidence."""\n',
        "typed Noema error classes",
    )

    text = replace_raises_between(
        text,
        "def validate_substantive_verdict(\n",
        "\ndef truncate_text(",
    )
    text = replace_raises_between(text, "def extract_json_object(", "\ndef extract_llm_message_content(")
    text = replace_raises_between(
        text,
        "def extract_llm_message_content(",
        "\ndef decode_llm_response_body(",
    )
    text = replace_raises_between(
        text,
        "def decode_llm_response_body(",
        "\ndef _truthy_env(",
    )

    # Retype the immediate post-response verdict-shape checks. These are all
    # model-output/schema failures, not GitHub/source or transport failures.
    for old, new in (
        (
            'raise RuntimeError(f"Noema LLM returned unsupported decision: {decision!r}")',
            'raise NoemaModelOutputError(f"Noema LLM returned unsupported decision: {decision!r}")',
        ),
        (
            'raise RuntimeError("Noema LLM response did not contain a substantive summary")',
            'raise NoemaModelOutputError("Noema LLM response did not contain a substantive summary")',
        ),
        (
            'raise RuntimeError("Noema LLM response findings must be a list of objects")',
            'raise NoemaModelOutputError("Noema LLM response findings must be a list of objects")',
        ),
        (
            'raise RuntimeError("Noema LLM response contained a malformed finding")',
            'raise NoemaModelOutputError("Noema LLM response contained a malformed finding")',
        ),
        (
            'raise RuntimeError("Noema LLM request_changes response did not contain a substantive finding")',
            'raise NoemaModelOutputError("Noema LLM request_changes response did not contain a substantive finding")',
        ),
    ):
        text = replace_once(text, old, new, old)

    text = replace_once(
        text,
        """        with opener.open(request) as response:  # nosec B310\n            raw_bytes = response.read()\n""",
        """        if is_retry:\n            response_context = opener.open(  # nosec B310\n                request, timeout=NOEMA_REPAIR_TIMEOUT_SECONDS\n            )\n        else:\n            response_context = opener.open(request)  # nosec B310\n        with response_context as response:\n            raw_bytes = response.read()\n""",
        "bounded repair HTTP timeout",
    )

    text = replace_once(
        text,
        """    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:\n        if is_retry:\n            if isinstance(exc, RuntimeError):\n                raise\n            raise RuntimeError(str(exc)) from exc\n        if str(fetch_pr(repo, number).get(\"headRefOid\") or \"\").lower() != expected_head:\n            raise StaleHeadDuringRepairRetryError(\n                \"Pull request head changed during review; stale before repair retry.\"\n            ) from exc\n        return call_llm(\n            repo,\n            number,\n            pr,\n            diff,\n            truncated,\n            expected_head,\n            review_context,\n            changed_paths,\n            str(exc),\n            is_retry=True,\n        )\n""",
        """    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:\n        current_failure = scrub_sensitive_data(str(exc)) or type(exc).__name__\n        if is_retry:\n            initial_failure = (\n                scrub_sensitive_data(repair_error)\n                or \"no diagnostic message was available\"\n            )\n            if isinstance(exc, NoemaModelOutputError):\n                raise NoemaModelOutputError(\n                    \"Noema model-output repair remained invalid; \"\n                    f\"initial failure: {initial_failure}; repair failure: {current_failure}\"\n                ) from exc\n            if isinstance(\n                exc, (urllib.error.URLError, http.client.HTTPException, OSError)\n            ):\n                raise NoemaTransportError(\n                    \"Noema bounded repair transport was exhausted; \"\n                    f\"initial failure: {initial_failure}; repair failure: \"\n                    f\"{type(exc).__name__}: {current_failure}\"\n                ) from exc\n            raise RuntimeError(\n                \"Noema repair failed closed; \"\n                f\"initial failure: {initial_failure}; repair failure: {current_failure}\"\n            ) from exc\n        if str(fetch_pr(repo, number).get(\"headRefOid\") or \"\").lower() != expected_head:\n            raise StaleHeadDuringRepairRetryError(\n                \"Pull request head changed during review; stale before repair retry.\"\n            ) from exc\n        return call_llm(\n            repo,\n            number,\n            pr,\n            diff,\n            truncated,\n            expected_head,\n            review_context,\n            changed_paths,\n            current_failure,\n            is_retry=True,\n        )\n""",
        "typed repair exhaustion",
    )

    text = text.replace(
        "Fails closed with ``RuntimeError``",
        "Fails closed with ``NoemaModelOutputError``",
    )
    SOURCE.write_text(text, encoding="utf-8")


def update_tests() -> None:
    """Extend the pre-existing RED with timeout and evidence-preservation coverage."""
    text = TEST.read_text(encoding="utf-8")
    marker = "def test_bounded_repair_preserves_initial_schema_and_transport_evidence"
    if marker in text:
        raise RuntimeError("#1617 repair tests already present")
    text += r'''


def test_bounded_repair_preserves_initial_schema_and_transport_evidence(monkeypatch) -> None:
    """A malformed verdict followed by 502 keeps both typed evidence classes."""
    import json
    import urllib.error

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "a" * 40
    requests: list[tuple[object, dict]] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    def open_response(_opener, request, **kwargs):
        requests.append((request, kwargs))
        if len(requests) == 1:
            return Response()
        raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(
        gate,
        "fetch_pr",
        lambda _repo, _number: {"headRefOid": head_sha},
    )

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

    message = str(exc_info.value)
    assert "outcome must be falsified or confirmed" in message
    assert "HTTPError" in message
    assert "502" in message
    assert len(requests) == 2
    assert requests[0][1] == {}
    assert requests[1][1]["timeout"] == gate.NOEMA_REPAIR_TIMEOUT_SECONDS


def test_repeated_model_output_failure_remains_typed(monkeypatch) -> None:
    """A second malformed verdict fails closed as model-output evidence."""
    import json

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    head_sha = "b" * 40

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(_verdict())}}]}
            ).encode()

    monkeypatch.setattr(
        gate.urllib.request.OpenerDirector,
        "open",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(
        gate,
        "fetch_pr",
        lambda _repo, _number: {"headRefOid": head_sha},
    )

    with pytest.raises(gate.NoemaModelOutputError) as exc_info:
        gate.call_llm(
            "owner/repo",
            7,
            {"title": "test", "headRefOid": head_sha},
            DIFF,
            False,
            head_sha,
            changed_paths=("README.md",),
        )

    assert "initial failure" in str(exc_info.value)
    assert "repair failure" in str(exc_info.value)
'''
    TEST.write_text(text, encoding="utf-8")


def update_docs() -> None:
    """Record the RCA, bounded contract, and architecture consequence."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry = """- **Classify and bound Noema malformed-verdict repair failures (#1611/#1617).** A schema-invalid model verdict now raises typed `NoemaModelOutputError` evidence instead of an undifferentiated runtime failure. The one corrective HTTP request has a 15-minute client ceiling while the primary contextual-orchestrator review remains under its no-fixed-inference-timeout contract. If the repair then fails at transport, `NoemaTransportError` preserves the first validator diagnostic plus the later transport class/status without logging raw model output or secrets.\n"""
    changelog = replace_once(changelog, "## [Unreleased]\n", "## [Unreleased]\n" + entry, "changelog unreleased")
    CHANGELOG.write_text(changelog, encoding="utf-8")

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    architecture_note = """

### Noema model-output and repair boundary

Noema separates deterministic model-output/schema failures from GitHub/source
findings and provider transport exhaustion. A malformed verdict remains
non-passing and is represented by `NoemaModelOutputError`. Its single corrective
request still routes only through the loopback contextual-orchestrator
`orchestrator/free` gateway, but is capped at 15 minutes because it repairs an
already-completed verdict rather than performing a second unbounded full
review. If that corrective request encounters transport exhaustion, the typed
transport error retains both the first trusted-validator diagnostic and the
later transport class/status while omitting raw model content and secrets.
"""
    if "### Noema model-output and repair boundary" not in architecture:
        architecture += architecture_note
    ARCHITECTURE.write_text(architecture, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline_note = """

## 2026-09-01 Noema malformed-verdict retry classification and wall-clock bound (#1611/#1617)

- **Observed consumer evidence:** `ContextualWisdomLab/naruon#1505@7da2a242e463f59d4580cb38e7591f1ba4b4049e`, Required Noema run `33460498090` / job `99742587317`. The first response reached the trusted semantic validator but used an out-of-domain adversarial-probe `outcome`; the generic repair attempt later ended as HTTP 502 after roughly 88 minutes.
- **Root cause:** model-output/schema rejection, repair transport exhaustion, and consumer-source findings shared an undifferentiated `RuntimeError` boundary. The corrective HTTP request also had no client-side repair-specific ceiling, so a malformed first verdict could initiate another effectively full-duration request.
- **Repair:** model-output/schema rejection is typed as `NoemaModelOutputError`; the one corrective request has a 900-second hard client ceiling; repair transport exhaustion is typed as `NoemaTransportError`; and the final fail-closed diagnostic preserves the sanitized first validator error plus the later typed transport evidence. Primary review inference remains governed by contextual-orchestrator `orchestrator/free` and is not given a new fixed model-inference timeout.
- **Security/operability invariant:** raw model content, credentials, and provider secrets are never included in the combined diagnostic. Exact-head revalidation still occurs before retry and before publication. No direct-provider fallback or GitHub authority change is introduced.
- **Verification contract:** deterministic tests cover the original invalid `outcome`, malformed-then-502 evidence preservation and the repair-only timeout, and repeated malformed model output remaining typed and non-passing. The affected Naruon head must be re-run after protected integration; predecessor review/check evidence does not transfer.
"""
    if "## 2026-09-01 Noema malformed-verdict retry classification" not in baseline:
        baseline += baseline_note
    BASELINE.write_text(baseline, encoding="utf-8")

    DOCTORING.parent.mkdir(parents=True, exist_ok=True)
    DOCTORING.write_text(
        """# Noema model-output repair boundary\n\n## Incident\n\nOn 2026-09-01 the required Noema review for `ContextualWisdomLab/naruon#1505` reached deterministic verdict validation, rejected an adversarial-probe `outcome` outside the closed `falsified|confirmed` domain, then spent the repair path on a long second model call that ultimately surfaced only `HTTP 502 Bad Gateway`. That final transport symptom erased the more informative first trusted-validator failure from the top-level diagnostic.\n\n## Decision\n\n1. Model-produced JSON/envelope/schema/semantic-contract failures are `NoemaModelOutputError`; they remain fail-closed and are not consumer-source findings.\n2. The primary review keeps the accepted contextual-orchestrator no-fixed-inference-timeout contract. The *single corrective request* is different: it repairs an already-completed verdict and therefore has a hard 900-second `urllib` client timeout.\n3. A corrective transport failure is `NoemaTransportError` and carries the sanitized first validator diagnostic plus the later transport exception class/status. Raw model output is never copied into public Actions diagnostics.\n4. Exact-head validation before retry and before publication remains mandatory. All model traffic remains on contextual-orchestrator `orchestrator/free`.\n\n## Verification\n\nThe #1617 regression first proved RED because `NoemaModelOutputError` did not exist. The repair adds focused cases for malformed-verdict typing, malformed-then-502 evidence preservation with the 900-second repair-only timeout, and repeated malformed output remaining typed and non-passing. The repository full coverage/docstring gate is run before the one-shot repair workflow commits the result.\n\n## References\n\nFielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). Internet Engineering Task Force.\n\nPython Software Foundation. (2026). *urllib.request — Extensible library for opening URLs*. Python 3 documentation.\n""",
        encoding="utf-8",
    )


def main() -> None:
    """Apply all production, regression, and traceability changes."""
    update_source()
    update_tests()
    update_docs()


if __name__ == "__main__":
    main()
