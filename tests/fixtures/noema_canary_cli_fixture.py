"""Finite offline CLI fixture; importing it performs no IO."""


def main():
    """Run one private synthetic CLI scenario."""
    """Execute unchanged Noema public CLI bodies with finite external IO."""
    import base64, hashlib, importlib.util, json, os, pathlib, runpy, socket, subprocess, sys, urllib.error, urllib.request
    root=pathlib.Path(os.environ['FIXTURE_SOURCE'])
    fixture=json.loads(pathlib.Path(os.environ['FIXTURE_INPUT']).read_text())
    state_path=pathlib.Path(os.environ['FIXTURE_STATE'])
    cli_argv=sys.argv[1:]
    sys.path.insert(0,str(root))
    from scripts.ci import noema_review_gate as gate, noema_exact_canary as policy
    marker=fixture['marker']; case=fixture['case']; entry=fixture['entry']
    content='name: synthetic\non: workflow_dispatch\n'
    policy.DIGEST=hashlib.sha256(content.encode()).hexdigest()
    pr={'number':4,'state':'OPEN','isDraft':False,'headRefOid':policy.HEAD,'baseRefOid':'b'*40,
        'title':marker,'body':marker,'author':{'login':'synthetic-author'},
        'reviews':{'nodes':[]},'reviewThreads':{'nodes':[{'path':marker,'line':1,'comments':{'nodes':[{'body':marker,'author':{'login':'synthetic'}}]}}]}}
    state={'external_calls':[],'http_requests':[],'publications':0,'content_reads':0,'pr_reads':0,'fixture_digest_substitution':True,'stage_faults':[]}
    REAL_OPEN=os.open; REAL_FSYNC=os.fsync; REAL_UNLINK=pathlib.Path.unlink
    def faulted_open(path,*args,**kwargs):
        if str(path).endswith('.envelope') and boundary=='envelope':
            state['stage_faults'].append('envelope');save();fail(kind)
        return REAL_OPEN(path,*args,**kwargs)
    def faulted_fsync(fd):
        if boundary=='fsync':
            state['stage_faults'].append('fsync');save();fail(kind)
        return REAL_FSYNC(fd)
    def faulted_unlink(path,*args,**kwargs):
        if str(path).endswith('.envelope') and boundary=='cleanup':
            state['stage_faults'].append('cleanup');save();fail(kind)
        return REAL_UNLINK(path,*args,**kwargs)
    os.open=faulted_open;os.fsync=faulted_fsync;pathlib.Path.unlink=faulted_unlink
    def save(): state_path.write_text(json.dumps(state,indent=2))
    def fail(kind):
        if kind=='nonzero':return subprocess.CompletedProcess(['gh'],1,marker,marker)
        if kind=='malformed':return subprocess.CompletedProcess(['gh'],0,marker,'')
        if kind=='decode':raise UnicodeDecodeError('utf-8',marker.encode()+b'\xff',len(marker),len(marker)+1,marker)
        cls={'runtime':RuntimeError,'os':OSError,'value':ValueError,'interrupt':KeyboardInterrupt,'exit':SystemExit,'type':TypeError}[kind]
        error=cls(marker);error.add_note(marker)
        raise error
    boundary,_,kind=case.partition(':')
    def fake_run(args,**kwargs):
        if args[:3]==['gh','api','graphql']:
            state['pr_reads']+=1
            stage='readback' if boundary=='readback' and state['pr_reads']>1 else 'pr'
            state['context_skipped']='reviewThreads' not in kwargs.get('input','')
        elif args[:2]==['gh','api'] and '/files' in args[2]:stage='files'
        elif args[:2]==['gh','api'] and '/contents/' in args[2]:
            state['content_reads']+=1
            stage='context' if state['content_reads']==1 and entry!='policy' and not state.get('context_skipped',False) else 'content'
            if state.get('context_skipped',False):stage='content'
        elif args[:2]==['gh','api'] and 'Accept: application/vnd.github.v3.diff' in args:stage='diff'
        else:raise AssertionError('Unexpected external operation')
        state['external_calls'].append(stage);save()
        if boundary==stage:
            result=fail(kind)
            if result is not None:return result
        if stage in {'pr','readback'}: value=json.dumps({'data':{'repository':{'pullRequest':pr}}})
        elif stage=='files': value=json.dumps([policy.PATH,'added'])+'\n'
        elif stage=='diff': value='diff --git a/'+policy.PATH+' b/'+policy.PATH+'\n--- /dev/null\n+++ b/'+policy.PATH+'\n@@ -0,0 +1,1 @@\n+'+marker+'\n'
        else:
            data=content.encode()
            value=json.dumps({'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()})
        return subprocess.CompletedProcess(args,0,value,'')
    native=fixture.get('native',False)
    if not native:
        subprocess.run=fake_run
    socket.getaddrinfo=lambda host,*args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
    def verdict():
        decision=marker if boundary=='verdict' else 'approve'
        return {'decision':decision,'summary':'Synthetic exact-file review.','findings':[],
            'reviewed_lines':[{'path':policy.PATH,'line':1,'side':'RIGHT','analysis':'Reviewed the added workflow.'}],
            'adversarial_validation':{'status':'passed','residual_risk':'Offline fixture only.','probes':[
                {'path':policy.PATH,'line':i+1,'side':'RIGHT','hypothesis':f'Concrete regression {i}',
                 'attack_or_counterexample':f'Concrete counterexample {i}','evidence':f'Exact line {i+1}','outcome':'falsified'} for i in range(2)]}}
    class Response:
        def __enter__(self):
            if boundary=='enter':fail(kind)
            return self
        def __exit__(self,*args):
            if boundary=='close':fail(kind)
            return False
        def read(self):
            if boundary=='read':fail(kind)
            if boundary=='model_decode':return marker.encode()+b'\xff'
            model=marker if boundary=='telemetry' else 'auto'
            return json.dumps({'model':model,'choices':[{'message':{'content':json.dumps(verdict())}}]}).encode()
    class ErrorBody:
        def read(self,*args):
            if boundary=='error_read':fail(kind)
            return json.dumps({'error':{'detail':{'model':marker,'terminal_reason':marker,'attempts':[{'provider_name':marker,'phase':marker,'attempt_number':1,'provider_status':503}]}}}).encode()
        def close(self):
            if boundary=='error_close':fail(kind)
    class Opener:
        def open(self,request):
            if native:state.update(json.loads(state_path.read_text()))
            state['http_requests'].append({'url':request.full_url,'data':request.data.decode(),'method':request.method});save()
            if boundary=='http':
                if kind=='url':raise urllib.error.URLError(marker)
                if kind=='http':raise urllib.error.HTTPError(request.full_url,503,marker,{},ErrorBody())
                fail(kind)
            if boundary in {'error_read','error_close'}:raise urllib.error.HTTPError(request.full_url,503,marker,{},ErrorBody())
            return Response()
    urllib.request.build_opener=lambda *args,**kwargs:Opener()
    def no_publish(*args,**kwargs):state['publications']+=1;save();raise AssertionError('Publication forbidden')
    gate.submit_review=no_publish
    # Defense in depth: no native process/socket operation may escape adapters.
    def audit(event,args):
        if event.startswith('socket.') or event in {'os.system','os.posix_spawn'}:
            raise AssertionError('Offline IO fence')
        if event=='subprocess.Popen':
            if not native or pathlib.Path(args[0]).name!='gh':raise AssertionError('Offline process fence')
    sys.addaudithook(audit)
    save()
    args=['--repo',policy.REPOSITORY,'--pr-number','4','--expected-head',policy.HEAD]
    if entry=='prepare':
        invocation=[str(root/'.github/actions/noema-review/two_phase.py'),*args,'--prepare-verdict-file',str(state_path.with_suffix('.envelope'))]
        if cli_argv:
            assert cli_argv[0]==invocation[0]
            invocation=cli_argv
        sys.argv=invocation
        runpy.run_path(sys.argv[0],run_name='__main__')
    elif entry=='gate':
        sys.argv=[str(root/'scripts/ci/noema_review_gate.py'),*args]
        runpy.run_path(sys.argv[0],run_name='__main__')
    elif entry=='policy':
        sys.argv=[str(root/'scripts/ci/noema_exact_canary.py'),*args]
        if cli_argv:
            assert cli_argv[:2]==['-m','scripts.ci.noema_exact_canary']
            sys.argv=[sys.argv[0],*cli_argv[2:]]
        # Compile the complete actual CLI; only the explicit fixture digest literal
        # is substituted, matching the imported policy fixture used by prepare.
        text=pathlib.Path(sys.argv[0]).read_text()
        old="DIGEST = '5427ca0c17d818d49f9af91b5cd495ab4599c969b894cb2467b794d674a96d3d'"
        assert text.count(old)==1
        text=text.replace(old,'DIGEST = '+repr(policy.DIGEST))
        exec(compile(text,sys.argv[0],'exec'),{'__name__':'__main__','__file__':sys.argv[0]})
    elif entry=='publish':
        envelope=state_path.with_suffix('.envelope')
        payload={'schema_version':1,'repository':policy.REPOSITORY,'pull_request_number':4,'expected_head':policy.HEAD,
           'expected_base':'b'*40,'reviewer_actor':'cwl-noema-review[bot]','pull_request_author':'synthetic-author','verdict':verdict()}
        envelope.write_text(json.dumps(payload));envelope.chmod(0o600)
        if boundary=='parse_envelope':envelope.write_bytes(marker.encode()+b'\xff')
        if boundary=='cleanup':pr['isDraft']=True
        sys.argv=[str(root/'.github/actions/noema-review/two_phase.py'),*args,'--publish-verdict-file',str(envelope)]
        runpy.run_path(sys.argv[0],run_name='__main__')
    else:raise AssertionError('Unknown fixture entry')


if __name__ == '__main__':
    main()
