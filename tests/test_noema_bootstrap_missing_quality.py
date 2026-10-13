"""New missing bootstrap boundary controls from retained exact55d7 coverage."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ci import noema_bootstrap_producer as producer
from tests.test_noema_issuer_producer_controls import bootstrap_case, issuer_case


@pytest.mark.parametrize('raw', [b'', b'\xff', b'{', b'[]'])
def test_missing_response_shape_controls(raw):
    """Reject absent, invalid UTF8, malformed and nonobject original responses."""
    with pytest.raises(ValueError):
        producer._response(raw)


@pytest.mark.parametrize('mutation', ['phase', 'identity', 'repository', 'actor', 'symlink_parent', 'parent_mode', 'custody_drift', 'fsync_error'])
def test_missing_issuer_refusals_preserve_output_boundary(tmp_path, monkeypatch, mutation):
    """Reach distinct missing producer denials using only fixture authority."""
    parent,scope,app,installation,response,calls,request=issuer_case(tmp_path)
    phase='prepare';app_id=11
    if mutation=='phase':phase='other'
    elif mutation=='identity':app_id=0
    elif mutation=='repository':scope['repository']='Other/example'
    elif mutation=='actor':scope['reviewer']='other[bot]'
    elif mutation=='symlink_parent':
        alias=tmp_path/'alias';alias.symlink_to(parent);parent=alias
    elif mutation=='parent_mode':parent.chmod(0o755)
    def fence():
        """Change private mode only after actual issuance to reach custody check."""
        if mutation=='custody_drift' and len(calls)==3:parent.chmod(0o750)
    if mutation=='fsync_error':
        def fail(fd):
            """Inject final ordinary IO failure after actual private file writing."""
            raise OSError('FIXTURE_IO')
        monkeypatch.setattr(producer.os,'fsync',fail)
    with pytest.raises((ValueError,OSError)):
        producer.produce_issuance(phase,scope=scope,installation_id=7,app_id=app_id,
            output=parent/'prepare.json',private_parent=parent,request=request,revalidate=fence)
    assert (parent/'prepare.json').exists()==(mutation=='fsync_error')


@pytest.mark.parametrize('mutation', ['relative', 'namespace', 'missing_evidence', 'dependencies'])
def test_missing_runtime_admission_controls(tmp_path, mutation):
    """Exercise otherwise admitted runtime evidence with one invalid boundary."""
    parent,source,entry,raw,admission=bootstrap_case(tmp_path)
    if mutation=='relative':parent=Path('relative')
    elif mutation=='namespace':admission['namespace']='foreign'
    elif mutation=='missing_evidence':admission['native_custody']=False
    else:admission['dependencies']=None
    with pytest.raises(ValueError):producer._validate_runtime(admission,parent)


@pytest.mark.parametrize('mutation', ['relative','hardlink','empty','whitespace'])
def test_missing_private_input_controls(tmp_path, mutation):
    """Private transport never reads an unowned or unusable fixture credential."""
    parent=tmp_path/'private';parent.mkdir(mode=0o700)
    jwt=parent/'jwt';jwt.write_bytes(b'FIXTURE_JWT');jwt.chmod(0o600)
    if mutation=='relative':jwt=Path('relative')
    elif mutation=='hardlink':os.link(jwt,parent/'alias')
    elif mutation=='empty':jwt.write_bytes(b'')
    else:jwt.write_bytes(b'FIXTURE WHITESPACE')
    with pytest.raises((ValueError,OSError)):producer.authenticated_transport(jwt,parent,opener=lambda *a,**kw:None)


@pytest.mark.parametrize('mutation',['endpoint','payload','framing','redirect'])
def test_missing_transport_controls(tmp_path, mutation):
    """Inspect fixed transport denials with no network or provider activity."""
    import urllib.request
    parent=tmp_path/'private';parent.mkdir(mode=0o700)
    jwt=parent/'jwt';jwt.write_bytes(b'FIXTURE_JWT');jwt.chmod(0o600)
    class Response:
        """Return a syntactically valid body with contrary declared length."""
        headers={'Content-Length':'100'}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,size):return b'{}'
    transport=producer.authenticated_transport(jwt,parent,opener=lambda *a,**kw:Response())
    if mutation=='redirect':
        # Recover the actual generated handler class without making any request.
        with pytest.MonkeyPatch.context() as mp:
            held=[]
            def build(*handlers):
                """Retain actual default handlers at the trusted construction seam."""
                held.extend(handlers);return SimpleNamespace(open=lambda *a:None)
            mp.setattr(urllib.request,'build_opener',build)
            producer.authenticated_transport(jwt,parent)
            assert held[1].redirect_request(None,None,302,'',{},'https://foreign.invalid') is None
    else:
        with pytest.raises(ValueError):transport('GET','/foreign' if mutation=='endpoint' else '/app',{} if mutation=='payload' else None)


def cli_inputs(tmp_path):
    """Build independent fixture pins for only newly missing CLI conditions."""
    import hashlib
    parent,source,entry,raw,admission=bootstrap_case(tmp_path)
    scope={'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    admission.update(scope=scope,app_id=11,installation_id=7)
    producer.materialize_tooling(source,parent/'tooling',raw,accepted_digest=hashlib.sha256(raw).hexdigest(),admission=admission,private_parent=parent)
    mf,af=tmp_path/'manifest',tmp_path/'admission';mf.write_bytes(raw);af.write_text(json.dumps(admission))
    args=['--issue-prepare','--private-parent',str(parent),'--source-root',str(source),'--manifest',str(mf),'--accepted-digest',hashlib.sha256(raw).hexdigest(),'--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),'--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head']]
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},'head':{'sha':scope['head']},'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    return args,parent,mf,af,pr


@pytest.mark.parametrize('mutation',['pin','admission_digest','target','no_jwt','verdict_namespace','pre_live_drift'])
def test_missing_cli_refusals(tmp_path,monkeypatch,mutation):
    """CLI rejects new malformed pins/scope/custody before transport acquisition."""
    args,parent,mf,af,pr=cli_inputs(tmp_path)
    if mutation=='pin':args[args.index('--accepted-digest')+1]=''
    elif mutation=='admission_digest':args[args.index('--admission-digest')+1]='0'*64
    elif mutation=='target':args[args.index('--repo')+1]='ContextualWisdomLab/other'
    elif mutation=='verdict_namespace':args[0]='--revalidate-publish';args+=['--verdict-file',str(parent/'foreign')]
    elif mutation=='pre_live_drift':
        args+=['--app-jwt-file',str(parent/'jwt')]
        def pre_read(admission,path):
            """Alter the pinned file after initial parsing, before the next fence."""
            mf.write_bytes(b'{}')
        monkeypatch.setattr(producer,'_validate_runtime',pre_read)
    monkeypatch.setattr(producer.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=json.dumps(pr)))
    assert producer.main(args)==1
