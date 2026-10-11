"""Execute parsed OSV shell boundaries with a bounded synthetic container."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/security-scan.yml').read_text())['jobs']['osv-scan']['steps']


def step(name):
    return next(s for s in STEPS if s['name'] == name)


def execute(name, env, cwd):
    s = step(name)
    run = s['run']
    if 'OSV_CONTROL' in env:
        run = run.replace('${{ steps.osv_prepare.outputs.control }}', env.get('CREATED_CONTROL', env['OSV_CONTROL']))
    argv = [env['PYTHON'], '-c', run] if s.get('shell', '').startswith('python') else ['bash', '-e', '-c', run]
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=10)


@pytest.fixture
def lifecycle(tmp_path):
    import sys
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'source').mkdir()
    (workspace / 'old-results.json').write_text('{"stale": true}')
    sentinel = tmp_path / 'sentinel'
    sentinel.write_text('preserve')
    binpath = tmp_path / 'bin'
    binpath.mkdir()
    (binpath / 'python3').symlink_to(sys.executable)
    fake = binpath / 'docker'
    fake.write_text('#!/usr/bin/env python3\nimport os, sys, pathlib, json, time, subprocess, signal\nargs = sys.argv[1:]\ncontrol = pathlib.Path(os.environ[\'OSV_CONTROL\'])\nstate = pathlib.Path(os.environ[\'FAKE_STATE\'])\nwith pathlib.Path(os.environ[\'FAKE_CALLS\']).open(\'a\') as calls:\n    calls.write(json.dumps(args)+\'\\n\')\nif args[0] == \'run\':\n    if \'--entrypoint\' not in args or \'/root/osv-scanner\' not in args or \'--verbosity=error\' not in args:\n        raise ValueError(\'Wrong scanner boundary\')\n    if not any(\'v2.5.1@sha256:dcd947\' in a for a in args):\n        raise ValueError(\'Wrong image pin\')\n    volumes = [args[i+1] for i,a in enumerate(args) if a == \'--volume\']\n    if any(str(control) in a for a in volumes):\n        raise ValueError(\'Control root mounted into scanner\')\n    name = args[args.index(\'--name\')+1]\n    if state.exists() and os.environ.get(\'FAKE_MODE\') not in (\'failed-before-cid\', \'interrupt-before-cid\'):\n        sys.exit(125)\n    if os.environ.get(\'FAKE_MODE\') == \'failed-before-cid\':\n        sys.exit(125)\n    if os.environ.get(\'FAKE_MODE\') == \'interrupt-before-cid\':\n        os.kill(os.getppid(), signal.SIGTERM)\n        time.sleep(20)\n        sys.exit(125)\n    cid = \'c\' * 64\n    pathlib.Path(args[args.index(\'--cidfile\')+1]).write_text(cid)\n    output = next(a.split(\'=\',1)[1] for a in args if a.startswith(\'--output-file=\'))\n    p = pathlib.Path(os.environ[\'OSV_ROOT\']) / output.removeprefix(\'/evidence/\')\n    mode = os.environ.get(\'FAKE_MODE\',\'complete\')\n    data = {\'Id\':cid,\'Name\':\'/\'+name,\'State\':{\'Running\':mode != \'complete\',\'ExitCode\':int(os.environ.get(\'FAKE_CHILD_EXIT\',os.environ.get(\'FAKE_EXIT\',\'0\')))}}\n    p.write_text(os.environ.get(\'FAKE_JSON\',\'{"results":null}\'))\n    if mode != \'complete\':\n        writer_code = "import pathlib,sys,time,signal; p=pathlib.Path(sys.argv[1]); marker=pathlib.Path(sys.argv[2]); marker.write_text(\'active\'); signal.signal(signal.SIGTERM,lambda *a:(marker.unlink(missing_ok=True),sys.exit(0))); exec(\'while True:\\\\n p.write_text(\\"still writing\\"); time.sleep(0.02)\')"\n        writer = subprocess.Popen([sys.executable,\'-c\',writer_code,str(p),str(control / \'writing\')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n        data[\'writer_pid\'] = writer.pid\n        for _ in range(100):\n            if (control / \'writing\').exists():\n                break\n            time.sleep(0.01)\n        if not (control / \'writing\').exists():\n            raise ValueError(\'synthetic writer startup missing\')\n    state.write_text(json.dumps(data))\n    if mode == \'signal\':\n        os.kill(os.getppid(),signal.SIGTERM)\n    if mode != \'complete\':\n        time.sleep(20)\n    sys.stderr.write(os.environ.get(\'FAKE_ERR\',\'\'))\n    sys.exit(int(os.environ.get(\'FAKE_EXIT\',\'0\')))\nelif args[0] == \'inspect\':\n    if not state.exists():\n        sys.exit(1)\n    data = json.loads(state.read_text())\n    if args[-1] not in (data[\'Id\'],data[\'Name\'].lstrip(\'/\')):\n        raise ValueError(\'foreign inspect\')\n    print(json.dumps([data[\'Id\'], data[\'Name\'], data[\'State\']]))\nelif args[0] == \'stop\':\n    data = json.loads(state.read_text())\n    if args[-1] != data[\'Id\']:\n        raise ValueError(\'foreign stop\')\n    if \'writer_pid\' in data:\n        os.kill(data[\'writer_pid\'],signal.SIGTERM)\n        for _ in range(100):\n            if not (control / \'writing\').exists():\n                break\n            time.sleep(0.01)\n        if (control / \'writing\').exists():\n            raise ValueError(\'writer not settled\')\n    data[\'State\'][\'Running\'] = False\n    state.write_text(json.dumps(data))\nelif args[0] == \'rm\':\n    data = json.loads(state.read_text())\n    if args[-1] != data[\'Id\'] or data[\'State\'][\'Running\']:\n        raise ValueError(\'foreign or running removal\')\n    state.unlink()\nelif args[0] == \'ps\':\n    if os.environ.get(\'FAKE_INVENTORY_FAIL\') == \'1\':\n        sys.exit(1)\n    if state.exists():\n        data = json.loads(state.read_text())\n        value = args[-1]\n        if value == \'name=^\'+data[\'Name\']+\'$\' or value == \'id=\'+data[\'Id\']:\n            print(data[\'Id\'])\nelse:\n    raise ValueError(\'Unknown synthetic docker operation\')\n')
    fake.chmod(0o755)
    env = {**os.environ, 'PYTHON': sys.executable, 'PATH': str(binpath) + os.pathsep + os.environ['PATH'], 'RUNNER_TEMP': str(tmp_path), 'GITHUB_WORKSPACE': str(workspace), 'GITHUB_OUTPUT': str(tmp_path / 'output'), 'OSV_RUN': '123:1', 'OSV_BASE_REV': 'a' * 40, 'OSV_HEAD_REV': 'b' * 40}
    result = execute('Prepare observable OSV lifecycle', env, workspace)
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split('=', 1) for line in (tmp_path / 'output').read_text().splitlines())
    env.update(OSV_ROOT=outputs['root'], OSV_IDENTITY=outputs['identity'], OSV_NONCE=outputs['nonce'], OSV_CONTROL=outputs.get('control', outputs['root']), CREATED_CONTROL=outputs.get('control', outputs['root']), OSV_BASE_OUTCOME='success', OSV_BASE_RETRY_OUTCOME='skipped', OSV_HEAD_OUTCOME='success', OSV_HEAD_RETRY_OUTCOME='skipped')
    env.update(FAKE_STATE=str(tmp_path / 'synthetic-container.json'), FAKE_CALLS=str(tmp_path / 'docker-calls.jsonl'))
    yield env, workspace, sentinel
    if Path(env['OSV_ROOT']).exists() and env.get('PRESERVE_EVIDENCE') != '1':
        result = execute('Cleanup observable OSV lifecycle', env, workspace)
        assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == 'preserve'
    assert (workspace / 'old-results.json').read_text() == '{"stale": true}'


@pytest.mark.parametrize('optimization', ['0', '1', '2'])
@pytest.mark.parametrize(('rc', 'err', 'accepted'), [(1, '', True), (0, '', True), (1, 'error', False), (0, 'error', False), (127, '', False), (129, '', False), (130, '', False)])
def test_child_exit_and_stderr_admission(lifecycle, rc, err, accepted, optimization):
    env, cwd, _ = lifecycle
    env.update(PYTHONOPTIMIZE=optimization)
    env.update(FAKE_EXIT=str(rc), FAKE_ERR=err)
    result = execute('Scan base with OSV', env, cwd)
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr
    receipt = json.loads((Path(env['OSV_ROOT']) / 'base-first/receipt.json').read_text())
    assert receipt['exit'] == rc and receipt['completed'] is True
    assert (Path(env['OSV_ROOT']) / 'old-results.json').exists() == accepted


def test_failed_partial_json_then_fresh_retry(lifecycle):
    env, cwd, _ = lifecycle
    env.update(FAKE_EXIT='127', FAKE_JSON='{"results":')
    assert execute('Scan base with OSV', env, cwd).returncode != 0
    root = Path(env['OSV_ROOT'])
    assert not (root / 'old-results.json').exists()
    env.update(FAKE_EXIT='1', FAKE_JSON='{"results":null}')
    assert execute('Retry base OSV without transitive resolution', env, cwd).returncode == 0
    assert (root / 'base-first/results.json').read_text() == '{"results":'
    env.update(OSV_BASE_OUTCOME='failure', OSV_BASE_RETRY_OUTCOME='success')
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    assert execute('Require OSV scan output', env, cwd).returncode == 0
    assert execute('Retry base OSV without transitive resolution', env, cwd).returncode != 0
    assert execute('Require OSV scan output', env, cwd).returncode != 0
    assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode == 0
    assert not root.exists()


def test_stale_json_has_no_admission(lifecycle):
    env, cwd, _ = lifecycle
    root = Path(env['OSV_ROOT'])
    (root / 'base-first').mkdir()
    (root / 'base-first/results.json').write_text('{"results":null}')
    assert execute('Scan base with OSV', env, cwd).returncode != 0
    assert not (root / 'old-results.json').exists()


@pytest.mark.parametrize('optimization', ['0', '1', '2'])
def test_alias_and_identity_cannot_cleanup(lifecycle, optimization):
    env, cwd, _ = lifecycle
    env['PYTHONOPTIMIZE'] = optimization
    alias = cwd / 'alias'
    alias.symlink_to(env['OSV_ROOT'], target_is_directory=True)
    altered = {**env, 'OSV_ROOT': str(alias)}
    assert execute('Cleanup observable OSV lifecycle', altered, cwd).returncode != 0
    assert Path(env['OSV_ROOT']).exists()
    altered = {**env, 'OSV_NONCE': 'wrong'}
    assert execute('Cleanup observable OSV lifecycle', altered, cwd).returncode != 0


def test_symlink_output_is_rejected(lifecycle):
    env, cwd, sentinel = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    path = Path(env['OSV_ROOT']) / 'base-first/results.json'
    path.unlink()
    path.symlink_to(sentinel)
    result = subprocess.run([env['PYTHON'], str(Path(env['OSV_CONTROL']) / 'validate.py'), 'admit', 'base-first', 'old-results.json'], env=env, capture_output=True, timeout=10)
    assert result.returncode != 0


def test_coherent_environment_retarget_preserves_foreign_root(lifecycle):
    import shutil
    env, cwd, sentinel = lifecycle
    foreign = cwd / 'foreign'
    foreign.mkdir(mode=0o700)
    st = foreign.stat()
    identity = f'{st.st_dev}:{st.st_ino}'
    (foreign / 'identity.json').write_text(json.dumps({'nonce': 'foreign', 'identity': identity, 'root': str(foreign)}))
    (foreign / 'owned-by-other').write_text('preserve')
    original_validator = Path(env['OSV_ROOT']) / 'validate.py'
    if original_validator.exists():
        shutil.copyfile(original_validator, foreign / 'validate.py')
    altered = {**env, 'OSV_ROOT': str(foreign), 'OSV_IDENTITY': identity, 'OSV_NONCE': 'foreign', 'OSV_CONTROL': str(foreign)}
    result = execute('Cleanup observable OSV lifecycle', altered, cwd)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (foreign / 'owned-by-other').read_text() == 'preserve'
    assert sentinel.read_text() == 'preserve'


def test_private_root_and_identity_modes_are_enforced(lifecycle):
    env, cwd, _ = lifecycle
    root = Path(env['OSV_ROOT'])
    root.chmod(0o777)
    try:
        assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
    finally:
        if root.exists():
            root.chmod(0o700)
    identity = root / 'identity.json'
    identity.chmod(0o666)
    try:
        assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
    finally:
        if identity.exists():
            identity.chmod(0o600)


def test_modified_final_is_rejected(lifecycle):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    (Path(env['OSV_ROOT']) / 'old-results.json').write_text('{"results":[]}')
    assert execute('Require OSV scan output', env, cwd).returncode != 0


@pytest.mark.parametrize(('first', 'retry'), [('failure', 'skipped'), ('failure', 'failure'), ('cancelled', 'skipped')])
def test_published_output_of_failed_step_is_rejected(lifecycle, first, retry):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    env.update(OSV_BASE_OUTCOME=first, OSV_BASE_RETRY_OUTCOME=retry)
    assert execute('Require OSV scan output', env, cwd).returncode != 0


def test_numeric_completion_receipt_is_rejected(lifecycle):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    receipt = Path(env['OSV_CONTROL']) / 'old-results.json.receipt.json'
    if not receipt.exists():
        receipt = Path(env['OSV_ROOT']) / 'base-first/receipt.json'
    data = json.loads(receipt.read_text())
    data['completed'] = 1
    receipt.write_text(json.dumps(data))
    assert execute('Require OSV scan output', env, cwd).returncode != 0


@pytest.mark.parametrize(('outcome', 'results', 'accepted', 'comprehensive'), [
    ('success', [], True, True),
    ('failure', [], False, False),
    ('failure', [{'message': {'text': 'vulnerability'}}], True, False),
])
def test_reporter_failure_cannot_close_clean_alerts(lifecycle, outcome, results, accepted, comprehensive):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    assert execute('Require OSV scan output', env, cwd).returncode == 0
    env['OSV_REPORTER_OUTCOME'] = outcome
    path = Path(env['OSV_ROOT']) / 'results.sarif'
    path.write_text(json.dumps({'version': '2.1.0', 'runs': [{'tool': {'driver': {'name': 'osv-scanner'}}, 'results': results}]}))
    result = execute('Mark clean OSV SARIF as comprehensive', env, cwd)
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr
    if accepted:
        assert json.loads(path.read_text())['runs'][0]['tool']['driver']['isComprehensive'] is comprehensive


@pytest.mark.parametrize('bad', ['', '{"version":"2.1.0","runs":[]}', '{"runs":[{}]}', 'symlink'])
def test_sarif_admission_rejects_empty_partial_and_symlink(lifecycle, bad):
    env, cwd, sentinel = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    assert execute('Require OSV scan output', env, cwd).returncode == 0
    env['OSV_REPORTER_OUTCOME'] = 'success'
    path = Path(env['OSV_ROOT']) / 'results.sarif'
    if bad == 'symlink':
        path.symlink_to(sentinel)
    else:
        path.write_text(bad)
    assert execute('Mark clean OSV SARIF as comprehensive', env, cwd).returncode != 0
    assert 'admitted=true' not in Path(env['GITHUB_OUTPUT']).read_text()
    upload = step('Upload OSV SARIF to code scanning')['if']
    assert "steps.osv_sarif_admission.outcome == 'success'" in upload
    assert "steps.osv_sarif_admission.outputs.admitted == 'true'" in upload


def debug_upload_plan(prepare, root, admission):
    """Evaluate the parsed guard and render paths, without accessing them."""
    upload = step('Upload OSV debug artifacts')
    values = {
        'steps.osv_prepare.outcome': prepare,
        'steps.osv_prepare.outputs.root': root,
        'steps.osv_require.outcome': admission,
    }
    expression = upload['if'].replace('always()', 'True').replace('&&', ' and ')
    for key, value in values.items():
        expression = expression.replace(key, repr(value))
    eligible = eval(expression, {'__builtins__': {}}, {})
    rendered = upload['with']['path'].replace('${{ steps.osv_prepare.outputs.root }}', root)
    return eligible, rendered.splitlines()


@pytest.mark.parametrize('prepare', ['failure', 'skipped', 'cancelled', '', 'unknown'])
@pytest.mark.parametrize('root', ['', '/synthetic-existing-foreign-root'])
def test_debug_upload_rejects_failed_prepare(prepare, root):
    eligible, paths = debug_upload_plan(prepare, root, 'success')
    # Missing outputs really render absolute foreign paths; never touch them.
    if not root:
        assert paths == ['/old-results.json', '/new-results.json', '/results.sarif']
    assert eligible is False, f'failed prepare admitted foreign paths: {paths}'


@pytest.mark.parametrize(('root', 'admission'), [
    ('', 'success'),
    ('/synthetic-existing-foreign-root', 'failure'),
    ('/synthetic-existing-foreign-root', 'skipped'),
    ('/synthetic-existing-foreign-root', 'cancelled'),
    ('/synthetic-existing-foreign-root', ''),
    ('/synthetic-existing-foreign-root', 'unknown'),
])
def test_debug_upload_requires_current_root_admission(root, admission):
    eligible, paths = debug_upload_plan('success', root, admission)
    assert eligible is False, f'unadmitted root eligible: {paths}'


def test_debug_upload_keeps_admitted_failure_diagnostics(lifecycle):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    assert execute('Require OSV scan output', env, cwd).returncode == 0
    # The reporter can fail after this admission. Debug retention is not a pass.
    root = Path(env['OSV_ROOT'])
    (root / 'results.sarif').write_text('{"partial":')
    eligible, paths = debug_upload_plan('success', str(root), 'success')
    assert eligible is True
    assert paths == [str(root / name) for name in
                     ('old-results.json', 'new-results.json', 'results.sarif')]
    assert all(Path(path).is_file() for path in paths)
    assert step('Upload OSV debug artifacts')['continue-on-error'] is True
    assert 'continue-on-error' not in step('Report PR-introduced OSV findings')


def test_debug_upload_rejects_actual_current_root_admission_failure(lifecycle):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    rejected = execute('Require OSV scan output', {**env, 'OSV_NONCE': 'foreign'}, cwd)
    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    eligible, _ = debug_upload_plan('success', env['OSV_ROOT'], 'failure')
    assert eligible is False


def test_setup_failure_skips_sarif_upload():
    guard = step('Upload OSV SARIF to code scanning')['if']
    assert "steps.osv_prepare.outcome == 'success'" in guard
    assert "steps.osv_sarif_admission.outcome == 'success'" in guard
    # Evaluate the actual parsed guard, including the output condition.
    for prepare, admission, admitted, expected in [
        ('failure', 'skipped', '', False),
        ('success', 'failure', '', False),
        ('success', 'success', '', False),
        ('success', 'success', 'true', True),
    ]:
        expression = guard.replace('always()', 'True').replace('&&', ' and ')
        for key, value in {
            'steps.osv_prepare.outcome': prepare,
            'steps.osv_sarif_admission.outcome': admission,
            'steps.osv_sarif_admission.outputs.admitted': admitted,
        }.items():
            expression = expression.replace(key, repr(value))
        assert eval(expression, {'__builtins__': {}}, {}) is expected


@pytest.mark.parametrize('mode', ['timeout', 'signal'])
def test_owned_scanner_settles_before_evidence_cleanup(lifecycle, mode):
    env, cwd, sentinel = lifecycle
    env.update(FAKE_MODE=mode, OSV_SCAN_DEADLINE='2')
    result = execute('Scan base with OSV', env, cwd)
    assert result.returncode != 0, result.stdout + result.stderr
    root = Path(env['OSV_ROOT'])
    owned = Path(env['OSV_CONTROL']) / 'base-first-owned.json'
    assert owned.exists(), 'owned scanner creation and settlement witness missing'
    data = json.loads(owned.read_text())
    assert data['settled'] is True and data['cid'] == 'c' * 64
    receipt = json.loads((Path(env['OSV_CONTROL']) / 'base-first.json').read_text())
    assert receipt['completed'] is False
    assert not (Path(env['OSV_CONTROL']) / 'writing').exists()
    assert not (root / 'old-results.json').exists()
    assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode == 0
    assert not root.exists()
    assert sentinel.read_text() == 'preserve'


def test_unsettled_writer_blocks_evidence_deletion(lifecycle):
    env, cwd, _ = lifecycle
    owned = Path(env['OSV_CONTROL']) / 'base-first-owned.json'
    owned.write_text(json.dumps({'settled': False, 'name': 'osv-foreign'}))
    assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
    assert Path(env['OSV_ROOT']).exists()
    owned.unlink()


def test_nonregular_identity_and_replaced_root_are_rejected(lifecycle):
    env, cwd, sentinel = lifecycle
    root = Path(env['OSV_ROOT'])
    identity = root / 'identity.json'
    saved = identity.read_bytes()
    identity.unlink()
    identity.mkdir()
    try:
        assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
    finally:
        identity.rmdir()
        identity.write_bytes(saved)
        identity.chmod(0o600)
    old = root.with_name(root.name + '-retained')
    root.rename(old)
    root.mkdir(mode=0o700)
    (root / 'identity.json').write_bytes(saved)
    (root / 'identity.json').chmod(0o600)
    (root / 'foreign').write_text('preserve')
    try:
        assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
        assert (root / 'foreign').read_text() == 'preserve'
        assert sentinel.read_text() == 'preserve'
    finally:
        import shutil
        shutil.rmtree(root)
        old.rename(root)


@pytest.mark.parametrize('field', ['run', 'revision', 'digest', 'attempt'])
def test_final_receipt_current_bindings_are_checked(lifecycle, field):
    env, cwd, _ = lifecycle
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    assert execute('Scan head with OSV', env, cwd).returncode == 0
    path = Path(env['OSV_CONTROL']) / 'old-results.json.receipt.json'
    receipt = json.loads(path.read_text())
    receipt[field] = 'changed'
    path.write_text(json.dumps(receipt))
    assert execute('Require OSV scan output', env, cwd).returncode != 0


def test_docker_transport_is_not_scanner_exit(lifecycle):
    env, cwd, _ = lifecycle
    env.update(FAKE_EXIT='0', FAKE_CHILD_EXIT='127')
    assert execute('Scan base with OSV', env, cwd).returncode != 0
    receipt = json.loads((Path(env['OSV_CONTROL']) / 'base-first.json').read_text())
    assert receipt['transport_exit'] == 0 and receipt['exit'] == 127
    assert not (Path(env['OSV_ROOT']) / 'old-results.json').exists()


def test_reporter_pin_and_hard_gate_are_unchanged():
    reporter = step('Report PR-introduced OSV findings')
    assert reporter['uses'] == 'google/osv-scanner-action/osv-reporter-action@8e5cf47b818121e8b405931c82126c2630b0b20d'
    assert '--fail-on-vuln=true' in reporter['with']['scan-args']
    assert 'continue-on-error' not in reporter
    assert len([s for s in STEPS if 'osv-scanner-action/osv-scanner-action@' in s.get('uses', '')]) == 0


# CID authority controls use parsed production source, mocking Docker only.
def docker_calls(env):
    path = Path(env['FAKE_CALLS'])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def seed_foreign(env):
    control = Path(env['OSV_CONTROL'])
    state = Path(env['FAKE_STATE'])
    foreign = {'Id': 'f' * 64, 'Name': '/osv-'+env['OSV_NONCE']+'-base-first', 'State': {'Running': True, 'ExitCode': 0}, 'sentinel': 'foreign-preserve'}
    state.write_text(json.dumps(foreign))
    return state, state.read_bytes()


@pytest.mark.parametrize('fault', ['collision', 'failed-before-cid', 'popen-failure', 'interrupt-before-cid'])
def test_missing_creation_cid_never_adopts_foreign_container(lifecycle, fault):
    env, cwd, sentinel = lifecycle
    env['PRESERVE_EVIDENCE'] = '1'
    env['FAKE_MODE'] = fault
    state, saved = seed_foreign(env)
    if fault != 'collision':
        # Race: inventory reports absent; foreign resource appears before failure.
        fake = Path(env['PATH'].split(os.pathsep)[0]) / 'docker'
        text = fake.read_text().replace("if state.exists():\n        data = json.loads(state.read_text())", "if state.exists() and not os.environ.get('FAKE_HIDE_INVENTORY'):\n        data = json.loads(state.read_text())")
        fake.write_text(text)
        env['FAKE_HIDE_INVENTORY'] = '1'
    if fault == 'popen-failure':
        code = "import subprocess,runpy,sys; original=subprocess.Popen; subprocess.Popen=lambda a,*v,**k: (_ for _ in ()).throw(OSError('synthetic Popen failure')) if a[:2]==['docker','run'] else original(a,*v,**k); sys.argv=[sys.argv[1],'scan','base-first','old-results.json']; runpy.run_path(sys.argv[0],run_name='__main__')"
        result = subprocess.run([env['PYTHON'], '-c', code, str(Path(env['OSV_CONTROL']) / 'validate.py')], env=env, cwd=cwd, text=True, capture_output=True, timeout=10)
    else:
        result = execute('Scan base with OSV', env, cwd)
    assert result.returncode != 0
    cleanup = execute('Cleanup observable OSV lifecycle', env, cwd)
    calls = docker_calls(env)
    destructive = [call for call in calls if call[0] in ('stop', 'rm')]
    assert destructive == [], 'foreign CID deletion authorized: '+repr(destructive)
    assert state.read_bytes() == saved
    assert cleanup.returncode != 0
    assert Path(env['OSV_ROOT']).exists()
    assert sentinel.read_text() == 'preserve'
    if fault in ('failed-before-cid', 'interrupt-before-cid'):
        assert any(call[0] == 'run' for call in calls), 'failure did not reach Docker run'
    if fault == 'popen-failure':
        assert 'synthetic Popen failure' in result.stderr
    if fault == 'collision':
        assert not any(call[0] == 'run' for call in calls)


@pytest.mark.parametrize('bad', ['wrong-cid', 'foreign-cid', 'symlink', 'empty', 'name-mismatch'])
def test_untrusted_cid_witness_preserves_foreign_sentinel(lifecycle, bad):
    env, cwd, sentinel = lifecycle
    env['PRESERVE_EVIDENCE'] = '1'
    control = Path(env['OSV_CONTROL'])
    # Establish a real owned creation, then change only the retained witness.
    assert execute('Scan base with OSV', env, cwd).returncode == 0
    owned_path = control / 'base-first-owned.json'
    owned = json.loads(owned_path.read_text())
    owned.update(cid='', settled=False)
    owned_path.write_text(json.dumps(owned))
    state, saved = seed_foreign(env)
    if bad == 'name-mismatch':
        state.write_text(json.dumps({'Id': 'c' * 64, 'Name': '/foreign-'+env['OSV_NONCE'], 'State': {'Running': True, 'ExitCode': 0}, 'sentinel': 'wrong-name-preserve'}))
        saved = state.read_bytes()
    slot = control / 'base-first.cid-slot'
    cidfile = slot / 'container.cid' if slot.exists() else control / 'base-first.cid'
    if cidfile.exists():
        cidfile.unlink()
    if bad == 'symlink':
        cidfile.symlink_to(sentinel)
    else:
        cidfile.write_text({'wrong-cid': 'not-a-cid', 'foreign-cid': 'd'*64, 'empty': '', 'name-mismatch': 'c'*64}[bad])
    before = len(docker_calls(env))
    cleanup = execute('Cleanup observable OSV lifecycle', env, cwd)
    destructive = [call for call in docker_calls(env)[before:] if call[0] in ('stop', 'rm')]
    assert destructive == []
    assert cleanup.returncode != 0
    assert state.read_bytes() == saved and sentinel.read_text() == 'preserve'
    assert Path(env['OSV_ROOT']).exists()


def test_inventory_failure_forbids_creation(lifecycle):
    env, cwd, _ = lifecycle
    env.update(FAKE_INVENTORY_FAIL='1', PRESERVE_EVIDENCE='1')
    assert execute('Scan base with OSV', env, cwd).returncode != 0
    assert not any(call[0] in ('run', 'stop', 'rm') for call in docker_calls(env))
    assert execute('Cleanup observable OSV lifecycle', env, cwd).returncode != 0
    assert Path(env['OSV_ROOT']).exists()
