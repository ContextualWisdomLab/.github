"""Execute production CLI phase children with only inert fixture authority."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_source_drift_during_credential_acquisition_blocks_child(tmp_path):
    """Credential acquisition cannot stale the source check before child spawn."""
    import importlib.util

    spec = importlib.util.spec_from_file_location('credential_wait_boundary', ROOT / 'scripts/ci/premerge_review_tooling.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = tmp_path / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'# accepted fixture\n')
    manifest = {'schema_version':1,'repository':'ContextualWisdomLab/.github',
                'commit':'a'*40,'tree':'b'*40,
                'entrypoint':'.github/actions/noema-review/two_phase.py',
                'files':{'.github/actions/noema-review/two_phase.py':hashlib.sha256(entry.read_bytes()).hexdigest()}}
    raw = json.dumps(manifest).encode()
    calls = []

    def acquire(phase):
        entry.write_bytes(b'# changed during authority acquisition\n')
        return {'NOEMA_LLM_MODEL':'auto'}

    def child(*args, **kwargs):
        from types import SimpleNamespace
        calls.append(args)
        return SimpleNamespace(returncode=0)

    tooling = module.load_noema_tooling(tmp_path, raw,
        accepted_digest=hashlib.sha256(raw).hexdigest(), interpreter=Path(sys.executable),
        phase_environment=acquire, child_runner=child)
    with pytest.raises(ValueError, match='source inventory'):
        tooling.prepare_verdict('ContextualWisdomLab/example',7,'c'*40,tmp_path.parent/'unused-verdict')
    assert calls == []



@pytest.mark.parametrize('mutation', ['none', 'source', 'permissions', 'custody'])
def test_real_phase_children_and_fail_closed_boundaries(tmp_path, mutation):
    """Prepare then separately publish; corrupted boundary never invokes publisher."""
    root = tmp_path / 'tooling'
    entry = root / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'d'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    envelope = {'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
                'expected_head':scope['head'],'expected_base':scope['base'],
                'pull_request_author':'writer','reviewer_actor':scope['reviewer'],
                'verdict':{'decision':'approve','summary':'INERT FIXTURE ONLY'}}
    entry.write_text('import sys,json,os\nfrom pathlib import Path\n'
                     'args=sys.argv\n'
                     'if "--prepare-verdict-file" in args:\n'
                     ' assert os.environ["GH_TOKEN"] == "SYNTHETIC_READ"\n'
                     ' assert os.environ["NOEMA_LLM_MODEL"] == "auto"\n'
                     ' p=Path(args[args.index("--prepare-verdict-file")+1])\n'
                     ' p.write_text(' + repr(json.dumps(envelope)) + ')\n p.chmod(0o600)\n'
                     'else:\n'
                     ' assert os.environ["GH_TOKEN"] == "SYNTHETIC_WRITE"\n'
                     ' assert "NOEMA_LLM_API_KEY" not in os.environ\n'
                     ' p=Path(args[args.index("--publish-verdict-file")+1])\n'
                     ' Path(str(p)+".published").write_text("FIXTURE ONLY")\n p.unlink()\n')
    manifest = {'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'b'*40,
                'tree':'c'*40,'entrypoint':'.github/actions/noema-review/two_phase.py',
                'files':{'.github/actions/noema-review/two_phase.py':hashlib.sha256(entry.read_bytes()).hexdigest()}}
    admission = {'scope':scope,'installation_id':7,**{name:True for name in
                 ('isolated_clean_job','native_custody','supplier_cost','supplier_retention','issuer_phase_separation')}}
    mf=tmp_path/'manifest';ad=tmp_path/'admission';issuer=tmp_path/'issuer';verdict=tmp_path/'verdict'
    mf.write_text(json.dumps(manifest));ad.write_text(json.dumps(admission))
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},'head':{'sha':scope['head']},
        'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    gh=tmp_path/'gh';gh.write_text('#!/bin/sh\nprintf \'%s\' \''+json.dumps(pr)+'\'\n');gh.chmod(0o700)
    common=['--tooling-root',str(root),'--manifest',str(mf),'--accepted-digest',hashlib.sha256(mf.read_bytes()).hexdigest(),
            '--admission',str(ad),'--admission-digest',hashlib.sha256(ad.read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
            '--phase-issuance',str(issuer),'--verdict-file',str(verdict)]
    for phase in ('prepare','publish'):
        response={'token':'SYNTHETIC_READ' if phase=='prepare' else 'SYNTHETIC_WRITE',
                  'permissions':{'contents':'read','metadata':'read','pull_requests':'read' if phase=='prepare' else 'write'},
                  'repositories':[{'full_name':scope['repository']}]}
        if phase=='publish':
            if mutation=='source':entry.write_text('# substituted\n')
            if mutation=='permissions':response['permissions']['contents']='write'
        issuer.write_text(json.dumps(response));issuer.chmod(0o644 if phase=='publish' and mutation=='custody' else 0o600)
        env={'PATH':str(tmp_path)+':/usr/bin:/bin'}
        if phase=='prepare':env['LLM_GATEWAY_API_KEY']='SYNTHETIC_INFERENCE'
        completed=subprocess.run([sys.executable,'-I','-B',str(ROOT/'scripts/ci/premerge_review_tooling.py'),
                                  '--'+phase+'-production',*common],env=env,capture_output=True,text=True,timeout=20)
        if phase=='prepare' or mutation=='none':
            assert completed.returncode==0,completed.stderr
        else:
            assert completed.returncode==1
    assert Path(str(verdict)+'.published').exists() is (mutation=='none')
    assert 'SYNTHETIC_READ' not in completed.stdout+completed.stderr
    assert 'SYNTHETIC_WRITE' not in completed.stdout+completed.stderr
