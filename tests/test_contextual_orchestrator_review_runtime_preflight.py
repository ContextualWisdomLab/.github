"""Collect runtime-preflight regressions under the no-heuristics contract.

The adjacent case module preserves historical regression evidence. This shim
continues to execute findings that remain semantically valid while excluding
oracles whose *expected behavior* was the retired priced fallback, 16->4096
token escalation, explicit serving-generation knobs, or bounded inference-retry
policy. Those cases are replaced by the executable fail-closed contract in
``test_contextual_orchestrator_review_no_heuristic_compute.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path


_CASES_PATH = Path(__file__).with_name(
    "_contextual_orchestrator_review_runtime_preflight_cases.py"
)
_CASES = runpy.run_path(str(_CASES_PATH))
_LAUNCHER = Path(__file__).resolve().parents[1] / "scripts/ci/contextual_orchestrator_review_launcher.py"


def _retired_heuristic_oracle(name: str) -> bool:
    """Identify historical tests whose asserted policy is now forbidden.

    This is test collection only, never a production decision rule. The
    underlying historical cases remain in-tree as incident evidence; executable
    replacements assert one provider-default observation and fail-closed output.
    """
    exact = {
        "test_preflight_transport_has_no_inference_timeout_and_is_provider_neutral",
        "test_preflight_mirrors_runtime_request_and_keeps_only_compatible_routes",
        "test_gateway_preflight_max_tokens_is_synchronized_with_the_routing_probe",
        "test_gateway_preflight_retries_transport_failures_up_to_a_bounded_attempt_count",
        "test_reasoning_without_content_escalates_then_still_fails_closed_if_unresolved",
        "test_finish_reason_length_escalates_and_can_succeed",
        "test_preflight_uses_priced_fallback_only_after_primary_routes_reject",
        "test_fallback_escalation_is_independent_of_primary_catalog_order",
        "test_preflight_keeps_more_than_twelve_admitted_primary_routes",
        "test_auto_fallback_keeps_all_admitted_routes_after_primary_failure",
        "test_sidecar_preserves_diagnostics_and_probes_the_real_gateway",
        "test_every_budget_starved_route_gets_its_own_escalation",
    }
    return (
        name in exact
        or name.startswith("test_gateway_retry_loop_")
        or name.startswith("test_escalated_probe_")
    )


for _name, _value in _CASES.items():
    if not _name.startswith("__") and not _retired_heuristic_oracle(_name):
        globals()[_name] = _value


def test_preflight_transport_has_no_inference_timeout_or_compute_defaults() -> None:
    """Central review inference supplies no repository-authored TTC policy."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES" not in launcher
    assert "REVIEW_MAX_OUTPUT_TOKENS" not in launcher
    assert "REVIEW_TEMPERATURE" not in launcher
    assert "REVIEW_PREFLIGHT_BASE_TOKENS" not in launcher
    assert "REVIEW_PREFLIGHT_ESCALATED_TOKENS" not in launcher
    assert launcher.count("timeout=None") == 2
    assert launcher.count("max_retries=0") == 2
    assert "max_output_tokens=" not in launcher
    assert "temperature=" not in launcher
