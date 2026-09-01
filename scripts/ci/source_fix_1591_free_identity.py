"""One-shot exact-head repair for PR #1591 central free-pool identity boundaries."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts/ci/contextual_orchestrator_review_policy.py"
LAUNCHER = ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
CHANGELOG = ROOT / "CHANGELOG.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace exactly one source fragment or fail closed on source drift."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_policy() -> None:
    """Reject normalized runtime identity collisions before catalog emission."""
    replace_once(
        POLICY,
        """    catalog_rows: list[dict[str, Any]] = []\n    zdr_count = 0\n    for row in picked:\n        provider = str(row[\"provider\"])\n        model = str(row[\"model\"])\n        evidence = _cost_evidence(row)\n        zdr = is_zdr_model(provider, model=model, zdr_endpoints=zdr_endpoints)\n        if zdr:\n            zdr_count += 1\n        catalog_rows.append(\n            {\n                \"id\": _normalize_agent_id(str(row[\"agent_id\"]), provider),\n""",
        """    catalog_rows: list[dict[str, Any]] = []\n    seen_agent_ids: set[str] = set()\n    zdr_count = 0\n    for row in picked:\n        provider = str(row[\"provider\"])\n        model = str(row[\"model\"])\n        agent_id = _normalize_agent_id(str(row[\"agent_id\"]), provider)\n        if agent_id in seen_agent_ids:\n            raise PolicyError(\n                f\"agent id collision after normalization: {agent_id!r}; \"\n                \"distinct review routes require distinct runtime identities\"\n            )\n        seen_agent_ids.add(agent_id)\n        evidence = _cost_evidence(row)\n        zdr = is_zdr_model(provider, model=model, zdr_endpoints=zdr_endpoints)\n        if zdr:\n            zdr_count += 1\n        catalog_rows.append(\n            {\n                \"id\": agent_id,\n""",
    )


def patch_central_free_only() -> None:
    """Make the central review entry points accept only orchestrator/free."""
    replace_once(
        LAUNCHER,
        '    parser.add_argument("--pool", choices=("free", "auto"), default="free")\n',
        '    parser.add_argument("--pool", choices=("free",), default="free")\n',
    )
    replace_once(
        SIDECAR,
        """orchestrator_pool=\"${CONTEXTUAL_ORCHESTRATOR_POOL:-free}\"\ncase \"$orchestrator_pool\" in\n  free|auto)\n    pool_args=(--pool \"$orchestrator_pool\")\n    ;;\n  *)\n    fail \"CONTEXTUAL_ORCHESTRATOR_POOL must be free or auto\"\n    ;;\nesac\n""",
        """orchestrator_pool=\"${CONTEXTUAL_ORCHESTRATOR_POOL:-free}\"\nif [ \"$orchestrator_pool\" != \"free\" ]; then\n  fail \"CONTEXTUAL_ORCHESTRATOR_POOL must be free\"\nfi\npool_args=(--pool free)\n""",
    )


def patch_docs() -> None:
    """Record the exact causal boundary without inventing routing evidence."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    line = (
        "- Make the central contextual-orchestrator review entry point strictly `orchestrator/free` "
        "and fail closed when distinct discovered routes normalize to the same runtime agent identity. "
        "This removes the retired paid-inclusive configuration path and prevents identity collisions "
        "from erasing failover candidates without introducing a replacement ranking heuristic.\n"
    )
    if line not in changelog:
        anchor = "## [Unreleased]\n"
        if anchor not in changelog:
            raise RuntimeError("CHANGELOG.md lacks [Unreleased] anchor")
        CHANGELOG.write_text(changelog.replace(anchor, anchor + line, 1), encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    marker = "## 2026-09-02 central free-pool reachability and identity repair"
    if marker not in baseline:
        BASELINE.write_text(
            baseline.rstrip()
            + "\n\n"
            + marker
            + "\n\n"
            + "PR #1591 exact-head review identified two remaining admission/runtime identity defects. "
            + "The central launcher and sidecar still accepted the retired `auto` pool even though "
            + "OpenCode, Noema, and Strix are governed as `orchestrator/free` only. The entry points now "
            + "reject every non-free pool value. Separately, two distinct discovered routes could normalize "
            + "to the same `ModelAgent.id`, which is runtime identity used by failover and evidence state; "
            + "catalog construction now fails closed on any such collision instead of silently collapsing "
            + "a route. No priority, provider order, model name, quota, weight, threshold, or fallback score "
            + "is introduced. The remaining no-evidence name-order routing defect belongs to "
            + "ContextualWisdomLab/contextual-orchestrator and is being repaired in canonical PR #1000; "
            + "`.github` must not invent a local priority to mask it.\n",
            encoding="utf-8",
        )


def main() -> None:
    """Apply the exact bounded repair."""
    patch_policy()
    patch_central_free_only()
    patch_docs()


if __name__ == "__main__":
    main()
