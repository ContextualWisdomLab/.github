"""An unattested discovery provider is excluded from the pool, not fatal.

``register_review_credentials(os.environ)`` registers every accepted provider
credential the sidecar job environment happens to carry, and the vendored
gateway ships provider sources this repository has not attested for retention
posture. Submitting such a row to
``contextual_orchestrator_review_policy.parse_discovery_report`` raises
``PolicyError``, which would take the whole review sidecar down rather than
merely refusing that provider. These tests pin the launcher-side exclusion and
the policy-side strictness it protects, so neither half can drift alone.
"""

from __future__ import annotations

import importlib
import io
import contextlib

from scripts.ci import zdr_policy
from scripts.ci.contextual_orchestrator_review_policy import (
    PolicyError,
    parse_discovery_report,
)

_launcher = importlib.import_module("scripts.ci.contextual_orchestrator_review_launcher")


class _Row:
    """Minimal stand-in for one ``contextual_orchestrator`` discovery result."""

    def __init__(
        self,
        provider_name: str,
        model_id: str,
        chat_base_url: str = "",
        credential_name: str = "",
        auth_scheme: str = "",
    ) -> None:
        """Record the discovery fields ``_report_rows`` reads."""
        self.provider_name = provider_name
        self.model_id = model_id
        self.chat_base_url = chat_base_url
        self.credential_name = credential_name
        self.auth_scheme = auth_scheme
        self.evidence_only = False


def _report_rows(models: list[object]) -> tuple[list[dict[str, object]], str]:
    """Run the production row builder and return its rows plus captured stderr."""
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        rows = _launcher._report_rows(models, frozenset())
    return rows, captured.getvalue()


def test_opencode_zen_is_not_registered_in_the_org_zdr_policy_table() -> None:
    """The premise: the gateway's OpenCode sources have no org attestation."""
    assert "opencode_zen" not in zdr_policy.PROVIDER_CREDENTIAL_NAMES
    assert "opencode_go" not in zdr_policy.PROVIDER_CREDENTIAL_NAMES


def test_unattested_provider_row_is_dropped_with_a_bounded_diagnostic() -> None:
    """An unattested provider never reaches the policy, and says so once."""
    rows, stderr = _report_rows(
        [_Row("opencode_zen", "grok-code", "https://opencode.ai/zen/v1", "OPENCODE_ZEN_API_KEY", "Bearer")]
    )
    assert rows == []
    assert (
        "discovery_row_skipped_unattested_provider provider=opencode_zen model=grok-code"
        in stderr
    )


def test_the_diagnostic_carries_no_credential_value() -> None:
    """The bounded line names provider and model only -- never a secret."""
    _rows, stderr = _report_rows(
        [_Row("opencode_go", "some-model", "https://opencode.ai/zen/go/v1", "OPENCODE_ZEN_API_KEY", "Bearer")]
    )
    assert "OPENCODE_ZEN_API_KEY" not in stderr
    assert stderr.count("discovery_row_skipped_unattested_provider") == 1


def test_an_attested_provider_alongside_it_still_reaches_the_pool() -> None:
    """Excluding one provider must not drop the rest of the discovery batch."""
    rows, _stderr = _report_rows(
        [
            _Row("opencode_zen", "grok-code", "https://opencode.ai/zen/v1", "OPENCODE_ZEN_API_KEY", "Bearer"),
            _Row(
                "nvidia_nim",
                "meta/llama-3.2-11b",
                "https://integrate.api.nvidia.com/v1",
                "NVIDIA_NIM_API_KEY",
                "Bearer",
            ),
        ]
    )
    assert [row["provider"] for row in rows] == ["nvidia_nim"]
    assert rows[0]["model"] == "meta/llama-3.2-11b"


def test_attested_rows_are_untouched_when_nothing_is_unattested() -> None:
    """The guard is inert for a batch the org policy table already covers."""
    rows, stderr = _report_rows(
        [
            _Row(
                "nvidia_nim",
                "meta/llama-3.2-11b",
                "https://integrate.api.nvidia.com/v1",
                "NVIDIA_NIM_API_KEY",
                "Bearer",
            )
        ]
    )
    assert len(rows) == 1
    assert "discovery_row_skipped_unattested_provider" not in stderr


def test_the_policy_keeps_raising_for_a_row_that_does_reach_it() -> None:
    """The launcher guard protects the policy; it does not relax the policy."""
    report = {
        "models": [
            {
                "provider": "opencode_zen",
                "model": "grok-code",
                "is_free": True,
                "base_url": "https://opencode.ai/zen/v1",
                "credential_key": "OPENCODE_ZEN_API_KEY",
                "auth_scheme": "Bearer",
            }
        ]
    }
    try:
        parse_discovery_report(report)
    except PolicyError as exc:
        assert "not registered in the ZDR policy table" in str(exc)
    else:  # pragma: no cover - the policy must stay fail-closed
        raise AssertionError("parse_discovery_report accepted an unattested provider")
