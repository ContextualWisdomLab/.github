"""Execute source-only auto selection; never contact a provider or publish a review."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.test_agent_review_runtime_quality_consolidation import (
    test_ghas_runtime_selector_executes_the_actual_shell as execute_runtime_selector,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'scripts/ci/contextual_orchestrator_review_sidecar.sh'


def test_sidecar_accepts_auto_with_zero_cost_fence():
    text = SIDECAR.read_text()
    start = text.index('orchestrator_pool=')
    body = text[start:text.index('\nlog "starting review sidecar', start)]
    result = subprocess.run([shutil.which('bash'), '-c',
                             'fail() { exit 7; }; ' + body +
                             '\nprintf "%s\\n" "${pool_args[@]}"'],
                            env={'CONTEXTUAL_ORCHESTRATOR_POOL': 'auto'},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, 'auto request rejected by source pool guard'
    assert result.stdout.splitlines() == ['--pool', 'auto', '--zero-cost-only']


def test_opencode_generated_primary_aux_reset_and_diagnosis_use_auto(tmp_path):
    source = (ROOT / '.github/workflows/opencode-review-dispatch.yml').read_text()
    # Execute the actual two jq expressions with an inert workspace; no workflow/API/model.
    initial = re.search(r"jq -n '(\{\n.*?\n          \})' >\"\$\{OPENCODE_REVIEW_WORKDIR\}/opencode.jsonc\"", source, re.S)
    assert initial
    reset = re.search(r"gateway_config=.*?\n          jq '(.*?)' \"\$\{OPENCODE_REVIEW_WORKDIR\}/opencode.jsonc\"", source, re.S)
    assert reset
    jq = shutil.which('jq')
    assert jq
    first = subprocess.run([jq, '-n', initial[1]], capture_output=True, text=True, timeout=5)
    assert first.returncode == 0
    data = json.loads(first.stdout)
    assert data['model'] == data['small_model'] == 'contextual-orchestrator/orchestrator/auto'
    # Force conflicting preceding values; the real reset must restore both to auto.
    data.update(model='external/unsafe', small_model='external/unsafe')
    second = subprocess.run([jq, reset[1]], input=json.dumps(data), capture_output=True, text=True, timeout=5)
    assert second.returncode == 0
    data = json.loads(second.stdout)
    assert data['model'] == data['small_model'] == 'contextual-orchestrator/orchestrator/auto'
    assert set(data['provider']['contextual-orchestrator']['models']) == {'orchestrator/auto'}
    assert 'OPENCODE_MODEL_CANDIDATES: "contextual-orchestrator/orchestrator/auto"' in source
    assert 'MODEL: contextual-orchestrator/orchestrator/auto' in source


def test_noema_and_opencode_sidecar_pool_match_model_alias():
    for name in ('noema-review.yml', 'opencode-review-dispatch.yml'):
        source = (ROOT / '.github/workflows' / name).read_text()
        provision = source.split('      - name: Provision contextual-orchestrator review sidecar\n', 1)[1]
        provision = provision.split('      - name:', 1)[0]
        assert re.search(r'^          CONTEXTUAL_ORCHESTRATOR_POOL: auto$', provision, re.M)
    assert 'export NOEMA_LLM_MODEL="orchestrator/auto"' in (ROOT / '.github/workflows/noema-review.yml').read_text()


def test_tracked_opencode_defaults_do_not_restore_free():
    source = (ROOT / 'opencode.jsonc').read_text()
    config = json.loads('\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('//')))
    assert config['model'] == config['small_model'] == 'contextual-orchestrator/orchestrator/auto'
    assert 'orchestrator/auto' in config['provider']['contextual-orchestrator']['models']


@pytest.mark.parametrize('path', [
    'tests/test_review_auto_route.py',
    'tests/test_review_auto_cost_admission.py',
    'tests/test_review_ai_app_independence.py',
])
def test_auto_new_regressions_reach_existing_quality_selector_and_command(path, tmp_path):
    source = (ROOT / '.github/workflows/agent-review-runtime-quality-ci.yml').read_text()
    trigger = source.split('on:\n', 1)[1].split('\nconcurrency:', 1)[0]
    assert f'      - "{path}"' in trigger
    execute_runtime_selector(path, {'review_repair'}, tmp_path)
    step = source.split('- name: Verify scheduler and contextual-orchestrator review-repair contracts', 1)[1]
    script = step.split('        run: |\n', 1)[1].split('      - name:', 1)[0]
    first_pytest = script.split('python -m interrogate', 1)[0]
    assert path in first_pytest
