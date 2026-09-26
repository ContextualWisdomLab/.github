"""The launcher admits nominated free routes only when they are servable free now."""

from __future__ import annotations

import contextlib
import enum
from types import SimpleNamespace

import pytest

from scripts.ci.contextual_orchestrator_review_launcher import (
    FREE_EVIDENCE_REQUIRED_PROVIDERS_FALLBACK,
    PER_CALL_FREE_EVIDENCE,
    REVIEW_FREE_EVIDENCE_MAX_PROBES,
    _free_now_models,
    _nominated_free_models,
    _report_rows,
)
from scripts.ci.contextual_orchestrator_review_policy import (
    COST_FREE,
    COST_PRICED,
    PolicyError,
    parse_discovery_report,
)


class _Verdict(str, enum.Enum):
    FREE = "free"
    PAID = "paid"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class _Ledger:
    def __init__(self) -> None:
        self.verdicts: dict[tuple[str, str], _Verdict] = {}

    def record(self, provider: str, model: str, verdict: _Verdict) -> None:
        self.verdicts[(provider, model)] = verdict

    def verdict(self, provider: str, model: str) -> _Verdict | None:
        return self.verdicts.get((provider, model))

    def probe_due(self, provider: str, model: str) -> bool:
        # The real ledger also re-opens non-FREE routes after 00:00 UTC; the
        # launcher runs in a fresh process, so "never observed" is the case here.
        return (provider, model) not in self.verdicts


def _evidence_module() -> SimpleNamespace:
    """Mirror contextual_orchestrator.free_serving_evidence's public contract."""
    ledger = _Ledger()
    required = frozenset({"experiential_labs"})

    def admitted(provider, model, *, catalog_free):
        verdict = ledger.verdict(provider, model)
        if provider in required:
            return verdict is _Verdict.FREE
        return bool(catalog_free) and verdict not in {_Verdict.PAID, _Verdict.EXHAUSTED}

    def probe_free_candidates(models, *, probe, max_probes):
        probed = []
        for model in models:
            if len(probed) >= max_probes:
                break
            key = (model.provider_name, model.model_id)
            nominated = getattr(model, "is_free", False) or getattr(model, "free_promotion", False)
            if key[0] not in required or not nominated or not ledger.probe_due(*key):
                continue
            probed.append("/".join(key))
            with contextlib.suppress(Exception):  # mirrors the real module
                probe(model)
            if ledger.verdict(*key) is None:
                ledger.record(*key, _Verdict.UNKNOWN)
        return {"probes": len(probed), "probed": probed}

    return SimpleNamespace(
        COST_EVIDENCE_REQUIRED_PROVIDERS=required,
        FREE_SERVING_LEDGER=ledger,
        CostVerdict=_Verdict,
        free_serving_admitted=admitted,
        probe_free_candidates=probe_free_candidates,
    )


def _model(
    provider: str, model_id: str, *, is_free: bool = True, free_promotion: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        provider_name=provider,
        model_id=model_id,
        is_free=is_free,
        free_promotion=free_promotion,
        prompt_price_per_1k=0.0 if is_free else 0.5,
        completion_price_per_1k=0.0 if is_free else 1.5,
        currency_code="USD",
    )


def test_without_the_orchestrator_signal_experiential_is_treated_as_paid() -> None:
    """Fail closed when the pinned orchestrator has no per-call cost signal."""
    models = [
        _model("experiential_labs", "promo"),
        _model("experiential_labs", "promoted", is_free=False, free_promotion=True),
        _model("openrouter", "m:free"),
    ]

    kept, report = _free_now_models(models, evidence=None, probe=None)

    assert [m.provider_name for m in kept] == ["openrouter"]
    assert "experiential_labs" in FREE_EVIDENCE_REQUIRED_PROVIDERS_FALLBACK
    assert report == {
        "signal": "unavailable",
        "probes": 0,
        "probed": [],
        "probe_skipped": None,
        "withheld": [
            {"provider": "experiential_labs", "model": "promo", "reason": "no_signal"},
            {"provider": "experiential_labs", "model": "promoted", "reason": "no_signal"},
        ],
    }


def test_a_pin_without_probe_support_is_also_fail_closed() -> None:
    evidence = _evidence_module()
    del evidence.probe_free_candidates
    evidence.FREE_SERVING_LEDGER.record("experiential_labs", "promo", _Verdict.FREE)

    kept, report = _free_now_models(
        [_model("experiential_labs", "promo"), _model("openrouter", "m:free")],
        evidence=evidence,
        probe=lambda _model: None,
    )

    assert [m.model_id for m in kept] == ["m:free"]
    assert report["signal"] == "unavailable"


def test_promotion_nominees_join_zero_priced_rows_once() -> None:
    zero = _model("openrouter", "m:free")
    promoted = _model("experiential_labs", "promo", is_free=False, free_promotion=True)
    priced = _model("experiential_labs", "paid", is_free=False)
    duplicate = _model("openrouter", "m:free", free_promotion=True)

    nominated = _nominated_free_models([zero, promoted, priced, duplicate], [zero])

    assert nominated == [zero, promoted]


def test_zero_cost_probe_admits_and_positive_cost_or_quota_withholds() -> None:
    evidence = _evidence_module()
    costs = {
        "free-now": _Verdict.FREE,
        "overflowing": _Verdict.PAID,
        "quota-429": _Verdict.EXHAUSTED,
    }
    probed: list[str] = []

    def probe(model):
        probed.append(model.model_id)
        if model.model_id == "transport-error":
            raise RuntimeError("connection reset")
        if model.model_id in costs:
            evidence.FREE_SERVING_LEDGER.record(
                model.provider_name, model.model_id, costs[model.model_id]
            )

    models = [
        _model("experiential_labs", "free-now", is_free=False, free_promotion=True),
        _model("experiential_labs", "overflowing"),
        _model("experiential_labs", "quota-429"),
        _model("experiential_labs", "transport-error"),
        _model("openrouter", "m:free"),
    ]
    kept, report = _free_now_models(models, evidence=evidence, probe=probe)

    assert [m.model_id for m in kept] == ["free-now", "m:free"]
    assert probed == ["free-now", "overflowing", "quota-429", "transport-error"]
    assert report["signal"] == "free_serving_evidence"
    assert report["probes"] == 4
    assert report["probed"] == [f"experiential_labs/{name}" for name in probed]
    assert report["withheld"] == [
        {"provider": "experiential_labs", "model": "overflowing", "reason": "cost_paid"},
        {"provider": "experiential_labs", "model": "quota-429", "reason": "cost_exhausted"},
        {"provider": "experiential_labs", "model": "transport-error", "reason": "cost_unknown"},
    ]


def test_probe_budget_is_bounded_and_unprobed_routes_stay_paid() -> None:
    evidence = _evidence_module()
    calls: list[str] = []

    def probe(model):
        calls.append(model.model_id)
        evidence.FREE_SERVING_LEDGER.record(model.provider_name, model.model_id, _Verdict.FREE)

    models = [
        _model("experiential_labs", f"m{index}")
        for index in range(REVIEW_FREE_EVIDENCE_MAX_PROBES + 2)
    ]
    kept, report = _free_now_models(models, evidence=evidence, probe=probe)

    assert len(calls) == REVIEW_FREE_EVIDENCE_MAX_PROBES
    assert len(kept) == REVIEW_FREE_EVIDENCE_MAX_PROBES
    assert [row["reason"] for row in report["withheld"]] == ["no_evidence", "no_evidence"]


def test_existing_verdicts_are_reused_and_demote_catalog_free_routes() -> None:
    evidence = _evidence_module()
    evidence.FREE_SERVING_LEDGER.record("experiential_labs", "known", _Verdict.FREE)
    evidence.FREE_SERVING_LEDGER.record("experiential_labs", "spent", _Verdict.EXHAUSTED)
    evidence.FREE_SERVING_LEDGER.record("openrouter", "m:free", _Verdict.PAID)

    def probe(model):  # pragma: no cover - must not be called
        raise AssertionError(f"unexpected probe for {model.model_id}")

    kept, report = _free_now_models(
        [
            _model("experiential_labs", "known"),
            _model("experiential_labs", "spent"),
            _model("openrouter", "m:free"),
        ],
        evidence=evidence,
        probe=probe,
    )

    assert [m.model_id for m in kept] == ["known"]
    assert report["probes"] == 0
    assert report["withheld"] == [
        {"provider": "experiential_labs", "model": "spent", "reason": "cost_exhausted"},
        {"provider": "openrouter", "model": "m:free", "reason": "cost_paid"},
    ]


def test_per_call_free_rows_drop_list_prices_and_parse_as_free() -> None:
    promoted = _model("experiential_labs", "promo", is_free=False, free_promotion=True)
    zero = _model("openrouter", "m:free")
    identities = frozenset({("experiential_labs", "promo"), ("openrouter", "m:free")})

    rows = _report_rows(
        [promoted, zero], identities, frozenset({("experiential_labs", "promo")})
    )

    assert rows[0]["free_evidence"] == PER_CALL_FREE_EVIDENCE
    assert rows[0]["is_free"] is True
    assert (
        rows[0]["prompt_price_per_1k"],
        rows[0]["completion_price_per_1k"],
        rows[0]["currency_code"],
    ) == (None, None, None)
    assert "free_evidence" not in rows[1]
    parsed = parse_discovery_report({"models": rows})
    assert [row["cost_evidence"] for row in parsed] == [COST_FREE, COST_FREE]
    assert parsed[0]["non_token_price_evidence"] == {
        "source": "usage.cost",
        "price": 0.0,
        "unit": "per_call",
    }
    assert parsed[1]["non_token_price_evidence"] is None


def _experiential_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "provider": "experiential_labs",
        "model": "promo",
        "is_free": True,
        "prompt_price_per_1k": None,
        "completion_price_per_1k": None,
        "currency_code": None,
        "credential_key": "EXPERIENTIAL_LABS_API_KEY",
        "free_evidence": PER_CALL_FREE_EVIDENCE,
    }
    row.update(overrides)
    return row


def test_policy_honours_the_marker_only_for_free_evidence_required_rows() -> None:
    # Without the marker a free row with no token prices stays unknown.
    unmarked = parse_discovery_report({"models": [_experiential_row(free_evidence=None)]})
    assert unmarked[0]["cost_evidence"] == "unknown"
    # A marker on a non-free row is ignored (list prices decide).
    priced = parse_discovery_report(
        {
            "models": [
                _experiential_row(
                    is_free=False,
                    prompt_price_per_1k=0.5,
                    completion_price_per_1k=1.5,
                    currency_code="USD",
                )
            ]
        }
    )
    assert priced[0]["cost_evidence"] == COST_PRICED
    # A marker on a provider outside the per-call set is ignored too.
    other = parse_discovery_report(
        {
            "models": [
                {
                    "provider": "openrouter",
                    "model": "vendor/m",
                    "is_free": True,
                    "prompt_price_per_1k": None,
                    "completion_price_per_1k": None,
                    "free_evidence": PER_CALL_FREE_EVIDENCE,
                }
            ]
        }
    )
    assert other[0]["cost_evidence"] == "unknown"
    # A free marker never launders a conflicting list price.
    with pytest.raises(PolicyError, match="conflicts with its free price marker"):
        parse_discovery_report(
            {
                "models": [
                    {
                        "provider": "openrouter",
                        "model": "vendor/m",
                        "is_free": True,
                        "prompt_price_per_1k": 0.5,
                        "completion_price_per_1k": 1.5,
                        "currency_code": "USD",
                        "free_evidence": PER_CALL_FREE_EVIDENCE,
                    }
                ]
            }
        )


# --- Round 3: ZDR runs never probe, unexpected pin shapes never abort -----------


def test_probe_skip_reason_sends_no_probe_and_keeps_evidence_routes_paid() -> None:
    evidence = _evidence_module()

    def probe(model):  # pragma: no cover - must not be called
        raise AssertionError(f"unexpected probe for {model.model_id}")

    kept, report = _free_now_models(
        [
            _model("experiential_labs", "promo", is_free=False, free_promotion=True),
            _model("openrouter", "m:free"),
        ],
        evidence=evidence,
        probe=probe,
        probe_skip_reason="require_zdr",
    )

    assert [m.model_id for m in kept] == ["m:free"]
    assert report["probes"] == 0
    assert report["probe_skipped"] == "require_zdr"
    assert report["withheld"] == [
        {"provider": "experiential_labs", "model": "promo", "reason": "no_evidence"}
    ]


def _without(evidence: SimpleNamespace, name: str) -> SimpleNamespace:
    delattr(evidence, name)
    return evidence


def _old_signature(evidence: SimpleNamespace) -> SimpleNamespace:
    evidence.free_serving_admitted = lambda provider, model: True  # no catalog_free kwarg
    return evidence


def _raising_probe_runner(evidence: SimpleNamespace) -> SimpleNamespace:
    def probe_free_candidates(models, *, probe, max_probes):
        raise AttributeError("'DiscoveredModel' object has no attribute 'provider_name'")

    evidence.probe_free_candidates = probe_free_candidates
    return evidence


def _non_mapping_report(evidence: SimpleNamespace) -> SimpleNamespace:
    evidence.probe_free_candidates = lambda models, *, probe, max_probes: ["unexpected"]
    return evidence


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda evidence: _without(evidence, "FREE_SERVING_LEDGER"), "AttributeError"),
        (_old_signature, "TypeError"),
        (_raising_probe_runner, "AttributeError"),
        (_non_mapping_report, "AttributeError"),
    ],
    ids=["missing_ledger", "signature_type_error", "attribute_error", "report_shape"],
)
def test_an_unexpected_pin_shape_withholds_only_evidence_routes(mutate, error) -> None:
    evidence = mutate(_evidence_module())

    kept, report = _free_now_models(
        [
            _model("experiential_labs", "promo"),
            _model("experiential_labs", "promoted", is_free=False, free_promotion=True),
            _model("openrouter", "m:free"),
        ],
        evidence=evidence,
        probe=lambda _model: None,
    )

    assert [m.model_id for m in kept] == ["m:free"]
    assert report["signal"] == "incompatible"
    assert report["signal_error"] == error
    assert report["withheld"] == [
        {"provider": "experiential_labs", "model": "promo", "reason": "no_signal"},
        {"provider": "experiential_labs", "model": "promoted", "reason": "no_signal"},
    ]


def test_the_fallback_provider_set_is_the_policy_set() -> None:
    from scripts.ci import contextual_orchestrator_review_policy as policy

    assert FREE_EVIDENCE_REQUIRED_PROVIDERS_FALLBACK is policy.PER_CALL_COST_EVIDENCE_PROVIDERS
    assert PER_CALL_FREE_EVIDENCE == policy.PER_CALL_FREE_EVIDENCE


def _stub_orchestrator(monkeypatch, *, probe_verdict: _Verdict) -> SimpleNamespace:
    """Install a minimal vendored-orchestrator stub so ``main()`` runs to selection."""
    import sys
    import types

    from scripts.ci import contextual_orchestrator_review_launcher as launcher

    evidence = _evidence_module()
    calls = SimpleNamespace(probe_runner=0, sent=[], clients=[])
    real_runner = evidence.probe_free_candidates

    def probe_free_candidates(models, *, probe, max_probes):
        calls.probe_runner += 1
        return real_runner(models, probe=probe, max_probes=max_probes)

    evidence.probe_free_candidates = probe_free_candidates

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            calls.clients.append(kwargs)

        def proxy_send_once(self, agent, endpoint, payload):
            calls.sent.append((agent, endpoint, payload["model"]))
            evidence.FREE_SERVING_LEDGER.record("experiential_labs", payload["model"], probe_verdict)
            return {}

    promo = SimpleNamespace(
        provider_name="experiential_labs",
        model_id="promo",
        is_free=False,
        free_promotion=True,
        output_modalities=("text",),
        prompt_price_per_1k=0.5,
        completion_price_per_1k=1.5,
        currency_code="USD",
    )
    modules = {
        "contextual_orchestrator": types.ModuleType("contextual_orchestrator"),
        "contextual_orchestrator.credentials": SimpleNamespace(get_credential=lambda _name: "tok"),
        "contextual_orchestrator.chat_capability": SimpleNamespace(
            is_general_chat_agent_model_id=lambda _model_id: True
        ),
        "contextual_orchestrator.model_discovery": SimpleNamespace(
            agent_from_discovered=lambda model: f"agent:{model.model_id}",
            discover_all_models=lambda: ([promo], []),
            free_discovered_models=lambda models: [m for m in models if m.is_free],
        ),
        "contextual_orchestrator.orchestrator": SimpleNamespace(
            ModelClient=_Client, TaskOrchestrator=object, load_agents=lambda _path: []
        ),
        "contextual_orchestrator.review_gateway": SimpleNamespace(
            REVIEW_AUTH_CREDENTIAL_NAME="REVIEW_AUTH",
            register_review_credentials=lambda _env: ["EXPERIENTIAL_LABS_API_KEY"],
        ),
        "contextual_orchestrator.server": SimpleNamespace(SecurityConfig=object, serve=None),
        "contextual_orchestrator.debug_logging": SimpleNamespace(configure_logging=None),
        "contextual_orchestrator.free_serving_evidence": evidence,
    }
    modules["contextual_orchestrator"].free_serving_evidence = evidence
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(launcher, "_configure_sidecar_logging", lambda _configure: "INFO")
    calls.main = launcher.main
    return calls


def _main_args(tmp_path, *extra: str) -> list[str]:
    return [
        "--discovery-out", str(tmp_path / "discovery.json"),
        "--catalog-out", str(tmp_path / "catalog.json"),
        "--report-out", str(tmp_path / "report.json"),
        "--preflight-out", str(tmp_path / "preflight.json"),
        *extra,
    ]


def test_require_zdr_runs_never_send_a_free_evidence_probe(monkeypatch, tmp_path, capsys) -> None:
    calls = _stub_orchestrator(monkeypatch, probe_verdict=_Verdict.FREE)

    with pytest.raises(SystemExit, match="no eligible models"):
        calls.main(_main_args(tmp_path, "--require-zdr"))

    assert calls.probe_runner == 0
    assert calls.sent == []
    assert "probe_skipped=require_zdr" in capsys.readouterr().err


def test_public_runs_probe_without_a_wall_clock_timeout(monkeypatch, tmp_path, capsys) -> None:
    # A billed probe (cost > 0) demotes the route, so selection still fails closed.
    calls = _stub_orchestrator(monkeypatch, probe_verdict=_Verdict.PAID)

    with pytest.raises(SystemExit, match="no eligible models"):
        calls.main(_main_args(tmp_path))

    assert calls.probe_runner == 1
    assert calls.sent == [("agent:promo", "chat/completions", "promo")]
    # ADR 0003: no fixed inference or connect timeout on the probe client.
    assert "timeout" not in calls.clients[0]
    assert "connect_timeout" not in calls.clients[0]
    assert "probes=1 probe_skipped=no" in capsys.readouterr().err
