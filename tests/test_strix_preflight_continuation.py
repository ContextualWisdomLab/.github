"""Exercise the actual post-failure dispatch shell without network or delay."""
import json
import os
import subprocess
from pathlib import Path


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
