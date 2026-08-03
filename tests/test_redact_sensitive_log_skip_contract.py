"""Regression tests for the log-redaction parser's skip-index optimization."""

from __future__ import annotations

import pytest

from scripts.ci import redact_sensitive_log as redactor


def _base_style_redact_assignments(text: str) -> str:
    """Reproduce the base branch's one-character failure-path advancement."""
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        replacement, next_cursor = redactor._consume_sensitive_assignment(text, cursor)
        if replacement is None:
            output.append(text[cursor])
            cursor += 1
            continue
        output.append(replacement)
        cursor = next_cursor
    return "".join(output)


@pytest.mark.parametrize(
    "source",
    [
        "foopassword=supersecret",
        "xxapi_key=TOPSECRET",
        "not_asecret=value",
        '"api_key=secret',
        "1password=secret",
        "safe=value password=secret",
        "ordinary diagnostic text",
        "",
        '"',
        "'",
    ],
)
def test_skip_index_matches_base_failure_path_on_adversarial_inputs(source: str) -> None:
    """Skipping a rejected key run must preserve the base parser's redaction output."""
    assert redactor._redact_assignments(source) == _base_style_redact_assignments(source)


def test_sensitive_key_search_is_unanchored_for_shifted_key_runs() -> None:
    """A rejected full key cannot contain a suffix that newly matches the key pattern."""
    for key in ("foopassword", "xxapi_key", "not_asecret"):
        assert redactor.SENSITIVE_KEY_RE.search(key) is not None


def test_shifted_and_malformed_sensitive_keys_remain_redacted() -> None:
    """Shifted, digit-prefixed, and malformed quoted keys never expose their values."""
    expected = redactor.REDACTED
    assert redactor._redact_unstructured("foopassword=supersecret") == (
        f"foopassword={expected}"
    )
    assert redactor._redact_unstructured("xxapi_key=TOPSECRET") == (
        f"xxapi_key={expected}"
    )
    assert redactor._redact_unstructured('"api_key=secret') == (
        f'"api_key={expected}'
    )
    assert redactor._redact_unstructured("1password=secret") == (
        f"1password={expected}"
    )
