"""Production premerge caller regressions; no live credentials or inference."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_phases_use_controller_and_preserve_refresh_order():
    """Both real phase steps must enter the controller, with refresh between them."""
    source = (ROOT / '.github/workflows/noema-review.yml').read_text()
    prepare = source.split('      - name: Prepare Noema model verdict\n', 1)[1].split('      - name:', 1)[0]
    publish = source.split('      - name: Publish prepared Noema verdict on the exact live head\n', 1)[1].split('\n  continue-noema-transport:', 1)[0]
    for step, phase in [(prepare, 'prepare'), (publish, 'publish')]:
        assert 'premerge_review_tooling.py' in step, 'phase bypasses controller'
        assert '--' + phase + '-production' in step
        assert '--tooling-root "$RUNNER_TEMP/noema-immutable-tooling"' in step
        assert '--phase-issuance "$RUNNER_TEMP/noema-' + phase + '-issuance.json"' in step
        assert '.github/actions/noema-review/two_phase.py"' not in step
    assert source.index('Prepare Noema model verdict\n') < source.index('Refresh repository-scoped Noema GitHub App token for publication\n') < source.index('Publish prepared Noema verdict on the exact live head\n')



def test_production_noema_requires_pinned_admission_before_reviewer_credentials():
    """Production must invoke admission before minting model/publication authority."""
    source = (ROOT / '.github/workflows/noema-review.yml').read_text()
    name = '      - name: Admit independently pinned premerge tooling and execution\n'
    assert name in source, 'production Noema has no premerge controller admission caller'
    step = source.split(name, 1)[1].split('      - name:', 1)[0]
    assert 'scripts/ci/premerge_review_tooling.py' in step
    assert '--admit-production' in step
    assert 'vars.NOEMA_TOOLING_MANIFEST_SHA256' in step
    assert 'vars.NOEMA_EXECUTION_ADMISSION_SHA256' in step
    assert source.index(name) < source.index('      - name: Select fail-closed Noema reviewer credential\n')
    assert 'LLM_GATEWAY_API_KEY' not in step
    assert '--accepted-digest "$NOEMA_TOOLING_MANIFEST_SHA256"' in step


def test_actual_cli_refuses_missing_independent_pins(tmp_path):
    """An unconfigured production caller cannot silently return success."""
    result = subprocess.run(
        [sys.executable, '-I', '-B', str(ROOT / 'scripts/ci/premerge_review_tooling.py'),
         '--admit-production', '--tooling-root', str(tmp_path),
         '--manifest', str(tmp_path / 'manifest.json'), '--accepted-digest', '',
         '--admission', str(tmp_path / 'admission.json'), '--admission-digest', '',
         '--repo', 'ContextualWisdomLab/example', '--pr-number', '7',
         '--expected-head', 'a' * 40],
        env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0, 'CLI ignored unconfigured independent admission'
    assert 'independent admission pins' in result.stderr


def test_actual_production_cli_binds_manifest_and_live_scope(tmp_path):
    """Real CLI reaches an inert metadata executable only after independent pins."""
    import hashlib
    import json

    root = tmp_path / 'tooling'
    entry = root / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'# INERT SOURCE FIXTURE\n')
    manifest = {'schema_version': 1, 'repository': 'ContextualWisdomLab/.github',
                'commit': 'b' * 40, 'tree': 'c' * 40,
                'entrypoint': '.github/actions/noema-review/two_phase.py',
                'files': {'.github/actions/noema-review/two_phase.py': hashlib.sha256(entry.read_bytes()).hexdigest()}}
    scope = {'repository': 'ContextualWisdomLab/example', 'number': 7, 'head': 'a' * 40,
             'base': 'd' * 40, 'author': 'writer', 'reviewer': 'cwl-noema-review[bot]'}
    admission = {'scope': scope, **{name: True for name in
                 ('isolated_clean_job', 'native_custody', 'supplier_cost', 'supplier_retention', 'issuer_phase_separation')}}
    manifest_path = tmp_path / 'manifest.json'
    admission_path = tmp_path / 'admission.json'
    manifest_path.write_text(json.dumps(manifest))
    admission_path.write_text(json.dumps(admission))
    pr = {'base': {'sha': scope['base'], 'repo': {'full_name': scope['repository']}},
          'head': {'sha': scope['head']}, 'number': 7, 'user': {'login': 'writer'},
          'state': 'open', 'draft': False}
    gh = tmp_path / 'gh'
    gh.write_text('#!/bin/sh\nprintf \'%s\' \'' + json.dumps(pr) + '\'\n')
    gh.chmod(0o700)
    command = [sys.executable, '-I', '-B', str(ROOT / 'scripts/ci/premerge_review_tooling.py'),
               '--admit-production', '--tooling-root', str(root), '--manifest', str(manifest_path),
               '--accepted-digest', hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
               '--admission', str(admission_path), '--admission-digest', hashlib.sha256(admission_path.read_bytes()).hexdigest(),
               '--repo', scope['repository'], '--pr-number', '7', '--expected-head', scope['head']]
    result = subprocess.run(command, env={'PATH': str(tmp_path) + ':/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    # An otherwise-valid independently pinned NOT_HELD receipt cannot pass.
    admission['native_custody'] = False
    admission_path.write_text(json.dumps(admission))
    command[command.index('--admission-digest') + 1] = hashlib.sha256(admission_path.read_bytes()).hexdigest()
    gh.write_text('#!/bin/sh\nexit 99\n')
    result = subprocess.run(command, env={'PATH': str(tmp_path) + ':/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert 'custody/scope evidence unavailable' in result.stderr


def test_production_run_invokes_controller_with_phase_scoped_issuance(tmp_path, monkeypatch):
    """Full caller reaches controller, loader and independent phase environments."""
    import importlib.util
    import hashlib
    import json
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location('production_caller_test', ROOT / 'scripts/ci/premerge_review_tooling.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'source'
    entry = root / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'# FIXTURE ONLY\n')
    files = {'.github/actions/noema-review/two_phase.py': entry.read_bytes()}
    manifest = {'schema_version': 1, 'repository': 'ContextualWisdomLab/.github', 'commit': 'b'*40,
                'tree': 'c'*40, 'entrypoint': next(iter(files)),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    scope = {'repository': 'ContextualWisdomLab/example', 'number': 7, 'head': 'a'*40,
             'base': 'd'*40, 'author': 'writer', 'reviewer': 'cwl-noema-review[bot]'}
    admission = {'scope': scope, 'installation_id': 7, **{name: True for name in
                 ('isolated_clean_job','native_custody','supplier_cost','supplier_retention','issuer_phase_separation')}}
    paths = {}
    for name, data in [('manifest', manifest), ('admission', admission),
                       ('prepare', {'token': 'SYNTHETIC_READ', 'permissions': {'contents':'read','metadata':'read','pull_requests':'read'}, 'repositories':[{'full_name':scope['repository']}]}),
                       ('publish', {'token': 'SYNTHETIC_WRITE', 'permissions': {'contents':'read','metadata':'read','pull_requests':'write'}, 'repositories':[{'full_name':scope['repository']}]})]:
        paths[name] = tmp_path / (name + '.json')
        paths[name].write_text(json.dumps(data))
        paths[name].chmod(0o600)
    pr = {'base': {'sha':scope['base'],'repo':{'full_name':scope['repository']}},
          'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(pr)))
    monkeypatch.setenv('LLM_GATEWAY_API_KEY','SYNTHETIC_INFERENCE')
    events = []

    def run_controller(raw, **kwargs):
        events.append('controller')
        kwargs['require_execution_admission']()
        tooling = kwargs['load_tooling']()
        assert tooling.phase_environment('prepare')['GH_TOKEN'] == 'SYNTHETIC_READ'
        assert tooling.phase_environment('prepare')['NOEMA_LLM_MODEL'] == 'auto'
        kwargs['refresh_publisher']()
        env = tooling.phase_environment('publish')
        assert env['GH_TOKEN'] == 'SYNTHETIC_WRITE'
        assert 'NOEMA_LLM_API_KEY' not in env
        return 0

    monkeypatch.setattr(module, 'run_review', run_controller)
    argv = ['--run-production','--tooling-root',str(root),'--manifest',str(paths['manifest']),
            '--accepted-digest',hashlib.sha256(paths['manifest'].read_bytes()).hexdigest(),
            '--admission',str(paths['admission']),'--admission-digest',hashlib.sha256(paths['admission'].read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
            '--prepare-issuance',str(paths['prepare']),'--publish-issuance',str(paths['publish']),
            '--private-parent',str(tmp_path)]
    assert module.production_main(argv) == 0
    assert events == ['controller'], 'production caller returned without controller execution'
