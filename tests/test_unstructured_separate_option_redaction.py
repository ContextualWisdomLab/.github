"""Regression evidence for separate sensitive options echoed in child output."""

from scripts.ci import redact_sensitive_log as redactor


def test_unstructured_output_redacts_separate_sensitive_option_values() -> None:
    """A child that echoes a separate secret option must not disclose its value."""

    assert redactor.redact_text(
        "running tool --api-key ordinary-value --mode safe"
    ) == "running tool --api-key [REDACTED] --mode safe"
