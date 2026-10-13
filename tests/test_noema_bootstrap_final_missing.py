"""New exact remaining branch controls; trusted fault seams are explicit."""
import hashlib
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts.ci import noema_bootstrap_producer as producer
from scripts.ci import premerge_review_tooling as tooling
from tests.test_noema_issuer_producer_controls import bootstrap_case
from tests.test_noema_bootstrap_missing_quality import cli_inputs


def test_source_root_symlink_refuses_before_copy(tmp_path):
    """Reach materializer alias denial with valid independent fixture pins."""
    parent,source,entry,raw,admission=bootstrap_case(tmp_path)
    alias=tmp_path/'alias';alias.symlink_to(source)
    with pytest.raises(ValueError,match='namespace'):
        producer.materialize_tooling(alias,parent/'tooling',raw,accepted_digest=hashlib.sha256(raw).hexdigest(),admission=admission,private_parent=parent)


def test_source_changes_after_verified_load_refuse_copy(tmp_path,monkeypatch):
    """Change actual source bytes in the trusted loader wait before delivery."""
    parent,source,entry,raw,admission=bootstrap_case(tmp_path)
    original=tooling.load_noema_tooling
    def load(*args,**kwargs):
        """Return the real admitted loader, then mutate the fixture supplier."""
        result=original(*args,**kwargs);entry.write_bytes(b'CHANGED');return result
    monkeypatch.setattr(tooling,'load_noema_tooling',load)
    with pytest.raises(ValueError,match='changed during delivery'):
        producer.materialize_tooling(source,parent/'tooling',raw,accepted_digest=hashlib.sha256(raw).hexdigest(),admission=admission,private_parent=parent)


def test_missing_inference_authority_refuses_composition(tmp_path):
    """Actual missing-key branch refuses before any issuer or child callback."""
    parent,source,entry,raw,admission=bootstrap_case(tmp_path);admission['scope']={}
    with pytest.raises(ValueError,match='inference authority'):
        producer.run_bootstrap_review(source,raw,accepted_digest=hashlib.sha256(raw).hexdigest(),admission=admission,private_parent=parent,fetch_live=lambda:None,request=lambda *a:None,revalidate=lambda:None,inference_key=None)


def test_digest_provider_fault_is_denied_before_issuer(tmp_path,monkeypatch):
    """Explicit trusted digest fault tests the otherwise redundant immutable pin guard."""
    parent,source,entry,raw,admission=bootstrap_case(tmp_path);admission['scope']={}
    def revalidate():
        """Inject only digest-provider failure after real initial source admission."""
        monkeypatch.setattr(hashlib,'sha256',lambda *a:SimpleNamespace(hexdigest=lambda:'0'*64))
    with pytest.raises(ValueError,match='source pin changed'):
        producer.run_bootstrap_review(source,raw,accepted_digest=hashlib.sha256(raw).hexdigest(),admission=admission,private_parent=parent,fetch_live=lambda:None,request=lambda *a:None,revalidate=revalidate,inference_key='FIXTURE_INFERENCE')


@pytest.mark.parametrize('mutation',['pre_fence_file','post_read_memory'])
def test_remaining_cli_wait_fences(tmp_path,monkeypatch,mutation):
    """Reach first file drift and defensive post-read memory revocation gates."""
    args,parent,mf,af,pr=cli_inputs(tmp_path);args+=['--app-jwt-file',str(parent/'jwt')]
    original=producer._response;held=[]
    def response(raw):
        """Parse actual bytes, then hold the returned trusted admission object."""
        value=original(raw);held.append(value)
        if mutation=='pre_fence_file':mf.write_bytes(b'{}')
        return value
    def live(*a,**kw):
        """Return otherwise valid live scope; revoke only in-memory admission."""
        if mutation=='post_read_memory':held[0]['native_custody']=False
        return SimpleNamespace(stdout=json.dumps(pr))
    monkeypatch.setattr(producer,'_response',response);monkeypatch.setattr(producer.subprocess,'run',live)
    assert producer.main(args)==1


def test_actual_isolated_entry_missing_pins_refuses_without_network(tmp_path,monkeypatch):
    """Exercise root bootstrap and __main__ in-process for coverage transport."""
    helper=Path(producer.__file__);root=str(helper.resolve().parents[2])
    monkeypatch.setattr(sys,'path',[x for x in sys.path if x!=root])
    args=['--materialize','--private-parent',str(tmp_path),'--source-root',str(tmp_path/'source'),'--manifest',str(tmp_path/'absent'),'--accepted-digest','','--admission',str(tmp_path/'absent2'),'--admission-digest','','--repo','ContextualWisdomLab/example','--pr-number','7','--expected-head','a'*40]
    monkeypatch.setattr(sys,'argv',[str(helper),*args])
    with pytest.raises(SystemExit) as error:runpy.run_path(str(helper),run_name='__main__')
    assert error.value.code==1
