"""Inert native gh fixture emitting synthetic API bytes offline."""

def main():
    """Answer one finite native process acquisition or fail on selected stage."""
    import base64
    import json
    import os
    import pathlib
    import sys
    fixture=json.loads(pathlib.Path(os.environ['FIXTURE_INPUT']).read_text())
    state_file=pathlib.Path(os.environ['FIXTURE_STATE'])
    state=json.loads(state_file.read_text())
    marker=fixture['marker'];case=fixture['case'];args=sys.argv[1:]
    if args[:2]==['api','graphql']:
        stage='pr';query=sys.stdin.read();state['context_skipped']='reviewThreads' not in query
    elif args[:1]==['api'] and '/files' in args[1]:stage='files'
    elif args[:1]==['api'] and '/contents/' in args[1]:
        state['content_reads']+=1
        stage='content' if state['context_skipped'] else 'context' if state['content_reads']==1 else 'content'
    elif args[:1]==['api'] and 'Accept: application/vnd.github.v3.diff' in args:stage='diff'
    else:raise SystemExit(2)
    state['external_calls'].append(stage);state_file.write_text(json.dumps(state))
    if case==stage+':nonzero':
        print(marker,file=sys.stderr)
        raise SystemExit(1)
    path='.github/workflows/docker-ephemeral-canary.yml';head='bf85ddde01f871f0e713db54aae5a16883777d9f'
    pr={'number':4,'state':'OPEN','isDraft':False,'headRefOid':head,'baseRefOid':'b'*40,'title':marker,'body':marker,
        'author':{'login':'synthetic-author'},'reviews':{'nodes':[]},'reviewThreads':{'nodes':[{'path':marker,'comments':{'nodes':[{'body':marker,'author':{'login':'synthetic'}}]}}]}}
    if stage=='pr':value=json.dumps({'data':{'repository':{'pullRequest':pr}}})
    elif stage=='files':value=json.dumps([path,'added'])
    elif stage=='diff':value='diff --git a/'+path+' b/'+path+'\n--- /dev/null\n+++ b/'+path+'\n@@ -0,0 +1,1 @@\n+'+marker+'\n'
    else:
        data=b'name: synthetic\non: workflow_dispatch\n'
        value=json.dumps({'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()})
    print(value)


if __name__=='__main__':
    main()
