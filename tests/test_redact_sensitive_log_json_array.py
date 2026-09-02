"""Regression coverage for _redact_line's fast non-JSON bypass.

_redact_line uses an O(1) first-character check to skip json.loads() (and
its JSONDecodeError exception path) for a line that obviously cannot start a
JSON value. That check must accept every character a valid top-level JSON
document can start with -- object, array, string, number, and the
true/false/null/NaN/Infinity/-Infinity literals Python's json module
accepts -- or a whole-line JSON scalar falls through to the unstructured
text redactor and comes back as malformed JSON instead of being preserved.
"""

import pytest

from scripts.ci.redact_sensitive_log import redact_text


def test_redact_json_array_preserves_array():
    """A JSON array line is still parsed and its sensitive keys redacted."""
    source = '   [{"token": "secret"}]'
    redacted = redact_text(source)
    assert '{"token":"[REDACTED]"}' in redacted


def test_redact_json_array_invalid_json():
    """A line that merely starts with '[' but isn't valid JSON falls back
    to the unstructured redactor unchanged."""
    source = "   [not a json array]"
    redacted = redact_text(source)
    assert redacted == "   [not a json array]"


@pytest.mark.parametrize(
    "scalar",
    [
        '"token=secret123456789"',
        "12345",
        "-12345",
        "3.14",
        "true",
        "false",
        "null",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_redact_json_scalar_line_is_preserved_unchanged(scalar):
    """A whole-line JSON scalar (string, number, or literal) must still be
    parsed as JSON and returned unchanged, not diverted through the
    unstructured text redactor -- which would corrupt it (e.g. a quoted
    string losing its closing quote) since _redact_json never rewrites a
    bare scalar value, only dict keys that match a sensitive pattern."""
    assert redact_text(scalar) == scalar


def test_redact_json_scalar_with_leading_whitespace_still_parses_as_json():
    """Leading whitespace before a JSON scalar must not defeat the fast
    non-JSON check (it strips leading spaces/tabs before inspecting the
    first character, mirroring json.loads()'s own whitespace tolerance),
    so the line is still parsed as JSON -- re-serialized without the
    insignificant leading whitespace -- rather than diverted through the
    unstructured redactor."""
    source = '   "plain string value"'
    assert redact_text(source) == '"plain string value"'


def test_redact_non_json_line_starting_like_a_json_literal_is_unstructured():
    """A plain-text line that happens to start with a JSON-literal prefix
    character (here 't', shared with 'true') but is not valid JSON still
    falls back to the unstructured redactor, and its own credential-shaped
    content is still redacted there."""
    source = "token=secret123456789 not valid json"
    redacted = redact_text(source)
    assert redacted == "token=[REDACTED] not valid json"
