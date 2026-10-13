"""In-process production caller controls with synthetic authority only."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ci import premerge_review_tooling as caller


def setup_caller(tmp_path, monkeypatch, mode):
    """Build private inert pins and intercept metadata without authenticating."""
    root = tmp_path / 'tooling'
    entry = root / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'# inert fixture\n')
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    manifest = {'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'c'*40,
                'tree':'d'*40,'entrypoint':'.github/actions/noema-review/two_phase.py',
                'files':{'.github/actions/noema-review/two_phase.py':hashlib.sha256(entry.read_bytes()).hexdigest()}}
    admission = {'scope':scope,'installation_id':7,**{k:True for k in
                 ('isolated_clean_job','native_custody','supplier_cost','supplier_retention','issuer_phase_separation')}}
    paths = {k:tmp_path/k for k in ['manifest','admission','prepare','publish','verdict']}
    for name, value in [('manifest',manifest),('admission',admission)]:
        paths[name].write_text(json.dumps(value))
    for phase in ['prepare','publish']:
        paths[phase].write_text(json.dumps({'token':'SYNTHETIC_ONLY',
            'permissions':{'contents':'read','metadata':'read','pull_requests':'read' if phase=='prepare' else 'write'},
            'repositories':[{'full_name':scope['repository']}]}))
        paths[phase].chmod(0o600)
    payload = {'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
               'expected_head':scope['head'],'expected_base':scope['base'],
               'pull_request_author':'writer','reviewer_actor':scope['reviewer'],'verdict':{'decision':'approve'}}
    pr = {'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},
          'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    monkeypatch.setattr(caller.subprocess,'run',lambda *_a,**_k:SimpleNamespace(stdout=json.dumps(pr)))
    monkeypatch.setenv('LLM_GATEWAY_API_KEY','SYNTHETIC_INFERENCE')
    events = []

    def prepare(repo, number, head, path):
        """Write an inert bounded envelope, not a model response."""
        path.write_text(json.dumps(payload));path.chmod(0o600);events.append('prepare');return 0

    def publish(repo, number, head, path):
        """Observe phase admission at a recording-only sink."""
        events.append('publish');return 0

    monkeypatch.setattr(caller,'load_noema_tooling',lambda *_a,**_k:SimpleNamespace(prepare_verdict=prepare,publish_verdict=publish))
    args = ['--'+mode+'-production','--tooling-root',str(root),'--manifest',str(paths['manifest']),
            '--accepted-digest',hashlib.sha256(paths['manifest'].read_bytes()).hexdigest(),
            '--admission',str(paths['admission']),'--admission-digest',hashlib.sha256(paths['admission'].read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head']]
    if mode in ['prepare','publish']:
        args += ['--phase-issuance',str(paths[mode]),'--verdict-file',str(paths['verdict'])]
    if mode == 'run':
        args += ['--prepare-issuance',str(paths['prepare']),'--publish-issuance',str(paths['publish']),'--private-parent',str(tmp_path)]
    return args,paths,payload,events


@pytest.mark.parametrize('mode',['prepare','publish','run','admit'])
def test_production_mode_positive(tmp_path,monkeypatch,mode):
    """Exercise caller control flow while keeping all network/model sinks inert."""
    args,paths,payload,events=setup_caller(tmp_path,monkeypatch,mode)
    if mode=='publish':
        paths['verdict'].write_text(json.dumps(payload));paths['verdict'].chmod(0o600)
    assert caller.production_main(args)==0
    assert events == {'prepare':['prepare'],'publish':['publish'],'run':['prepare','publish'],'admit':[]}[mode]


@pytest.mark.parametrize('mutation',['pins','digest','target','native','missing_phase','custody','missing_run','run_custody','admission_drift'])
def test_production_denial_controls(tmp_path,monkeypatch,mutation):
    """Missing or changed private authority refuses before later publication."""
    mode='run' if mutation in ['missing_run','run_custody','admission_drift'] else 'prepare'
    args,paths,payload,events=setup_caller(tmp_path,monkeypatch,mode)
    if mutation=='pins':args[args.index('--accepted-digest')+1]=''
    if mutation=='digest':args[args.index('--admission-digest')+1]='0'*64
    if mutation in ['target','native']:
        data=json.loads(paths['admission'].read_text())
        if mutation=='target':data['scope']['number']=8
        else:data['native_custody']=False
        paths['admission'].write_text(json.dumps(data));args[args.index('--admission-digest')+1]=hashlib.sha256(paths['admission'].read_bytes()).hexdigest()
    if mutation in ['missing_phase','missing_run']:
        flag='--phase-issuance' if mutation=='missing_phase' else '--private-parent'
        pos=args.index(flag);del args[pos:pos+2]
    if mutation in ['custody','run_custody']:paths['prepare'].chmod(0o644)
    if mutation=='admission_drift':
        def stale(*_a,**kwargs):
            """Mutate accepted custody before the controller revalidation."""
            paths['admission'].write_text('{}')
            kwargs['require_execution_admission']()
        monkeypatch.setattr(caller,'run_review',stale)
    assert caller.production_main(args)==1
    assert events==[]


@pytest.mark.parametrize('mode',['prepare','publish'])
def test_phase_admission_drift_during_live_read_blocks_execution(tmp_path,monkeypatch,mode):
    """A live metadata wait cannot preserve authority revoked during that wait."""
    args,paths,payload,events=setup_caller(tmp_path,monkeypatch,mode)
    if mode=='publish':
        paths['verdict'].write_text(json.dumps(payload));paths['verdict'].chmod(0o600)
    original=caller.subprocess.run

    def revoke(*args,**kwargs):
        """Return real fixture metadata but replace the previously accepted receipt."""
        response=original(*args,**kwargs)
        paths['admission'].write_text('{}')
        return response

    monkeypatch.setattr(caller.subprocess,'run',revoke)
    assert caller.production_main(args)==1
    assert events==[]


def test_main_entrypoint_rejects_empty_pins_without_network(monkeypatch,tmp_path):
    """Execute the real __main__ boundary in process with no external authority."""
    import runpy
    import sys

    monkeypatch.setattr(sys,'argv',[str(Path(caller.__file__)), '--admit-production',
        '--tooling-root',str(tmp_path),'--manifest',str(tmp_path/'missing'),
        '--accepted-digest','','--admission',str(tmp_path/'missing-admission'),
        '--admission-digest','','--repo','ContextualWisdomLab/example',
        '--pr-number','7','--expected-head','a'*40])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(caller.__file__,run_name='__main__')
    assert stopped.value.code == 1
