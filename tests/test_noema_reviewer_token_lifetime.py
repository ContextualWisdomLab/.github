"""Regression contract for Noema reviewer credential lifetime."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "noema-review.yml"
APP_TOKEN_ACTION = (
    "uses: actions/create-github-app-token@"
    "bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0"
)


def _step_block(text: str, name: str) -> str:
    """Return one exact named workflow step without borrowing sibling evidence."""
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    next_step = text.find("\n      - name: ", start + len(marker))
    next_job = text.find("\n  continue-noema-transport:\n", start + len(marker))
    ends = [end for end in (next_step, next_job) if end >= 0]
    return text[start:min(ends)] if ends else text[start:]


def test_prepublication_metadata_uses_fresh_read_only_app_token(tmp_path: Path) -> None:
    """An expired pre-model token never masks the new post-model read grant."""
    import json
    import os
    import re
    import shutil
    import subprocess
    from tests.test_strix_repository_visibility_contract import _extract_run_block
    workflow = WORKFLOW.read_text(encoding="utf-8")
    refresh_name = "Refresh read-only Noema GitHub App metadata token after model"
    revalidate_name = "Revalidate prepared scope before publisher credential refresh"
    import hashlib
    import sys
    from scripts.ci import noema_bootstrap_producer as producer
    from tests.test_noema_issuer_producer_controls import bootstrap_case
    revalidate = _step_block(workflow, revalidate_name)
    expression = re.search(r"GH_TOKEN: \$\{\{ (.*?) \}\}", revalidate)
    tokens = {'steps.noema_metadata_app_token.outputs.token': 'EXPIRED_PRE_MODEL',
              'steps.noema_publication_metadata_token.outputs.token': 'FRESH_READ_ONLY',
              'github.token': 'OTHER_IDENTITY'}
    token = next((tokens.get(term.strip(), '') for term in expression.group(1).split(' || ')
                  if tokens.get(term.strip(), '')), '')
    private, source, entry, raw, admission = bootstrap_case(tmp_path)
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    admission.update(scope=scope, installation_id=7, app_id=11)
    producer.materialize_tooling(source, private/'tooling', raw,
        accepted_digest=hashlib.sha256(raw).hexdigest(), admission=admission, private_parent=private)
    mf, af = tmp_path/'manifest', tmp_path/'admission'
    mf.write_bytes(raw); af.write_text(json.dumps(admission))
    envelope = {'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
                'expected_head':scope['head'],'expected_base':scope['base'],
                'reviewer_actor':scope['reviewer'],'pull_request_author':'writer',
                'verdict':{'decision':'approve'}}
    verdict = private/'verdict.json'; verdict.write_text(json.dumps(envelope)); verdict.chmod(0o600)
    pr = {'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},
          'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    gh = tmp_path/'gh'
    gh.write_text('#!/bin/sh\n[ "$GH_TOKEN" = FRESH_READ_ONLY ] || exit 77\n' +
                  "printf '%s' '" + json.dumps(pr) + "'\n")
    gh.chmod(0o755)
    args = ['--revalidate-publish','--private-parent',str(private),'--source-root',str(source),
            '--manifest',str(mf),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
            '--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
            '--verdict-file',str(verdict)]
    env = {'PATH':str(tmp_path)+':/usr/bin:/bin','GH_TOKEN':token}
    result = subprocess.run([sys.executable,'-I','-B',str(ROOT/'scripts/ci/noema_bootstrap_producer.py'),*args],
                            env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode == 0, 'expired pre-model metadata token blocks publisher refresh'
    assert not (private/'publish.json').exists(), 'write grant issued before readonly fence'
    refresh = _step_block(workflow, refresh_name)
    writer = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    assert workflow.index("      - name: Prepare Noema model verdict") < workflow.index(refresh) < workflow.index(revalidate) < workflow.index(writer)
    assert APP_TOKEN_ACTION in refresh
    assert all(f"permission-{p}: read" in refresh for p in ('contents','metadata','pull-requests'))
    assert ': write' not in refresh and 'github.token' not in revalidate


def test_noema_remints_repository_scoped_app_token_after_model_before_publication() -> None:
    """A long model call must not publish with its predecessor App token."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = _step_block(workflow, "Prepare Noema model verdict")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert APP_TOKEN_ACTION in refresh
    assert "--phase prepare" in prepare
    assert "--phase publish" in publish
    assert 'scripts/ci/noema_existing_app_issuer.cjs' in prepare
    assert 'scripts/ci/noema_existing_app_issuer.cjs' in publish
    assert '--verdict-file "$verdict_file"' in prepare
    assert '--verdict-file "$verdict_file"' in publish
    assert workflow.index(prepare) < workflow.index(refresh) < workflow.index(publish)
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in prepare
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in publish
    assert 'export NOEMA_LLM_MODEL="orchestrator/auto"' in prepare
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
    assert "permission-pull-requests: read" in refresh
    assert "permission-pull-requests: write" not in refresh
    assert "permission-contents: read" in refresh
    assert "permission-actions: read" not in refresh
    assert "permission-checks: read" not in refresh
    assert "permission-security-events: read" not in refresh
    assert "permission-statuses: read" not in refresh
    assert "permission-vulnerability-alerts: read" not in refresh
    assert "permission-metadata: read" in refresh
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
    assert workflow.count("--phase prepare") == 1
    assert workflow.count("--phase publish") == 1
    assert '--phase-issuance' not in workflow
    issuer = (ROOT / 'scripts/ci/noema_existing_app_issuer.cjs').read_text()
    assert "'--'+phase+'-production'" in issuer
    assert "'--phase-issuance',file" in issuer
    assert '--prepare-verdict-file' not in workflow
    assert '--publish-verdict-file' not in workflow


@pytest.mark.parametrize("old_flag", ["--prepare-verdict-file", "--publish-verdict-file"])
def test_phase_contract_rejects_obsolete_flags_with_current_path_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_flag: str,
) -> None:
    """An extra obsolete flag must be rejected even beside valid phase calls."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    mutated = tmp_path / "noema-review.yml"
    current_flag = "--phase prepare" if old_flag == "--prepare-verdict-file" else "--phase publish"
    assert workflow.count(current_flag) == 1
    mutated.write_text(
        workflow.replace(current_flag, f"{current_flag} {old_flag}"), encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "WORKFLOW", mutated)
    with pytest.raises(AssertionError):
        test_prepare_and_publish_are_the_only_model_verdict_execution_path()
