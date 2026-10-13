"""New issuer producer composition; all authority here is synthetic fixture data."""
import json
import re
from pathlib import Path

from scripts.ci import premerge_review_tooling as caller

ROOT = Path(__file__).resolve().parents[1]


def test_actual_prepare_request_is_consumable_without_permission_relabeling():
    """Execute the controller with the response to the real workflow request."""
    workflow = (ROOT / '.github/workflows/noema-review.yml').read_text()
    step = workflow.split('      - name: Mint repository-scoped Noema GitHub App token\n', 1)[1]
    step = step.split('      - name:', 1)[0]
    permissions = {name.replace('-', '_'): value for name, value in
                   re.findall(r'          permission-([a-z-]+): (read|write)', step)}
    # A recording App API returns its actual requested grant; the controller
    # receives those original bytes, not labels synthesized from action outputs.
    raw_response = json.dumps({'token': 'SYNTHETIC_PREPARE_ONLY',
                               'permissions': permissions,
                               'repositories': [{'full_name': 'ContextualWisdomLab/example'}]}).encode()
    scope = {'repository': 'ContextualWisdomLab/example', 'reviewer': 'cwl-noema-review[bot]'}
    observed = None
    try:
        observed = caller.phase_environment_from_issuance(
            'prepare', json.loads(raw_response), scope=scope,
            reviewer_actor=scope['reviewer'], installation_id=7,
            inference_key='SYNTHETIC_INFERENCE_ONLY')
    except ValueError:
        pass
    assert observed is not None, 'actual prepare request grants broader authority than controller permits'
    assert observed['GH_TOKEN'] == 'SYNTHETIC_PREPARE_ONLY'
    assert observed['NOEMA_LLM_MODEL'] == 'auto'


def test_original_authenticated_response_reaches_controller(tmp_path):
    """Missing producer cannot be replaced by action-output permission metadata."""
    import importlib.util
    helper = ROOT / 'scripts/ci/noema_bootstrap_producer.py'
    scope = {'repository': 'ContextualWisdomLab/example', 'reviewer': 'cwl-noema-review[bot]'}
    raw = b'{"token":"SYNTHETIC_ORIGINAL","permissions":{"contents":"read","metadata":"read","pull_requests":"read"},"repositories":[{"full_name":"ContextualWisdomLab/example"}]}'
    calls = []

    def request(method, route, payload):
        """Return authenticated API fixture bytes without rewriting the grant."""
        calls.append((method, route, payload))
        if route == '/app':
            return b'{"id":11,"slug":"cwl-noema-review"}'
        if route.endswith('/installation'):
            return b'{"id":7,"app_id":11}'
        return raw

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    output = private / 'prepare.json'
    if helper.exists():
        spec = importlib.util.spec_from_file_location('issuer_fixture_producer', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.produce_issuance('prepare', scope=scope, installation_id=7,
            app_id=11, output=output, private_parent=private,
            request=request, revalidate=lambda: None)
    assert output.exists() and len(calls) == 3, 'authenticated issuer response producer is missing'
    assert output.read_bytes() == raw
    observed = caller.phase_environment_from_issuance(
        'prepare', json.loads(output.read_bytes()), scope=scope,
        reviewer_actor=scope['reviewer'], installation_id=7,
        inference_key='SYNTHETIC_INFERENCE_ONLY')
    assert observed['GH_TOKEN'] == 'SYNTHETIC_ORIGINAL'


def test_missing_bootstrap_materialization_cannot_run_original_phase_child(tmp_path):
    """Execute a newly supplied child only after complete external pin admission."""
    import hashlib
    import importlib.util
    import sys
    helper = ROOT / 'scripts/ci/noema_bootstrap_producer.py'
    spec = importlib.util.spec_from_file_location('bootstrap_fixture_producer', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'supplier'
    entry = source / '.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('print("INERT_ACCEPTED_CHILD")\n')
    files = {entry.relative_to(source).as_posix(): hashlib.sha256(entry.read_bytes()).hexdigest()}
    manifest = {'schema_version': 1, 'repository': 'ContextualWisdomLab/.github',
                'commit': 'c' * 40, 'tree': 'd' * 40,
                'entrypoint': entry.relative_to(source).as_posix(), 'files': files}
    raw = json.dumps(manifest).encode()
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    target = private / 'tooling'
    admission = {'namespace': str(private),
                 'interpreter': {'path': str(Path(sys.executable).resolve()),
                                 'sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()},
                 'dependencies': {},
                 **{key: True for key in ('isolated_clean_job', 'native_custody',
                    'supplier_cost', 'supplier_retention', 'issuer_phase_separation')}}
    if hasattr(module, 'materialize_tooling'):
        module.materialize_tooling(source, target, raw,
            accepted_digest=hashlib.sha256(raw).hexdigest(),
            admission=admission, private_parent=private)
    assert (target / entry.relative_to(source)).exists(), 'immutable bootstrap producer is missing'
    import subprocess
    result = subprocess.run([sys.executable, '-I', '-B', str(target / entry.relative_to(source))],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout == 'INERT_ACCEPTED_CHILD\n'


def test_issuer_write_grant_rejected_before_private_delivery(tmp_path):
    """Original broad response cannot be relabeled as preparation read authority."""
    import pytest
    from scripts.ci.noema_bootstrap_producer import produce_issuance
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    calls = []
    def request(method, route, payload):
        """Return otherwise valid fixture identities and a contrary original grant."""
        calls.append(route)
        if route == '/app':
            return b'{"id":11,"slug":"cwl-noema-review"}'
        if route.endswith('/installation'):
            return b'{"id":7,"app_id":11}'
        return b'{"token":"SYNTHETIC_ONLY","permissions":{"contents":"read","metadata":"read","pull_requests":"write"},"repositories":[{"full_name":"ContextualWisdomLab/example"}]}'
    output = private / 'prepare.json'
    with pytest.raises(ValueError, match='phase grant'):
        produce_issuance('prepare', scope={'repository':'ContextualWisdomLab/example',
            'reviewer':'cwl-noema-review[bot]'}, installation_id=7, app_id=11,
            output=output, private_parent=private, request=request, revalidate=lambda: None)
    assert not output.exists() and len(calls) == 3


def test_revocation_during_issuer_identity_wait_prevents_token_request(tmp_path):
    """The post-wait fence denies token POST rather than only later output."""
    import pytest
    from scripts.ci.noema_bootstrap_producer import produce_issuance
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    calls = []
    def request(method, route, payload):
        """Record the only reached synthetic identity read."""
        calls.append(route)
        return b'{"id":11,"slug":"cwl-noema-review"}'
    def revalidate():
        """Revoke once the identity read has returned."""
        if calls:
            raise ValueError('FIXTURE_REVOKED')
    with pytest.raises(ValueError, match='FIXTURE_REVOKED'):
        produce_issuance('prepare', scope={'repository':'ContextualWisdomLab/example',
            'reviewer':'cwl-noema-review[bot]'}, installation_id=7, app_id=11,
            output=private/'prepare.json', private_parent=private,
            request=request, revalidate=revalidate)
    assert calls == ['/app'] and not (private/'prepare.json').exists()


def composition_fixture(tmp_path, mutation=None):
    """Native inert children consume real producer files with separated grants."""
    import importlib.util
    import hashlib
    import sys
    from scripts.ci import noema_bootstrap_producer as producer
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    source = tmp_path/'supplier'
    entry = source/'.github/actions/noema-review/two_phase.py'
    entry.parent.mkdir(parents=True)
    envelope = {'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
                'expected_head':scope['head'],'expected_base':scope['base'],
                'reviewer_actor':scope['reviewer'],'pull_request_author':'writer',
                'verdict':{'decision':'approve'}}
    entry.write_text('import os,sys,json\nfrom pathlib import Path\n'
        'a=sys.argv\n'
        'if "--prepare-verdict-file" in a:\n'
        ' assert os.environ["GH_TOKEN"]=="SYNTHETIC_READ"\n'
        ' assert os.environ["NOEMA_LLM_MODEL"]=="auto"\n'
        ' p=Path(a[a.index("--prepare-verdict-file")+1]);p.write_text('+repr(json.dumps(envelope))+');p.chmod(0o600)\n'
        'else:\n'
        ' assert os.environ["GH_TOKEN"]=="SYNTHETIC_WRITE"\n'
        ' assert "NOEMA_LLM_API_KEY" not in os.environ\n'
        ' p=Path(a[a.index("--publish-verdict-file")+1]);Path(str(p)+".marker").write_text("PUBLISHED_FIXTURE");p.unlink()\n')
    manifest = {'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'c'*40,
                'tree':'d'*40,'entrypoint':entry.relative_to(source).as_posix(),
                'files':{entry.relative_to(source).as_posix():hashlib.sha256(entry.read_bytes()).hexdigest()}}
    raw=json.dumps(manifest).encode()
    private=tmp_path/'private';private.mkdir(mode=0o700)
    interpreter=Path(sys.executable).resolve()
    admission={'namespace':str(private),'scope':scope,'installation_id':7,'app_id':11,
               'interpreter':{'path':str(interpreter),'sha256':hashlib.sha256(interpreter.read_bytes()).hexdigest()},
               'dependencies':{},**{k:True for k in ('isolated_clean_job','native_custody',
                    'supplier_cost','supplier_retention','issuer_phase_separation')}}
    events=[]
    def live():
        """Return exact synthetic live scope, never a real GitHub response."""
        return {**scope,'state':'OPEN','draft':False}
    def request(method,route,payload):
        """Assert original requested grant at the actual issuer call."""
        if route=='/app':return b'{"id":11,"slug":"cwl-noema-review"}'
        if route.endswith('/installation'):return b'{"id":7,"app_id":11}'
        mode=payload['permissions']['pull_requests'];events.append(mode)
        if mode=='write':assert (private/'prepare.json').exists()
        return json.dumps({'token':'SYNTHETIC_READ' if mode=='read' else 'SYNTHETIC_WRITE',
            'permissions':payload['permissions'],'repositories':[{'full_name':scope['repository']}]}).encode()
    if mutation == 'prepare_failure':
        entry.write_text('raise SystemExit(23)\n')
        manifest['files'][entry.relative_to(source).as_posix()] = hashlib.sha256(entry.read_bytes()).hexdigest()
        raw = json.dumps(manifest).encode()
    if mutation == 'missing_cost':
        admission['supplier_cost'] = False
    def execute():
        """Execute unchanged real composition with this case's synthetic inputs."""
        return producer.run_bootstrap_review(source,raw,accepted_digest=hashlib.sha256(raw).hexdigest(),
            admission=admission,private_parent=private,fetch_live=live,request=request,
            revalidate=lambda:None,inference_key='SYNTHETIC_INFERENCE')
    return execute, events, private


def test_actual_producer_controller_composition_issues_publish_only_after_prepare(tmp_path):
    """Retain original composition oracle without replaying its completed GREEN."""
    execute, events, _ = composition_fixture(tmp_path)
    assert execute() == 0 and events == ['read', 'write']


def test_new_prepare_failure_never_requests_publisher(tmp_path):
    """A real failed child blocks independent publication issuance."""
    import pytest
    execute, events, private = composition_fixture(tmp_path, 'prepare_failure')
    with pytest.raises(ValueError, match='preparation failed'):
        execute()
    assert events == ['read'] and not (private/'publish.json').exists()


def test_new_missing_runtime_cost_refuses_before_issuer(tmp_path):
    """Missing actual acceptance stays false rather than derived from manifest."""
    import pytest
    execute, events, private = composition_fixture(tmp_path, 'missing_cost')
    with pytest.raises(ValueError, match='execution evidence'):
        execute()
    assert events == [] and not (private/'prepare.json').exists()


def test_producer_cli_missing_independent_inputs_denies_before_issuer(tmp_path):
    """Actual CLI must refuse missing pins instead of successful no-op execution."""
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-B', '-m',
        'scripts.ci.noema_bootstrap_producer', '--materialize',
        '--private-parent', str(tmp_path/'private'), '--source-root', str(tmp_path/'absent'),
        '--manifest', str(tmp_path/'missing'), '--accepted-digest', '',
        '--admission', str(tmp_path/'missing-admission'), '--admission-digest', '',
        '--repo', 'ContextualWisdomLab/example', '--pr-number', '7',
        '--expected-head', 'a'*40], env={'PATH':'/usr/bin:/bin'},
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0, 'missing producer CLI accepts unavailable inputs as no-op'
    assert 'Traceback' not in result.stderr, 'producer refusal leaks an uncaught adapter exception'
    assert not (tmp_path/'private').exists()


def test_pinned_authenticated_transport_dispatches_original_phase_request(tmp_path):
    """Actual fixed-origin adapter must preserve response bytes, not metadata."""
    import pytest
    from scripts.ci import noema_bootstrap_producer as producer
    private = tmp_path/'private';private.mkdir(mode=0o700)
    jwt = private/'jwt';jwt.write_bytes(b'SYNTHETIC_JWT_ONLY');jwt.chmod(0o600)
    calls=[]
    class Response:
        """Minimal trusted transport fixture, never a live HTTP response."""
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,size):return b'{"original":"FIXTURE"}'
    def opener(request,timeout):
        """Inspect actual serialized fixed-origin request."""
        calls.append(request)
        return Response()
    transport = None
    if hasattr(producer,'authenticated_transport'):
        transport=producer.authenticated_transport(jwt, private, opener=opener)
    assert transport is not None, 'actual issuer transport connection is missing'
    raw=transport('POST','/app/installations/7/access_tokens',
                  {'permissions':{'pull_requests':'read'},'repositories':['example']})
    assert raw==b'{"original":"FIXTURE"}'
    assert calls[0].full_url=='https://api.github.com/app/installations/7/access_tokens'
    assert json.loads(calls[0].data)['permissions']=={'pull_requests':'read'}


def test_normal_workflow_does_not_require_unprovided_bootstrap_inputs():
    """The independent issuer remains dormant until its supplier exists."""
    workflow=(ROOT/'.github/workflows/noema-review.yml').read_text()
    assert 'scripts/ci/noema_bootstrap_producer.py' not in workflow
    assert 'node "$GITHUB_WORKSPACE/scripts/ci/noema_existing_app_issuer.cjs"' not in workflow
    assert workflow.count('.github/actions/noema-review/two_phase.py"') == 2


def test_actual_publish_request_has_only_scoped_app_write_permissions():
    """Publication gets only fresh repository-scoped review authority."""
    workflow=(ROOT/'.github/workflows/noema-review.yml').read_text()
    step=workflow.split('      - name: Refresh repository-scoped Noema GitHub App token for publication\n',1)[1]
    step=step.split('      - name:',1)[0]
    permissions={name.replace('-','_'):value for name,value in
        re.findall(r'          permission-([a-z-]+): (read|write)',step)}
    assert permissions=={'contents':'read','metadata':'read','pull_requests':'write'}
    assert 'repositories: ${{ steps.noema_credential.outputs.repository }}' in step
