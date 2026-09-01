"""One-shot source repair driver for PR #1629; removed by the repair workflow."""

from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source contract or fail before writing partial output."""
    if old not in text:
        raise SystemExit(f"missing repair anchor: {label}")
    return text.replace(old, new, 1)


def repair_launcher() -> None:
    """Make full-catalog startup non-additive while preserving source evidence order."""
    path = Path("scripts/ci/contextual_orchestrator_review_launcher.py")
    text = path.read_text(encoding="utf-8")
    if "from concurrent.futures import ThreadPoolExecutor" not in text:
        text = replace_once(
            text,
            "import argparse\nimport json",
            "import argparse\nfrom concurrent.futures import ThreadPoolExecutor\nimport json",
            "launcher concurrent-futures import",
        )

    start = text.index("def _preflight_review_agents(")
    end = text.index("\ndef _preflight_with_fallback(", start)
    replacement = '''def _preflight_review_agent(\n    agent: object, *, client: Any\n) -> tuple[object | None, dict[str, object], int]:\n    """Probe one admitted route with route-local budget escalation evidence."""\n    row: dict[str, object] = {\n        "agent_id": str(getattr(agent, "id", "")),\n        "provider": str(getattr(agent, "provider_name", "") or "unknown"),\n        "model": str(getattr(agent, "model", "")),\n        "attempts": 1,\n    }\n    base_payload: dict[str, object] = {\n        "model": getattr(agent, "model", ""),\n        "messages": [\n            {"role": "system", "content": "You are a helpful assistant."},\n            {"role": "user", "content": "Reply with just 'OK'."},\n        ],\n        "temperature": REVIEW_TEMPERATURE,\n        "max_tokens": REVIEW_PREFLIGHT_BASE_TOKENS,\n        "stream": False,\n    }\n    try:\n        response = client.proxy_send_once(agent, "chat/completions", base_payload)\n    except Exception as exc:  # noqa: BLE001 - sanitize at provider boundary\n        _record_provider_exception(row, exc)\n        return None, row, 0\n    if _chat_response_has_text(response):\n        row["status"] = "ready"\n        row["finish_reason"] = _response_finish_reason(response) or "unknown"\n        row["reasoning_without_content"] = _response_has_reasoning_without_content(response)\n        return agent, row, 0\n\n    finish_reason = _response_finish_reason(response)\n    row["finish_reason"] = finish_reason or "unknown"\n    reasoning_without_content = _response_has_reasoning_without_content(response)\n    row["reasoning_without_content"] = reasoning_without_content\n    if finish_reason != "length" and not reasoning_without_content:\n        row["status"] = "rejected"\n        row["error_type"] = "invalid_chat_response"\n        return None, row, 0\n\n    row["attempts"] = 2\n    escalated_payload = dict(base_payload)\n    escalated_payload["max_tokens"] = REVIEW_PREFLIGHT_ESCALATED_TOKENS\n    try:\n        escalated_response = client.proxy_send_once(\n            agent, "chat/completions", escalated_payload\n        )\n    except Exception as exc:  # noqa: BLE001 - sanitize at provider boundary\n        _record_provider_exception(row, exc)\n        return None, row, 1\n    if _chat_response_has_text(escalated_response):\n        row["status"] = "ready"\n        row["escalated"] = True\n        row["finish_reason"] = _response_finish_reason(escalated_response) or "unknown"\n        row["reasoning_without_content"] = _response_has_reasoning_without_content(\n            escalated_response\n        )\n        return agent, row, 1\n\n    row["status"] = "rejected"\n    row["error_type"] = "invalid_chat_response"\n    row["finish_reason"] = _response_finish_reason(escalated_response) or "unknown"\n    row["reasoning_without_content"] = _response_has_reasoning_without_content(\n        escalated_response\n    )\n    return None, row, 1\n\n\ndef _preflight_review_agents(\n    agents: list[object], *, client: Any\n) -> tuple[list[object], dict[str, object]]:\n    """Probe admitted routes concurrently and report evidence in catalog order.\n\n    Admission and readiness are separate contracts. Every evidence-eligible\n    route stays admitted; this stage only establishes immediate serving\n    readiness. All admitted routes start one equal base probe concurrently, so\n    one slow route cannot serialize startup behind every other provider. A\n    route receives one larger-budget retry only when its own response carries\n    the explicit budget-starvation signature. There is no shared first-come\n    quota, route cap, provider preference, or completion-order authority.\n\n    Results are consumed in input order, preserving exact catalog/source\n    evidence even when providers complete out of order. ``ModelClient`` keeps\n    per-call usage in thread-local storage and its provider-slot guard is\n    thread-safe, so one shared client does not alias route telemetry.\n    """\n    if not agents:\n        report: dict[str, object] = {\n            "contract": "strix-plain-chat-preflight-v2",\n            "probed_count": 0,\n            "ready_count": 0,\n            "rejected_count": 0,\n            "escalations_used": 0,\n            "routes": [],\n        }\n        raise ReviewPreflightError(\n            "no provider route passed the Strix plain-chat preflight", report\n        )\n\n    with ThreadPoolExecutor(\n        max_workers=len(agents), thread_name_prefix="review-preflight"\n    ) as executor:\n        futures = [\n            executor.submit(_preflight_review_agent, agent, client=client)\n            for agent in agents\n        ]\n        outcomes = [future.result() for future in futures]\n\n    viable: list[object] = []\n    routes: list[dict[str, object]] = []\n    escalations_used = 0\n    for ready_agent, row, escalations in outcomes:\n        routes.append(row)\n        escalations_used += escalations\n        if ready_agent is not None:\n            viable.append(ready_agent)\n\n    report = {\n        "contract": "strix-plain-chat-preflight-v2",\n        "probed_count": len(agents),\n        "ready_count": len(viable),\n        "rejected_count": len(agents) - len(viable),\n        "escalations_used": escalations_used,\n        "routes": routes,\n    }\n    if not viable:\n        raise ReviewPreflightError(\n            "no provider route passed the Strix plain-chat preflight", report\n        )\n    return viable, report\n\n'''
    text = text[:start] + replacement + text[end + 1 :]

    # The production parser is free-only. Remove dormant auto-pool plumbing so
    # an unreachable historical branch cannot be mistaken for supported review behavior.
    text = text.replace("        PolicyError,\n", "", 1)
    old_selection = '''    free_rows = [\n        row for row in normalized_rows if row.get("cost_evidence") == "free"\n    ]\n    priced_rows = [\n        row for row in normalized_rows if row.get("cost_evidence") == "priced"\n    ]\n    admitted_free_rows = _zdr_admitted_rows(\n        free_rows,\n        require_zdr=args.require_zdr,\n        zdr_endpoints=zdr_endpoints,\n        checker=is_zdr_model,\n    )\n    admitted_priced_rows = _zdr_admitted_rows(\n        priced_rows,\n        require_zdr=args.require_zdr,\n        zdr_endpoints=zdr_endpoints,\n        checker=is_zdr_model,\n    )\n    primary_rows = (\n        (admitted_free_rows or admitted_priced_rows)\n        if args.pool == "auto"\n        else normalized_rows\n    )\n    result = build_zdr_prioritized_catalog(\n        primary_rows,\n'''
    new_selection = '''    result = build_zdr_prioritized_catalog(\n        normalized_rows,\n'''
    text = replace_once(text, old_selection, new_selection, "launcher dead auto selection")

    old_fallback = '''    agents = load_agents(args.catalog_out)\n    primary_report = result["report"]\n    fallback_result = None\n    fallback_agents: list[object] = []\n    if (\n        args.pool == "auto"\n        and admitted_free_rows\n        and admitted_priced_rows\n    ):\n        try:\n            fallback_result = build_zdr_prioritized_catalog(\n                admitted_priced_rows,\n                zdr_endpoints=zdr_endpoints,\n                require_zdr=args.require_zdr,\n                pool="auto",\n            )\n        except PolicyError:\n            fallback_result = None\n        if fallback_result is not None:\n            fallback_result["report"] = _with_discovery_counts(\n                fallback_result["report"], normalized_rows, provider_account=provider_account\n            )\n            fallback_result["report"]["primary_selected_count"] = primary_report[\n                "selected_count"\n            ]\n            fallback_result["report"]["primary_selection"] = primary_report["selected"]\n            fallback_agents = _load_temporary_agents(\n                f"{args.catalog_out}.priced",\n                fallback_result["agents"],\n                loader=load_agents,\n            )\n    client = ModelClient(\n'''
    text = replace_once(
        text,
        old_fallback,
        '''    agents = load_agents(args.catalog_out)\n    client = ModelClient(\n''',
        "launcher dead auto fallback setup",
    )
    old_call = '''    try:\n        agents, preflight_report, fallback_used = _preflight_with_fallback(\n            agents, fallback_agents, client=client\n        )\n    except ReviewPreflightError as exc:\n        _write_json(args.preflight_out, exc.report)\n        _log_preflight_rejections(exc.report)\n        raise SystemExit(f"review sidecar preflight failed: {exc}") from None\n    if fallback_used and fallback_result is not None:\n        Path(args.catalog_out).write_text(\n            json.dumps({"agents": fallback_result["agents"]}, indent=2, sort_keys=True)\n            + "\\n",\n            encoding="utf-8",\n        )\n        result = fallback_result\n        result["report"]["fallback_reason"] = "primary_routes_unavailable"\n        _write_json(args.report_out, result["report"])\n    _write_json(args.preflight_out, preflight_report)\n'''
    new_call = '''    try:\n        agents, preflight_report = _preflight_review_agents(agents, client=client)\n    except ReviewPreflightError as exc:\n        _write_json(args.preflight_out, exc.report)\n        _log_preflight_rejections(exc.report)\n        raise SystemExit(f"review sidecar preflight failed: {exc}") from None\n    _write_json(args.preflight_out, preflight_report)\n'''
    text = replace_once(text, old_call, new_call, "launcher production preflight call")
    path.write_text(text, encoding="utf-8")


def repair_policy() -> None:
    """Make ignored cardinality knobs observable without restoring decision authority."""
    path = Path("scripts/ci/contextual_orchestrator_review_policy.py")
    text = path.read_text(encoding="utf-8")
    parser_anchor = "\ndef _build_parser() -> argparse.ArgumentParser:\n"
    helper = '''\ndef _warn_explicit_legacy_options(argv: list[str]) -> None:\n    """Warn when obsolete cardinality options remain in operator configuration."""\n    for option in ("--limit", "--account-cap"):\n        if any(argument == option or argument.startswith(f"{option}=") for argument in argv):\n            print(\n                f"contextual-orchestrator review policy: {option} is deprecated and ignored",\n                file=sys.stderr,\n            )\n\n\n'''
    if "def _warn_explicit_legacy_options" not in text:
        text = replace_once(text, parser_anchor, helper + "def _build_parser() -> argparse.ArgumentParser:\n", "policy helper")
    old_main = '''def main(argv: list[str] | None = None) -> int:\n    """Run the catalog CLI and return one on policy or input failure."""\n    args = _build_parser().parse_args(argv)\n'''
    new_main = '''def main(argv: list[str] | None = None) -> int:\n    """Run the catalog CLI and return one on policy or input failure."""\n    effective_argv = list(sys.argv[1:] if argv is None else argv)\n    args = _build_parser().parse_args(effective_argv)\n    _warn_explicit_legacy_options(effective_argv)\n'''
    text = replace_once(text, old_main, new_main, "policy main diagnostics")
    path.write_text(text, encoding="utf-8")


def repair_docs() -> None:
    """Reconcile the monitoring contract and record the review-quality regression."""
    adr3 = Path("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md")
    text = adr3.read_text(encoding="utf-8")
    old = '''  that gate. The evidence itself remains useful regardless: it is exactly\n  the live signal for when "the free-catalog's stale-model and\n  provider-diversity gaps documented alongside this amendment" (above) are\n  closed, without requiring a manual re-audit.\n'''
    new = '''  that gate. The evidence itself remains useful as an account-level\n  diagnostic, but it is not an exact provider/outage-domain diversity signal:\n  multiple credentialed accounts can share one provider or outage domain.\n  Closing the reliability risk therefore requires separately modeled provider/\n  outage-domain evidence rather than treating account cardinality as routing\n  authority or as proof that the earlier diversity gap is closed.\n'''
    text = replace_once(text, old, new, "ADR-0003 monitoring contract")
    adr3.write_text(text, encoding="utf-8")

    adr5 = Path("docs/adr/0005-contextual-orchestrator-review-preflight-budget.md")
    text = adr5.read_text(encoding="utf-8")
    heading = "## 2026-09-02 startup-latency amendment"
    if heading not in text:
        text = text.rstrip() + f'''\n\n{heading}\n\nAdmission evidence and runtime readiness are distinct. The central free-only\ncatalog retains every evidence-eligible route. Startup probes those admitted\nroutes concurrently, with identical per-route base/escalation semantics and\ndeterministic input-order evidence, so one slow provider cannot serialize the\nwhole catalog and consume the review workflow deadline. Concurrency changes no\nroute membership, priority, cost/ZDR decision, or provider preference; it only\nremoves additive startup latency. The regression uses a synchronization barrier\nrather than a wall-clock threshold, proving that all admitted routes enter the\nprobe before any one route is allowed to complete.\n'''
        adr5.write_text(text, encoding="utf-8")

    doctor = Path("docs/doctoring/contextual-orchestrator-strix-free-diversity-evidence.md")
    text = doctor.read_text(encoding="utf-8")
    note = '''Startup readiness follows the same separation: complete admission evidence\nremains durable, while all admitted routes are probed concurrently and reported\nin catalog order. This removes additive provider latency without turning probe\ncompletion order into routing authority.\n\n'''
    marker = "PR #1629 restores that contract on current protected-main lineage"
    if note not in text:
        text = replace_once(text, marker, note + marker, "doctoring startup note")
        doctor.write_text(text, encoding="utf-8")

    baseline = Path("docs/product-technical-gap-baseline.md")
    text = baseline.read_text(encoding="utf-8")
    heading = "### 2026-09-02 Noema/OpenCode reviewer readiness false-negative regression"
    if heading not in text:
        text = text.rstrip() + f'''\n\n{heading}\n\nExternal review on `.github#1629` demonstrated a real operational false negative:\nfull evidence admission had been coupled to sequential startup probing, so a large\nset of individually slow provider routes could consume the review deadline before\nNoema/OpenCode began serving. The repair keeps evidence admission complete, starts\nper-route readiness probes concurrently with no provider preference, preserves\ninput-order/source evidence, and keeps each candidate's budget escalation local.\n`tests/test_contextual_orchestrator_review_preflight_concurrency.py` is the durable\nbarrier-based regression: the old sequential implementation cannot pass it, while\nthe GREEN implementation proves all admitted routes can enter transport before any\nroute completes. Explicit legacy `--limit`/`--account-cap` CLI configuration now\nemits diagnostics while remaining decision-inert. The pinned contextual-orchestrator\nranking contract was also re-audited: `_static_rank_key` ends in `agent.id`, so equal\nneutral priorities do not inherit discovery/list order as a routing tiebreak.\n'''
        baseline.write_text(text, encoding="utf-8")


def main() -> None:
    """Apply all causal source, regression-contract, and traceability repairs."""
    repair_launcher()
    repair_policy()
    repair_docs()


if __name__ == "__main__":
    main()
