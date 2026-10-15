"""Additional new fail-closed issuer boundaries using fixture-only authority."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.ci import noema_bootstrap_producer as producer


def issuer_case(tmp_path):
    """Return private native paths and a recording, original-byte issuer."""
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    scope = {'repository': 'ContextualWisdomLab/example', 'reviewer': 'cwl-noema-review[bot]'}
    app = {'id': 11, 'slug': 'cwl-noema-review'}
    installation = {'id': 7, 'app_id': 11}
    response = {'token': 'FIXTURE_ONLY_NEVER_LIVE',
                'permissions': {'contents': 'read', 'metadata': 'read', 'pull_requests': 'read'},
                'repositories': [{'full_name': scope['repository']}]}
    calls = []

    def request(method, route, payload):
        """Project exact fixture responses rather than inventing action metadata."""
        calls.append((method, route, payload))
        value = app if route == '/app' else installation if route.endswith('/installation') else response
        return json.dumps(value).encode()

    return private, scope, app, installation, response, calls, request


@pytest.mark.parametrize('mutation', ['wrong_app', 'wrong_actor', 'wrong_installation',
    'wrong_repository', 'metadata_only', 'output_existing', 'output_symlink',
    'output_hardlink', 'output_external', 'output_same_jwt'])
def test_new_issuer_identity_and_delivery_controls(tmp_path, mutation):
    """Each distinct malformed boundary rejects without overwriting a private file."""
    private, scope, app, installation, response, calls, request = issuer_case(tmp_path)
    output = private / 'prepare.json'
    sentinel = private / 'sentinel'
    sentinel.write_bytes(b'KEEP_ORIGINAL')
    sentinel.chmod(0o600)
    if mutation == 'wrong_app':
        app['id'] = 12
    elif mutation == 'wrong_actor':
        app['slug'] = 'other-reviewer'
    elif mutation == 'wrong_installation':
        installation['id'] = 8
    elif mutation == 'wrong_repository':
        response['repositories'][0]['full_name'] = 'ContextualWisdomLab/other'
    elif mutation == 'metadata_only':
        response.pop('token')
    elif mutation == 'output_existing':
        output.write_bytes(b'KEEP_EXISTING')
    elif mutation == 'output_symlink':
        output.symlink_to(sentinel)
    elif mutation == 'output_hardlink':
        os.link(sentinel, output)
    elif mutation == 'output_external':
        output = tmp_path / 'foreign.json'
    elif mutation == 'output_same_jwt':
        output = sentinel
    with pytest.raises(ValueError):
        producer.produce_issuance('prepare', scope=scope, installation_id=7, app_id=11,
            output=output, private_parent=private, request=request, revalidate=lambda: None)
    assert sentinel.read_bytes() == b'KEEP_ORIGINAL'
    if mutation not in ('output_existing', 'output_symlink', 'output_hardlink', 'output_same_jwt'):
        assert not output.exists()
    if mutation.startswith('output_'):
        assert calls == []


def test_new_issuer_boolean_app_identity_cannot_match_integer(tmp_path):
    """Exact integer admission must not permit Python's true-equals-one alias."""
    private, scope, app, installation, response, calls, request = issuer_case(tmp_path)
    app['id'] = True
    installation['app_id'] = 1
    with pytest.raises(ValueError, match='App identity'):
        producer.produce_issuance('prepare', scope=scope, installation_id=7, app_id=1,
            output=private/'prepare.json', private_parent=private,
            request=request, revalidate=lambda: None)
    assert [row[1] for row in calls] == ['/app']


def bootstrap_case(tmp_path):
    """Build exact stdlib-only tooling and explicit synthetic runtime pins."""
    import sys
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    source = tmp_path / 'supplier'
    entry = source / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'# INERT ORIGINAL SUPPLIER\n')
    manifest = {'schema_version': 1, 'repository': 'ContextualWisdomLab/.github',
                'commit': 'c'*40, 'tree': 'd'*40,
                'entrypoint': entry.relative_to(source).as_posix(),
                'files': {entry.relative_to(source).as_posix(): hashlib.sha256(entry.read_bytes()).hexdigest()}}
    interpreter = Path(sys.executable).resolve()
    admission = {'namespace':str(private), 'dependencies':{},
                 'interpreter':{'path':str(interpreter), 'sha256':hashlib.sha256(interpreter.read_bytes()).hexdigest()},
                 **{field:True for field in ('isolated_clean_job','native_custody','supplier_cost',
                     'supplier_retention','issuer_phase_separation')}}
    raw = json.dumps(manifest).encode()
    return private, source, entry, raw, admission


@pytest.mark.parametrize('mutation', ['stale_pin','source_drift','missing_custody',
    'wrong_interpreter','bad_dependency','foreign_namespace','same_source_target','target_symlink'])
def test_new_bootstrap_supply_and_runtime_controls(tmp_path, mutation):
    """Invalid source/namespace/runtime evidence refuses before any phase dispatch."""
    private, source, entry, raw, admission = bootstrap_case(tmp_path)
    digest = hashlib.sha256(raw).hexdigest()
    target = private/'tooling'
    if mutation == 'stale_pin': digest = '0'*64
    elif mutation == 'source_drift': entry.write_bytes(b'# MODIFIED AFTER INDEPENDENT PIN\n')
    elif mutation == 'missing_custody': admission['native_custody'] = False
    elif mutation == 'wrong_interpreter': admission['interpreter']['sha256'] = '0'*64
    elif mutation == 'bad_dependency': admission['dependencies'][str(entry)] = '0'*64
    elif mutation == 'foreign_namespace': admission['namespace'] = str(tmp_path)
    elif mutation == 'same_source_target': target = source
    elif mutation == 'target_symlink': target.symlink_to(source)
    with pytest.raises(ValueError):
        producer.materialize_tooling(source,target,raw,accepted_digest=digest,
                                     admission=admission,private_parent=private)
    assert entry.read_bytes().startswith(b'#')
    if mutation not in ('same_source_target','target_symlink'):
        assert not target.exists()


def test_dependency_revocation_during_live_wait_blocks_issuance(tmp_path, monkeypatch):
    """A changed runtime supplier cannot survive the CLI metadata wait."""
    from types import SimpleNamespace
    private, source, entry, raw, admission = bootstrap_case(tmp_path)
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    dependency = tmp_path/'dependency'
    dependency.write_bytes(b'ACCEPTED_STDLIB_FIXTURE')
    admission.update(scope=scope, installation_id=7, app_id=11)
    admission['dependencies'][str(dependency)] = hashlib.sha256(dependency.read_bytes()).hexdigest()
    producer.materialize_tooling(source, private/'tooling', raw,
        accepted_digest=hashlib.sha256(raw).hexdigest(), admission=admission, private_parent=private)
    manifest_file, admission_file = tmp_path/'manifest', tmp_path/'admission'
    manifest_file.write_bytes(raw); admission_file.write_text(json.dumps(admission))
    jwt = private/'prepare-app.jwt';jwt.write_bytes(b'FIXTURE_ONLY');jwt.chmod(0o600)
    calls=[]
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},
        'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    def metadata(*args, **kwargs):
        """Return valid fixture PR but revoke one pinned dependency during waiting."""
        dependency.write_bytes(b'REVOKED_RUNTIME_SUPPLIER')
        return SimpleNamespace(stdout=json.dumps(pr))
    def auth(*args, **kwargs):
        """Expose whether revoked authority ever reaches credential transport."""
        def request(*args):
            calls.append(args)
            return b'{}'
        return request
    monkeypatch.setattr(producer.subprocess,'run',metadata)
    monkeypatch.setattr(producer,'authenticated_transport',auth)
    argv=['--issue-prepare','--private-parent',str(private),'--source-root',str(source),
          '--manifest',str(manifest_file),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
          '--admission',str(admission_file),'--admission-digest',hashlib.sha256(admission_file.read_bytes()).hexdigest(),
          '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
          '--app-jwt-file',str(jwt)]
    assert producer.main(argv)==1
    assert calls==[], 'runtime dependency drift reached issuer after live metadata wait'


@pytest.mark.parametrize('mutation', ['manifest', 'tooling'])
def test_post_live_metadata_pin_drift_never_reaches_authenticated_issuer(tmp_path, monkeypatch, mutation):
    """Source and manifest are re-read after the actual metadata wait too."""
    from types import SimpleNamespace
    private, source, entry, raw, admission = bootstrap_case(tmp_path)
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    admission.update(scope=scope, installation_id=7, app_id=11)
    producer.materialize_tooling(source, private/'tooling', raw,
        accepted_digest=hashlib.sha256(raw).hexdigest(), admission=admission, private_parent=private)
    manifest_file, admission_file = tmp_path/'manifest', tmp_path/'admission'
    manifest_file.write_bytes(raw); admission_file.write_text(json.dumps(admission))
    jwt=private/'prepare-app.jwt';jwt.write_bytes(b'FIXTURE_ONLY');jwt.chmod(0o600)
    calls=[]
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},
        'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    def metadata(*args, **kwargs):
        """Replace a source pin after the pre-wait validation succeeded."""
        if mutation=='manifest':manifest_file.write_bytes(b'{}')
        else:(private/'tooling'/entry.relative_to(source)).write_bytes(b'# STALE CHILD\n')
        return SimpleNamespace(stdout=json.dumps(pr))
    def auth(*args, **kwargs):
        """Assert no credential read, not merely no final response file."""
        calls.append('credential')
        return lambda *args:b'{}'
    monkeypatch.setattr(producer.subprocess,'run',metadata)
    monkeypatch.setattr(producer,'authenticated_transport',auth)
    argv=['--issue-prepare','--private-parent',str(private),'--source-root',str(source),
          '--manifest',str(manifest_file),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
          '--admission',str(admission_file),'--admission-digest',hashlib.sha256(admission_file.read_bytes()).hexdigest(),
          '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
          '--app-jwt-file',str(jwt)]
    assert producer.main(argv)==1
    assert calls==[], 'post-live source drift reached credential acquisition'


def test_new_cli_producer_original_responses_feed_actual_controller_children(tmp_path, monkeypatch):
    """Exercise real CLI functions plus native children; only HTTP/metadata is inert."""
    from types import SimpleNamespace
    from scripts.ci import premerge_review_tooling as controller
    import subprocess
    import sys
    import urllib.request
    private, source, entry, _, admission = bootstrap_case(tmp_path)
    scope={'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
           'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    envelope={'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
              'expected_head':scope['head'],'expected_base':scope['base'],
              'reviewer_actor':scope['reviewer'],'pull_request_author':'writer',
              'verdict':{'decision':'approve'}}
    entry.write_text('import os,sys\nfrom pathlib import Path\n'
        'a=sys.argv\n'
        'if "--prepare-verdict-file" in a:\n'
        ' assert os.environ["GH_TOKEN"]=="NEW_FIXTURE_READ"\n'
        ' assert os.environ["NOEMA_LLM_MODEL"]=="auto"\n'
        ' p=Path(a[a.index("--prepare-verdict-file")+1]);p.write_text('+repr(json.dumps(envelope))+');p.chmod(0o600)\n'
        'else:\n'
        ' assert os.environ["GH_TOKEN"]=="NEW_FIXTURE_WRITE"\n'
        ' assert "LLM_GATEWAY_API_KEY" not in os.environ and "NOEMA_LLM_API_KEY" not in os.environ\n'
        ' p=Path(a[a.index("--publish-verdict-file")+1]);Path(str(p)+".marker").write_text("NEW_NATIVE_FIXTURE");p.unlink()\n')
    manifest={'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'c'*40,
              'tree':'d'*40,'entrypoint':entry.relative_to(source).as_posix(),
              'files':{entry.relative_to(source).as_posix():hashlib.sha256(entry.read_bytes()).hexdigest()}}
    raw=json.dumps(manifest).encode()
    admission.update(scope=scope,installation_id=7,app_id=11)
    mf,af=tmp_path/'manifest',tmp_path/'admission';mf.write_bytes(raw);af.write_text(json.dumps(admission))
    common=['--private-parent',str(private),'--source-root',str(source),
            '--manifest',str(mf),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
            '--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head']]
    events=[]
    class Response:
        """Hold raw response bytes with exact declared length and native cleanup."""
        def __init__(self,raw):
            self.raw=raw;self.headers={'Content-Length':str(len(raw))}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,size):return self.raw
    def open_fixture(req,timeout):
        """Return exact API fixture bodies to the real fixed-origin adapter."""
        if req.full_url.endswith('/app'):return Response(b'{"id":11,"slug":"cwl-noema-review"}')
        if req.full_url.endswith('/installation'):return Response(b'{"id":7,"app_id":11}')
        body=json.loads(req.data);phase=body['permissions']['pull_requests'];events.append(phase)
        assert body['repositories']==['example']
        if phase=='write':assert (private/'verdict.json').exists()
        return Response(json.dumps({'token':'NEW_FIXTURE_READ' if phase=='read' else 'NEW_FIXTURE_WRITE',
            'permissions':body['permissions'],'repositories':[{'full_name':scope['repository']}]}).encode())
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:SimpleNamespace(open=open_fixture))
    native_run=subprocess.run
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},
        'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    def metadata_or_native(argv,**kwargs):
        """Fixture only gh metadata; execute the real isolated Python child."""
        if argv[0]=='gh':return SimpleNamespace(stdout=json.dumps(pr))
        return native_run(argv,**kwargs)
    monkeypatch.setattr(subprocess,'run',metadata_or_native)
    monkeypatch.setenv('LLM_GATEWAY_API_KEY','NEW_FIXTURE_INFERENCE')
    assert producer.main(['--materialize',*common])==0
    for phase in ('prepare','publish'):
        jwt=private/(phase+'-app.jwt');jwt.write_bytes(b'NEW_FIXTURE_JWT');jwt.chmod(0o600)
        if phase=='publish':
            assert producer.main(['--revalidate-publish',*common,'--verdict-file',str(private/'verdict.json')])==0
        argv=['--issue-'+phase,*common,'--app-jwt-file',str(jwt)]
        if phase=='publish':argv+=['--verdict-file',str(private/'verdict.json')]
        assert producer.main(argv)==0
        response=json.loads((private/(phase+'.json')).read_bytes())
        assert response['permissions']['pull_requests']==('read' if phase=='prepare' else 'write')
        assert controller.production_main(['--'+phase+'-production',
            '--tooling-root',str(private/'tooling'),
            '--manifest',str(mf),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
            '--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],
            '--phase-issuance',str(private/(phase+'.json')),
            '--verdict-file',str(private/'verdict.json')])==0
    assert events==['read','write']
    assert (private/'verdict.json.marker').read_text()=='NEW_NATIVE_FIXTURE'
