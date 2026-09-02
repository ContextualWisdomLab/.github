#!/usr/bin/env python3
"""Repair exact-head PR #1674 review findings before the existing one-shot materializer.

This bridge edits only the already-reviewed one-shot transformer plus permanent
Noema workflow/test/docs contracts. It deletes itself before the successor
commit so no standing source-fix driver remains.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STRIX_HELPER = ROOT / "scripts/ci/pr1674_status_publication_repair.py"
NOEMA_WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
NOEMA_TEST = ROOT / "tests/test_noema_live_target_admission.py"
CHANGELOG = ROOT / "CHANGELOG.md"
SELF = ROOT / "scripts/ci/pr1674_exact_findings_repair.py"


def replace_exact(text: str, old: str, new: str, *, expected: int, label: str) -> str:
    """Replace an exact number of anchors or fail closed on concurrent drift."""
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} anchor(s), found {count}")
    return text.replace(old, new)


def repair_strix_materializer() -> None:
    """Make the existing Strix transformer executable and fail-closed."""
    text = STRIX_HELPER.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        "steps.dispatch_validation.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch'",
        "steps.dispatch_validation.outputs.should_scan == 'true' && github.event_name == 'repository_dispatch'",
        expected=2,
        label="late repository_dispatch admission conditions",
    )
    text = replace_exact(
        text,
        "if: github.event_name != 'repository_dispatch' || steps.dispatch_validation.outputs.should_scan != 'false'\\n",
        "if: github.event_name != 'repository_dispatch' || steps.dispatch_validation.outputs.should_scan == 'true'\\n",
        expected=1,
        label="target visibility skip condition",
    )
    old = (
        '    text = replace_once(\n'
        '        text,\n'
        '        "          TARGET_APP_STATUS_TOKEN: ${{ steps.target_app_token.outputs.token || \'\' }}\\n",\n'
        '        "          TARGET_APP_STATUS_TOKEN: ${{ steps.status_target_app_token.outputs.token || \'\' }}\\n",\n'
        '        "scan publisher fresh app token",\n'
        '    )\n'
    )
    new = (
        '    text = replace_once(\n'
        '        text,\n'
        '        "        if: ${{ always() && !cancelled() && steps.dispatch_publish_validation.outputs.publish_status == \'true\' && github.event_name == \'repository_dispatch\' && github.event.client_payload.pr_head_sha != \'\' }}\\n"\n'
        '        "        env:\\n"\n'
        '        "          TARGET_APP_STATUS_TOKEN: ${{ steps.target_app_token.outputs.token || \'\' }}\\n",\n'
        '        "        if: ${{ always() && !cancelled() && steps.dispatch_publish_validation.outputs.publish_status == \'true\' && github.event_name == \'repository_dispatch\' && github.event.client_payload.pr_head_sha != \'\' }}\\n"\n'
        '        "        env:\\n"\n'
        '        "          TARGET_APP_STATUS_TOKEN: ${{ steps.status_target_app_token.outputs.token || \'\' }}\\n",\n'
        '        "scan publisher fresh app token",\n'
        '    )\n'
    )
    text = replace_exact(text, old, new, expected=1, label="unique scan publisher token anchor")
    STRIX_HELPER.write_text(text, encoding="utf-8")


def repair_noema_oidc() -> None:
    """Require HTTPS-only transport before either Noema OIDC bearer exchange."""
    text = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    request_anchor = '''          request_url="${ACTIONS_ID_TOKEN_REQUEST_URL}"
          separator="&"
'''
    request_replacement = '''          request_url="${ACTIONS_ID_TOKEN_REQUEST_URL}"
          case "$request_url" in
            https://*) ;;
            *) fail_unavailable "Noema OIDC request URL must use https:// before transmitting a bearer token." ;;
          esac
          case "${TOKEN_EXCHANGE_URL:-}" in
            https://*) ;;
            *) fail_unavailable "Noema token exchange URL must use https:// before transmitting a bearer token." ;;
          esac
          separator="&"
'''
    text = replace_exact(
        text,
        request_anchor,
        request_replacement,
        expected=2,
        label="Noema OIDC HTTPS preflight",
    )
    text = replace_exact(
        text,
        '''            curl -fsS \\
              -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \\
''',
        '''            curl --proto '=https' --proto-redir '=https' -fsS \\
              -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \\
''',
        expected=2,
        label="Noema OIDC HTTPS-only request curl",
    )
    text = replace_exact(
        text,
        '''            curl -fsS \\
              -X POST \\
              -H "Content-Type: application/json" \\
              -H "Authorization: Bearer ${oidc_token}" \\
''',
        '''            curl --proto '=https' --proto-redir '=https' -fsS \\
              -X POST \\
              -H "Content-Type: application/json" \\
              -H "Authorization: Bearer ${oidc_token}" \\
''',
        expected=2,
        label="Noema app-token HTTPS-only exchange curl",
    )
    NOEMA_WORKFLOW.write_text(text, encoding="utf-8")


def repair_noema_contract_test() -> None:
    """Align permanent assertions with repository-scoped credentials and HTTPS transport."""
    text = NOEMA_TEST.read_text(encoding="utf-8")
    old_loop = '''    for step_name, step_id in (
        (refresh_name, "live_pr_refresh"),
        (publish_name, "live_pr_publish"),
    ):
        step_body = _step_body(workflow_text, step_name)
        assert f"        id: {step_id}\\n" in step_body
        assert "GH_TOKEN: ${{ github.token }}" in step_body
        assert "live_state=" in step_body
        assert "live_head_sha=" in step_body
        assert "live_draft=" in step_body
        assert 'echo "proceed=false" >>"$GITHUB_OUTPUT"' in step_body
        assert 'echo "proceed=true" >>"$GITHUB_OUTPUT"' in step_body
        assert "EXPECTED_HEAD_SHA" in step_body
        assert "live_head_sha,," in step_body
'''
    new_loop = '''    for step_name, step_id in (
        (refresh_name, "live_pr_refresh"),
        (publish_name, "live_pr_publish"),
    ):
        step_body = _step_body(workflow_text, step_name)
        assert f"        id: {step_id}\\n" in step_body
        assert "github.token" not in step_body
        assert "GH_TOKEN:" in step_body
        assert "live_state=" in step_body
        assert "live_head_sha=" in step_body
        assert "live_draft=" in step_body
        assert 'echo "proceed=false" >>"$GITHUB_OUTPUT"' in step_body
        assert 'echo "proceed=true" >>"$GITHUB_OUTPUT"' in step_body
        assert "EXPECTED_HEAD_SHA" in step_body
        assert "live_head_sha,," in step_body
'''
    text = replace_exact(text, old_loop, new_loop, expected=1, label="repository-scoped revalidation assertion")
    old_publication = '''    for publication_step in (
        "Refresh repository-scoped Noema GitHub App token for publication",
        "Publish prepared Noema verdict on the exact live head",
    ):
        assert "steps.live_pr_publish.outputs.proceed == 'true'" in _step_body(
            workflow_text,
            publication_step,
        )
'''
    new_publication = '''    publication_revalidation_index = workflow_text.index(
        "      - name: Revalidate live Noema target before publication\\n"
    )
    for refresh_step in (
        "Refresh repository-scoped Noema GitHub App token for publication",
        "Refresh repository-scoped Noema OIDC app token for publication",
    ):
        assert workflow_text.index(f"      - name: {refresh_step}\\n") < publication_revalidation_index
        assert "steps.live_pr_publish.outputs.proceed" not in _step_body(workflow_text, refresh_step)

    assert "steps.live_pr_publish.outputs.proceed == 'true'" in _step_body(
        workflow_text,
        "Publish prepared Noema verdict on the exact live head",
    )
'''
    text = replace_exact(text, old_publication, new_publication, expected=1, label="publication credential ordering assertions")
    if "def test_oidc_bearer_exchanges_require_https_only_transport" not in text:
        text += '''\n\ndef test_oidc_bearer_exchanges_require_https_only_transport() -> None:
    """Neither initial nor refreshed OIDC bearer material may traverse plaintext HTTP."""
    workflow_text = _workflow_text()
    for step_name in (
        "Exchange Noema app token through OIDC",
        "Refresh repository-scoped Noema OIDC app token for publication",
    ):
        body = _step_body(workflow_text, step_name)
        assert 'case "$request_url" in' in body
        assert 'https://*) ;;' in body
        assert 'case "${TOKEN_EXCHANGE_URL:-}" in' in body
        assert "--proto '=https' --proto-redir '=https'" in body
        assert "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" in body
        assert "Authorization: Bearer ${oidc_token}" in body
'''
    NOEMA_TEST.write_text(text, encoding="utf-8")


def update_changelog() -> None:
    """Record the security/authority repair without duplicating an existing entry."""
    text = CHANGELOG.read_text(encoding="utf-8")
    entry = '''## 2026-09-02 — Noema/Strix live-publication authority hardening

- Revalidate long-running Strix `repository_dispatch` targets immediately before either status publisher, fail closed on head/repository/lookup drift, and cleanly suppress exact-head closed/draft publication; skipped dispatches no longer perform visibility admission work.
- Require HTTPS-only OIDC request and token-exchange transport before Noema sends bearer material, while keeping final publication on freshly selected repository-scoped credentials.
- Added permanent workflow-level regressions for both late Strix publication boundaries, skipped-target propagation, Noema credential ordering, and HTTPS-only bearer exchange.

'''
    if entry not in text:
        CHANGELOG.write_text(entry + text, encoding="utf-8")


def main() -> int:
    """Apply all exact-head review findings, then retire this bridge."""
    repair_strix_materializer()
    repair_noema_oidc()
    repair_noema_contract_test()
    update_changelog()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
