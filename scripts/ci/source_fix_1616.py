#!/usr/bin/env python3
"""One-shot deterministic source transform for PR #1616; self-removes on success."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
HELPER = ROOT / ".github/actions/noema-review/two_phase.py"
TEMP_WORKFLOW = ROOT / ".github/workflows/source-fix-1616-noema-token-refresh.yml"
SELF = Path(__file__).resolve()


workflow = WORKFLOW.read_text(encoding="utf-8")
marker = "      - name: Run Noema LLM review and submit verdict\n"
if workflow.count(marker) != 1:
    raise SystemExit("expected exactly one single-phase Noema workflow marker")
replacement = '''      - name: Prepare Noema model verdict
        if: env.PR_NUMBER != ''
        id: noema_prepare
        env:
          GH_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN || steps.noema_github_app_token.outputs.token || steps.noema_oidc_token.outputs.token }}
          NOEMA_REVIEW_TOKEN_SOURCE: ${{ steps.noema_credential.outputs.source == 'pat' && 'noema-review-pat' || steps.noema_credential.outputs.source == 'github-app' && 'noema-review-github-app' || 'noema-review-app-oidc' }}
          NOEMA_REVIEW_ACTOR: ${{ steps.noema_github_app_token.outputs['app-slug'] && format('{0}[bot]', steps.noema_github_app_token.outputs['app-slug']) || '' }}
          NOEMA_REVIEW_INSTALLATION_ID: ${{ steps.noema_github_app_token.outputs['installation-id'] }}
        run: |
          set -euo pipefail
          if [ -z "${PR_NUMBER:-}" ]; then
            echo "No pull request number was available for this event; skipping."
            echo "prepared=false" >>"$GITHUB_OUTPUT"
            exit 0
          fi
          if [ -z "${GH_TOKEN:-}" ]; then
            echo "::error::Noema reviewer credential selection succeeded but no token was minted; review cannot prepare a verdict."
            exit 1
          fi
          if [ -z "${CONTEXTUAL_ORCHESTRATOR_BASE_URL:-}" ] || [ -z "${CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE:-}" ]; then
            echo "::error::contextual-orchestrator review sidecar must be provisioned before Noema LLM review."
            exit 1
          fi
          source "$GITHUB_WORKSPACE/scripts/ci/load_contextual_orchestrator_token.sh"
          export NOEMA_LLM_API_URL="${CONTEXTUAL_ORCHESTRATOR_BASE_URL%/}/v1/chat/completions"
          export NOEMA_LLM_MODEL="orchestrator/free"
          export NOEMA_LLM_API_KEY="${CONTEXTUAL_ORCHESTRATOR_TOKEN}"
          export NOEMA_LLM_VIA_ORCHESTRATOR=1
          verdict_file="${RUNNER_TEMP}/noema-verdict-envelope.json"
          rm -f "$verdict_file"
          python3 "$GITHUB_WORKSPACE/.github/actions/noema-review/two_phase.py" \
            --repo "$TARGET_REPOSITORY" \
            --pr-number "$PR_NUMBER" \
            --expected-head "$EXPECTED_HEAD_SHA" \
            --prepare-verdict-file "$verdict_file"
          if [ -f "$verdict_file" ]; then
            echo "prepared=true" >>"$GITHUB_OUTPUT"
          else
            echo "prepared=false" >>"$GITHUB_OUTPUT"
            echo "::notice::Noema model phase produced no publishable envelope; publication is skipped."
          fi

      - name: Refresh repository-scoped Noema GitHub App token for publication
        if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'github-app'
        id: noema_github_app_publication_token
        uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0
        with:
          client-id: ${{ vars.NOEMA_GITHUB_APP_CLIENT_ID }}
          private-key: ${{ secrets.NOEMA_GITHUB_APP_PRIVATE_KEY }}
          owner: ContextualWisdomLab
          repositories: ${{ steps.noema_credential.outputs.repository }}
          permission-actions: read
          permission-checks: read
          permission-contents: read
          permission-metadata: read
          permission-pull-requests: write
          permission-security-events: read
          permission-statuses: read
          permission-vulnerability-alerts: read

      - name: Publish prepared Noema verdict on the exact live head
        if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true'
        env:
          GH_TOKEN: ${{ steps.noema_credential.outputs.source == 'pat' && secrets.NOEMA_REVIEW_TOKEN || steps.noema_credential.outputs.source == 'github-app' && steps.noema_github_app_publication_token.outputs.token || steps.noema_credential.outputs.source == 'oidc' && steps.noema_oidc_token.outputs.token || '' }}
          NOEMA_REVIEW_TOKEN_SOURCE: ${{ steps.noema_credential.outputs.source == 'pat' && 'noema-review-pat' || steps.noema_credential.outputs.source == 'github-app' && 'noema-review-github-app-refresh' || steps.noema_credential.outputs.source == 'oidc' && 'noema-review-app-oidc' || '' }}
          NOEMA_REVIEW_ACTOR: ${{ steps.noema_github_app_publication_token.outputs['app-slug'] && format('{0}[bot]', steps.noema_github_app_publication_token.outputs['app-slug']) || '' }}
          NOEMA_REVIEW_INSTALLATION_ID: ${{ steps.noema_github_app_publication_token.outputs['installation-id'] }}
        run: |
          set -euo pipefail
          if [ -z "${GH_TOKEN:-}" ]; then
            echo "::error::Noema publication has no credential for the explicitly selected reviewer source; refusing any GITHUB_TOKEN or author fallback."
            exit 1
          fi
          verdict_file="${RUNNER_TEMP}/noema-verdict-envelope.json"
          if [ ! -f "$verdict_file" ]; then
            echo "::error::Noema prepared-verdict output claimed success but its private envelope is missing."
            exit 1
          fi
          python3 "$GITHUB_WORKSPACE/.github/actions/noema-review/two_phase.py" \
            --repo "$TARGET_REPOSITORY" \
            --pr-number "$PR_NUMBER" \
            --expected-head "$EXPECTED_HEAD_SHA" \
            --publish-verdict-file "$verdict_file"
'''
WORKFLOW.write_text(workflow[: workflow.index(marker)] + replacement, encoding="utf-8")

helper = HELPER.read_text(encoding="utf-8")
old = "    expected = _canonical_head(expected_head)\n    payload = _read_envelope(path)\n    try:\n"
new = "    expected = _canonical_head(expected_head)\n    try:\n        payload = _read_envelope(path)\n"
if old not in helper:
    raise SystemExit("expected two-phase publication cleanup seam is missing")
HELPER.write_text(helper.replace(old, new, 1), encoding="utf-8")

(ROOT / "tests/test_noema_reviewer_token_lifetime.py").write_text('''"""Regression contract for Noema reviewer credential lifetime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "noema-review.yml"
APP_TOKEN_ACTION = (
    "uses: actions/create-github-app-token@"
    "bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0"
)


def _step_block(text: str, name: str) -> str:
    """Return one exact named workflow step without borrowing sibling evidence."""
    marker = f"      - name: {name}\\n"
    start = text.index(marker)
    next_step = text.find("\\n      - name: ", start + len(marker))
    return text[start:] if next_step < 0 else text[start:next_step]


def test_noema_remints_repository_scoped_app_token_after_model_before_publication() -> None:
    """A long model call must not publish with its predecessor App token."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = _step_block(workflow, "Prepare Noema model verdict")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert APP_TOKEN_ACTION in refresh
    assert "--prepare-verdict-file" in prepare
    assert "--publish-verdict-file" in publish
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in prepare
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in publish
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in prepare
    assert "steps.noema_prepare.outputs.prepared == 'true'" in refresh
    assert "steps.noema_credential.outputs.source == 'github-app'" in refresh
    assert "steps.noema_prepare.outputs.prepared == 'true'" in publish


def test_publication_step_uses_fresh_app_token_without_authority_fallback() -> None:
    """Publication selects the refreshed App token and fails closed for unknown sources."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert "owner: ContextualWisdomLab" in refresh
    assert "repositories: ${{ steps.noema_credential.outputs.repository }}" in refresh
    assert "permission-pull-requests: write" in refresh
    assert "permission-contents: read" in refresh
    assert "permission-actions: read" in refresh
    assert "steps.noema_github_app_publication_token.outputs.token" in publish
    assert "steps.noema_github_app_token.outputs.token" not in publish
    assert "secrets.NOEMA_REVIEW_TOKEN" in publish
    assert "steps.noema_oidc_token.outputs.token" in publish
    assert "github.token" not in publish
    assert "refusing any GITHUB_TOKEN or author fallback" in publish


def test_prepare_and_publish_are_the_only_model_verdict_execution_path() -> None:
    """The old single-process review path must not survive beside the handoff."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Run Noema LLM review and submit verdict" not in workflow
    assert "python3 -m scripts.ci.noema_review_gate" not in workflow
    assert workflow.count("--prepare-verdict-file") == 1
    assert workflow.count("--publish-verdict-file") == 1
''', encoding="utf-8")

(ROOT / "tests/test_noema_two_phase_handoff.py").write_text('''"""Executable regressions for the Noema two-phase reviewer handoff."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".github" / "actions" / "noema-review" / "two_phase.py"
HEAD = "a" * 40


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("noema_two_phase_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_live_gate(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    monkeypatch.setattr(module.gate, "fetch_pr", lambda _repo, _number: {"isDraft": False})
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)


def test_prepare_seals_validated_verdict_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preparation performs model work but cannot submit GitHub review evidence."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    monkeypatch.setattr(module.gate, "fetch_diff", lambda _repo, _number: ("diff", False))
    monkeypatch.setattr(module.gate, "fetch_changed_files", lambda _repo, _number: [("src/a.py", "MODIFIED")])
    monkeypatch.setattr(module.gate, "build_review_context", lambda *_args: "context")
    verdict = {"decision": "approve", "summary": "bounded"}
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: verdict)
    monkeypatch.setattr(module.gate, "submit_review", lambda *_args: pytest.fail("preparation must never publish"))
    envelope = tmp_path / "verdict.json"

    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert module._read_envelope(envelope)["verdict"] == verdict


def test_publish_refetches_exact_head_with_fresh_actor_and_removes_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publication rebinds repository/head/actor and consumes the private handoff."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    envelope = tmp_path / "verdict.json"
    verdict = {"decision": "approve", "summary": "bounded"}
    module._write_envelope(envelope, {
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 7,
        "expected_head": HEAD,
        "verdict": verdict,
    })
    submitted: list[tuple[object, ...]] = []
    monkeypatch.setattr(module.gate, "submit_review", lambda *args: submitted.append(args))

    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert len(submitted) == 1
    assert submitted[0][0:2] == ("ContextualWisdomLab/example", 7)
    assert submitted[0][3] == "cwl-noema-review[bot]"
    assert submitted[0][4] == verdict
    assert not envelope.exists()


def test_publish_rejects_stale_head_and_never_submits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A moved head invalidates predecessor model evidence before publication."""
    module = _load_module()
    monkeypatch.setattr(module.gate, "fetch_pr", lambda _repo, _number: {"isDraft": False})
    def stale(_pr: object, _head: str) -> None:
        raise RuntimeError("stale")
    monkeypatch.setattr(module.gate, "require_expected_head", stale)
    monkeypatch.setattr(module.gate, "submit_review", lambda *_args: pytest.fail("stale evidence must not publish"))
    envelope = tmp_path / "verdict.json"
    module._write_envelope(envelope, {
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 7,
        "expected_head": HEAD,
        "verdict": {"decision": "approve"},
    })

    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


def test_prepare_skip_creates_no_publishable_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Draft skip semantics stay non-failing and cannot fabricate evidence."""
    module = _load_module()
    monkeypatch.setattr(module.gate, "fetch_pr", lambda _repo, _number: {"isDraft": True})
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: pytest.fail("draft must not call the model"))
    envelope = tmp_path / "verdict.json"

    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


def test_publish_cleans_untrusted_envelope_even_when_read_validation_fails(tmp_path: Path) -> None:
    """Malformed handoff state cannot linger after a failed publication attempt."""
    module = _load_module()
    envelope = tmp_path / "verdict.json"
    envelope.write_text("{}\\n", encoding="utf-8")
    os.chmod(envelope, 0o644)

    with pytest.raises(RuntimeError, match="permissions"):
        module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope)
    assert not envelope.exists()


def test_reader_rejects_hardlinked_aliases(tmp_path: Path) -> None:
    """A caller-owned alias cannot mutate the supposedly private handoff file."""
    module = _load_module()
    envelope = tmp_path / "verdict.json"
    alias = tmp_path / "alias.json"
    module._write_envelope(envelope, {"schema_version": module.ENVELOPE_SCHEMA_VERSION})
    os.link(envelope, alias)
    try:
        with pytest.raises(RuntimeError, match="single-link"):
            module._read_envelope(envelope)
    finally:
        envelope.unlink(missing_ok=True)
        alias.unlink(missing_ok=True)
''', encoding="utf-8")

(ROOT / "docs/doctoring/noema-review-token-lifetime.md").write_text('''# Noema reviewer credential lifetime

## Incident and root cause

On 2026-09-01, trusted central Noema review for `ContextualWisdomLab/naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0` minted the repository-scoped `cwl-noema-review` GitHub App installation token before model work. Contextual-orchestrator review then exceeded the installation-token lifetime; the first later GitHub operation failed HTTP 401 and cleanup independently reported token expiry. Repository-owned deterministic checks on that Naruon head were otherwise green. The defect is in the central reviewer credential lifecycle, not Naruon product code.

## Closed operating contract

Noema separates model verdict preparation from GitHub publication. Preparation remains bound to the trigger's canonical exact head and stores only a bounded, owner-only, single-link runner-local envelope. If preparation intentionally skips because the PR is stale, draft, or already reviewed, the workflow emits `prepared=false` and performs no publication.

For the GitHub App path, a second repository-scoped installation token is minted only after model work and only when a publishable envelope exists. Publication never reuses the predecessor App token, never falls back to `github.token` or the PR author, and independently re-fetches the live PR/head and reviewer actor before submitting evidence. PAT and OIDC remain explicit sources: publication uses only the selected source and fails closed if it is absent; this repair does not silently convert those paths to another authority.

The envelope is deleted after every publication attempt, including malformed-envelope read validation failures. Executable regressions cover preparation-without-publication, exact-head/actor rebinding, stale heads, draft skip behavior, cleanup, and hard-link alias rejection. Step-scoped workflow regressions prove that the second App mint sits between preparation and publication and that publication references the fresh token.

## Verification and downstream replay

Focused CI runs the token-lifetime and two-phase handoff regressions with hash-pinned review dependencies whenever the workflow/helper/contracts change. After protected-main merge, replay unchanged `naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0`: Required Noema Review must finish with current-head schema-valid review evidence or a typed review-unavailable result, never opaque expired-token 401 and never stale-head publication. A pre-merge run does not prove the merged workflow-source path and is not promoted to release evidence.
''', encoding="utf-8")

(ROOT / ".github/workflows/noema-token-lifetime-quality-ci.yml").write_text('''name: Noema Reviewer Token Lifetime CI

on:
  pull_request:
    paths:
      - .github/workflows/noema-review.yml
      - .github/actions/noema-review/two_phase.py
      - tests/test_noema_reviewer_token_lifetime.py
      - tests/test_noema_two_phase_handoff.py
      - docs/doctoring/noema-review-token-lifetime.md
      - docs/product-technical-gap-baseline.md
      - CHANGELOG.md
      - requirements-opencode-review-ci-hashes.txt
      - .github/workflows/noema-token-lifetime-quality-ci.yml

permissions:
  contents: read

jobs:
  noema-reviewer-token-lifetime:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - name: Checkout exact source
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install pinned review CI dependencies
        run: >-
          python3 -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-opencode-review-ci-hashes.txt
      - name: Verify token-lifetime handoff contracts
        run: |
          set -euo pipefail
          PYTHONPATH=. python3 -m pytest -q \
            tests/test_noema_reviewer_token_lifetime.py \
            tests/test_noema_two_phase_handoff.py
          python3 -m compileall -q .github/actions/noema-review/two_phase.py tests/test_noema_reviewer_token_lifetime.py tests/test_noema_two_phase_handoff.py
          git diff --check
''', encoding="utf-8")

changelog_path = ROOT / "CHANGELOG.md"
changelog = changelog_path.read_text(encoding="utf-8")
entry = "- **Refresh Noema reviewer App authority after long model work (`#1616`).** A real `naruon#1497` review outlived its repository-scoped GitHub App installation token and failed the next exact-head GitHub operation with HTTP 401. The trusted workflow now prepares the validated verdict into a private runner-local envelope, remints the same least-privilege repository-scoped App authority after model work, independently re-fetches exact live head/reviewer identity, and only then publishes. Skipped preparation creates no envelope, predecessor App tokens cannot authorize publication, PAT/OIDC remain explicit fail-closed sources, malformed handoffs are cleaned up, and executable plus step-scoped regressions cover stale-head, identity, alias, and workflow-wiring behavior.\n"
if entry not in changelog:
    if "## [Unreleased]\n" not in changelog:
        raise SystemExit("CHANGELOG Unreleased marker is missing")
    changelog = changelog.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
changelog_path.write_text(changelog, encoding="utf-8")

baseline_path = ROOT / "docs/product-technical-gap-baseline.md"
baseline = baseline_path.read_text(encoding="utf-8")
heading = "## Noema reviewer credential-lifetime delta — 2026-09-01"
if heading not in baseline:
    baseline += '''

## Noema reviewer credential-lifetime delta — 2026-09-01

**Observed gap.** `ContextualWisdomLab/naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0` demonstrated a control-plane latency/authority defect: a repository-scoped `cwl-noema-review` GitHub App token minted before contextual-orchestrator model work expired before the next GitHub operation, producing HTTP 401 even though repository-owned deterministic checks were otherwise successful. This is a central `.github` reviewer-lifecycle gap, not a Naruon product failure.

**Owner-side closure in #1616.** The Noema workflow now treats model preparation and GitHub publication as separate trust phases. A bounded private envelope carries only the model verdict; the GitHub App path remints the same repository-scoped least-privilege authority after model work, and publication independently verifies repository, PR number, canonical exact head, live PR state, draft state, independent reviewer actor, and duplicate-current-head review state before submission. No predecessor-head evidence or predecessor App credential is accepted as publication authority. PAT/OIDC remain explicit sources and there is no `github.token` or author fallback.

**Executable evidence.** `tests/test_noema_reviewer_token_lifetime.py` binds the production workflow step graph to prepare → fresh App mint → publish with exact-head arguments and source-specific credentials. `tests/test_noema_two_phase_handoff.py` executes the helper against controlled gate doubles and proves no preparation-side publication, fresh-head/actor rebinding, stale-head non-publication, draft skip behavior, cleanup on malformed handoff, and hard-link alias rejection. `.github/workflows/noema-token-lifetime-quality-ci.yml` runs these contracts with hash-pinned dependencies on every relevant seam.

**Residual external verification.** After this central change reaches protected `main`, replay Required Noema Review for unchanged `naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0`. Closure evidence requires a current-head schema-valid review or typed review-unavailable outcome without expired-token 401; a pre-merge run cannot prove the merged workflow-source path and is not promoted to release evidence.
'''
baseline_path.write_text(baseline, encoding="utf-8")

TEMP_WORKFLOW.unlink(missing_ok=True)
SELF.unlink(missing_ok=True)
