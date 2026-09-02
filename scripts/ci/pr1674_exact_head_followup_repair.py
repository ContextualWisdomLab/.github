#!/usr/bin/env python3
"""Materialize PR #1674 exact-head reviewer repairs, then self-delete via workflow."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOEMA = ROOT / ".github/workflows/noema-review.yml"
STRIX = ROOT / ".github/workflows/strix.yml"
STRIX_TEST = ROOT / "tests/test_strix_repository_dispatch_live_state.py"


def require_once(text: str, needle: str, label: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one occurrence, found {count}")


def repair_noema() -> None:
    text = NOEMA.read_text(encoding="utf-8")

    app_start = "      - name: Refresh repository-scoped Noema GitHub App token for publication\n"
    live_start = "      - name: Revalidate live Noema target before publication\n"
    publish_start = "      - name: Publish prepared Noema verdict on the exact live head\n"
    initial_oidc_start = "      - name: Exchange Noema app token through OIDC\n"
    model_refresh_start = "      - name: Revalidate live Noema target before model setup\n"
    for needle, label in (
        (app_start, "app refresh"),
        (live_start, "publication live check"),
        (publish_start, "publication step"),
        (initial_oidc_start, "initial oidc exchange"),
        (model_refresh_start, "model live refresh"),
    ):
        require_once(text, needle, label)

    # Extract and remove the existing publication GitHub-App refresh block.
    app_i = text.index(app_start)
    publish_i = text.index(publish_start, app_i)
    app_block = text[app_i:publish_i]
    text = text[:app_i] + text[publish_i:]
    app_block = app_block.replace(
        "if: env.PR_NUMBER != '' && steps.live_pr_publish.outputs.proceed == 'true' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'github-app'",
        "if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'github-app'",
        1,
    )
    if "steps.live_pr_publish.outputs.proceed" in app_block:
        raise SystemExit("app publication refresh still depends on the later live-publication step")

    # Clone the already-reviewed OIDC exchange implementation so long model runs
    # obtain fresh repository-scoped authority immediately before publication.
    oidc_i = text.index(initial_oidc_start)
    model_i = text.index(model_refresh_start, oidc_i)
    oidc_block = text[oidc_i:model_i]
    oidc_refresh = oidc_block.replace(
        "- name: Exchange Noema app token through OIDC",
        "- name: Refresh repository-scoped Noema OIDC app token for publication",
        1,
    ).replace(
        "id: noema_oidc_token",
        "id: noema_oidc_publication_token",
        1,
    ).replace(
        "if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true' && steps.noema_credential.outputs.source == 'oidc'",
        "if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'oidc'",
        1,
    )
    if "id: noema_oidc_publication_token" not in oidc_refresh:
        raise SystemExit("failed to construct publication OIDC refresh")

    # Place both refreshes before the authoritative publication-boundary lookup.
    live_i = text.index(live_start)
    text = text[:live_i] + app_block + oidc_refresh + text[live_i:]

    # The live lookup and final publication must use the selected fresh authority,
    # never the central workflow token or an expired pre-model app/OIDC token.
    live_i = text.index(live_start)
    publish_i = text.index(publish_start, live_i)
    live_block = text[live_i:publish_i]
    require_once(live_block, "          GH_TOKEN: ${{ github.token }}\n", "publication live-check central token")
    fresh_expr = (
        "          GH_TOKEN: ${{ steps.noema_credential.outputs.source == 'pat' && secrets.NOEMA_REVIEW_TOKEN || "
        "steps.noema_credential.outputs.source == 'github-app' && steps.noema_github_app_publication_token.outputs.token || "
        "steps.noema_credential.outputs.source == 'oidc' && steps.noema_oidc_publication_token.outputs.token || '' }}\n"
    )
    live_block = live_block.replace("          GH_TOKEN: ${{ github.token }}\n", fresh_expr, 1)
    text = text[:live_i] + live_block + text[publish_i:]

    old_publish_oidc = "steps.noema_credential.outputs.source == 'oidc' && steps.noema_oidc_token.outputs.token"
    new_publish_oidc = "steps.noema_credential.outputs.source == 'oidc' && steps.noema_oidc_publication_token.outputs.token"
    require_once(text, old_publish_oidc, "final publication stale OIDC token")
    text = text.replace(old_publish_oidc, new_publish_oidc, 1)

    # Fail closed if a future edit accidentally reintroduces the central token at
    # the publication boundary.
    live_i = text.index(live_start)
    publish_i = text.index(publish_start, live_i)
    live_block = text[live_i:publish_i]
    if "github.token" in live_block:
        raise SystemExit("publication live check still contains github.token")
    if "noema_github_app_publication_token.outputs.token" not in live_block or "noema_oidc_publication_token.outputs.token" not in live_block:
        raise SystemExit("publication live check lacks fresh repository-scoped authorities")

    NOEMA.write_text(text, encoding="utf-8")


def repair_strix() -> None:
    text = STRIX.read_text(encoding="utf-8")

    strix_header = "  strix:\n    if: github.event_name != 'pull_request_target' || github.event.action != 'closed'\n"
    require_once(text, strix_header, "strix job header")
    if "    outputs:\n      should_scan: ${{ steps.dispatch_validation.outputs.should_scan || 'true' }}\n" not in text:
        text = text.replace(
            strix_header,
            strix_header + "    outputs:\n      should_scan: ${{ steps.dispatch_validation.outputs.should_scan || 'true' }}\n",
            1,
        )

    visibility = "      - name: Resolve target repository visibility\n        id: target_visibility\n"
    require_once(text, visibility, "target visibility step")
    text = text.replace(
        visibility,
        "      - name: Resolve target repository visibility\n        if: steps.dispatch_validation.outputs.should_scan != 'false'\n        id: target_visibility\n",
        1,
    )

    old_followup = "    if: ${{ always() && !cancelled() && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n"
    require_once(text, old_followup, "follow-up status job condition")
    new_followup = "    if: ${{ always() && !cancelled() && needs.strix.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n"
    text = text.replace(old_followup, new_followup, 1)

    STRIX.write_text(text, encoding="utf-8")


def strengthen_strix_regression() -> None:
    text = STRIX_TEST.read_text(encoding="utf-8")
    marker = "        \"Fetch pull request head for trusted scan\",\n"
    require_once(text, marker, "strix guarded step set")
    if '"Resolve target repository visibility"' not in text:
        text = text.replace(marker, '        "Resolve target repository visibility",\n' + marker, 1)

    addition = '''\n\ndef test_repository_dispatch_skip_signal_crosses_into_followup_status_job() -> None:\n    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))\n    strix_job = workflow["jobs"]["strix"]\n    followup = workflow["jobs"]["publish-manual-pr-evidence-status"]\n\n    assert "steps.dispatch_validation.outputs.should_scan" in str(strix_job.get("outputs", {}).get("should_scan", ""))\n    condition = str(followup.get("if", ""))\n    assert "needs.strix.outputs.should_scan != 'false'" in condition\n'''
    test_name = "def test_repository_dispatch_skip_signal_crosses_into_followup_status_job()"
    if test_name not in text:
        text = text.rstrip() + addition + "\n"
    STRIX_TEST.write_text(text, encoding="utf-8")


def main() -> None:
    repair_noema()
    repair_strix()
    strengthen_strix_regression()


if __name__ == "__main__":
    main()
