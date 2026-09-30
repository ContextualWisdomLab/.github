"""Exercise the actual post-failure dispatch shell without network or delay."""
import json
import os
import subprocess
from pathlib import Path

from scripts.ci import strix_runtime_capacity


def test_transport_continuation_uses_oidc_app_token_for_central_dispatch():
    """Consumer-scoped ``github.token`` must never dispatch to central ``.github``."""
    source = Path('.github/workflows/strix.yml').read_text()
    continuation = source.split('\n  continue-strix-transport:\n', 1)[1]

    assert '      id-token: write' in continuation
    assert '      - name: Exchange OpenCode app token for central Strix continuation' in continuation
    assert '/exchange_github_app_token' in continuation
    assert 'GH_TOKEN: ${{ steps.central_dispatch_app_token.outputs.token }}' in continuation
    assert 'GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || github.token }}' not in continuation


def test_dispatch_binds_live_head_base_and_ready_state(tmp_path):
    source = Path('.github/workflows/strix.yml').read_text()
    block = source.split('      - name: Schedule bounded Strix transport re-dispatch\n', 1)[1]
    shell = '\n'.join(line[10:] for line in block.split('        run: |\n', 1)[1].splitlines())
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    gh = bindir / 'gh'
    gh.write_text('#!/bin/bash\nif [[ "$*" == *"-X POST"* ]]; then cat > "$POSTED"; else cat "$LIVE"; fi\n')
    gh.chmod(0o700)
    sleep = bindir / 'sleep'
    sleep.write_text('#!/bin/bash\nexit 0\n')
    sleep.chmod(0o700)
    repo = 'ContextualWisdomLab/late-life-anxiety-reanalysis'
    head, base = 'a' * 40, 'b' * 40
    live = {'state': 'open', 'draft': False, 'head': {'sha': head, 'repo': {'full_name': repo}}, 'base': {'sha': base, 'ref': 'main', 'repo': {'full_name': repo}}}
    env = dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'], GITHUB_REPOSITORY='ContextualWisdomLab/.github', TARGET_REPOSITORY=repo, PR_NUMBER='269', EXPECTED_HEAD_SHA=head, EXPECTED_BASE_SHA=base, EXPECTED_BASE_REF='main', DELAY_SECONDS='60', NEXT_ATTEMPT='1', LIVE=str(tmp_path/'live.json'), POSTED=str(tmp_path/'post.json'))
    for change in ({}, {'head': {'sha': 'c'*40, 'repo': {'full_name': repo}}}, {'base': {'sha': base, 'ref': 'other', 'repo': {'full_name': repo}}}, {'draft': True}, {'draft': 'false'}, {'state': 'closed'}):
        Path(env['LIVE']).write_text(json.dumps(live | change))
        posted = Path(env['POSTED'])
        posted.unlink(missing_ok=True)
        result = subprocess.run(['bash', '-c', shell], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert posted.exists() == (not change)
        if not change:
            payload = json.loads(posted.read_text())
            assert payload['event_type'] == 'strix-scan'
            assert payload['client_payload'] == {'target_repository': repo, 'pr_number': 269, 'pr_head_sha': head, 'pr_base_sha': base, 'pr_base_ref': 'main', 'transport_retry_attempt': 1}
    for attempt in ['0', '3', 'garbage']:
        posted.unlink(missing_ok=True)
        result = subprocess.run(['bash', '-c', shell], env=env | {'NEXT_ATTEMPT': attempt}, capture_output=True, text=True)
        assert result.returncode != 0
        assert not posted.exists()


def test_workflow_classifier_invocation_emits_bounded_capacity(tmp_path):
    source = Path('.github/workflows/strix.yml').read_text()
    block = source.split('      - name: Classify all-429 Strix sidecar failure\n', 1)[1].split('      - name:', 1)[0]
    shell = '\n'.join(line[10:] for line in block.split('        run: |\n', 1)[1].splitlines())
    reports = tmp_path / 'strix_runs'
    reports.mkdir()
    report = reports / 'contextual-orchestrator-preflight.json'
    report.write_text(json.dumps({'contract': 'strix-plain-chat-preflight-v2', 'ready_count': 0, 'probed_count': 1, 'routes': [{'status': 'rejected', 'http_status': 429}]}))
    output = tmp_path / 'output'
    env = dict(os.environ, TRUSTED_STRIX_SOURCE=str(Path.cwd()), GITHUB_WORKSPACE=str(tmp_path), EXPECTED_HEAD_SHA='a'*40, NOEMA_TRANSPORT_RETRY_ATTEMPT='0', GITHUB_OUTPUT=str(output))
    result = subprocess.run(['bash', '-c', shell], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    emitted = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert emitted['transport_capacity_unavailable'] == 'true'
    assert emitted['transport_retry_eligible'] == 'true'
    assert emitted['transport_retry_next_attempt'] == '1'
    result = subprocess.run(['bash', '-c', shell], env=env | {'NOEMA_TRANSPORT_RETRY_ATTEMPT': '2', 'GITHUB_OUTPUT': str(tmp_path/'exhausted')}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'transport_retry_eligible=false' in (tmp_path/'exhausted').read_text()


def test_runtime_provider_failure_emits_bounded_continuation_without_passing(tmp_path):
    source = Path('.github/workflows/strix.yml').read_text()
    assert 'id: strix_scan' in source
    assert 'steps.strix_scan.outputs.transport_retry_eligible' in source
    block = source.split('          strix_neutralization_scope_log="$strix_terminal_log"', 1)[1]
    block = 'strix_neutralization_scope_log="$strix_terminal_log"' + block.split('      - name: Collect Strix reports', 1)[0]
    log = tmp_path / 'strix_gate_console.log'
    log.write_text('LLM CONNECTION FAILED\nError: Request timed out.\n')
    output = tmp_path / 'output'
    env = dict(os.environ, TRUSTED_STRIX_SOURCE=str(Path.cwd()), PYTHONPATH=str(Path.cwd()),
               RUNNER_TEMP=str(tmp_path), PR_HEAD_SHA='a'*40, GITHUB_OUTPUT=str(output),
               NOEMA_TRANSPORT_RETRY_ATTEMPT='0')
    script = '\n'.join((
        'strix_terminal_log="$RUNNER_TEMP/strix_gate_console.log"',
        'strix_rc=1',
        "backend_unavailable_signal='LLM CONNECTION FAILED|STRIX_PROVIDER_UNAVAILABLE'",
        "runtime_transport_signal='LLM CONNECTION FAILED'",
        "model_behavior_error_signal='ModelBehaviorError'",
        "reported_vulnerability_signal='Vulnerabilities[[:space:]]+[1-9]|severity[[:space:]]*:'",
        "tooling_error_signal='STRIX_TOOLING_ERROR'",
        block,
    ))
    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    emitted = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert emitted['transport_capacity_unavailable'] == 'true'
    assert emitted['transport_retry_eligible'] == 'true'
    assert emitted['transport_retry_next_attempt'] == '1'

    output.unlink()
    result = subprocess.run(['bash', '-c', script], env=env | {'NOEMA_TRANSPORT_RETRY_ATTEMPT': '2'}, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'transport_retry_eligible=false' in output.read_text()

    output.unlink()
    log.write_text('LLM CONNECTION FAILED\nVulnerability Report\nSeverity: CRITICAL\n')
    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert not output.exists()

    log.write_text('STRIX_PROVIDER_UNAVAILABLE: STRIX_SANDBOX_UNAVAILABLE\n')
    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert not output.exists()

    log.write_text('LLM CONNECTION FAILED\nSTRIX_SANDBOX_UNAVAILABLE\n')
    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert not output.exists()


def test_runtime_capacity_module_covers_head_and_retry_budget(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setattr('sys.argv', ['strix_runtime_capacity', '--expected-head', 'invalid'])
    assert strix_runtime_capacity.main() == 0
    assert not output.exists()

    monkeypatch.setattr('sys.argv', ['strix_runtime_capacity', '--expected-head', 'a'*40])
    monkeypatch.setenv('NOEMA_TRANSPORT_RETRY_ATTEMPT', '0')
    assert strix_runtime_capacity.main() == 0
    assert 'transport_retry_eligible=true' in output.read_text()
    assert 'transport_retry_next_attempt=1' in output.read_text()

    output.unlink()
    monkeypatch.setenv('NOEMA_TRANSPORT_RETRY_ATTEMPT', '2')
    assert strix_runtime_capacity.main() == 0
    assert 'transport_retry_eligible=false' in output.read_text()
