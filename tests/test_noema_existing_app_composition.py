"""Source-only existing-App issuer controls; keys and HTTP are synthetic."""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/ci/noema_existing_app_issuer.cjs'


def test_normal_review_uses_existing_two_phase_and_short_lived_app_tokens():
    """Production review works without an unprovisioned issuer supplier."""
    text=(ROOT/'.github/workflows/noema-review.yml').read_text()
    prepare=text.split('      - name: Prepare Noema model verdict\n',1)[1].split('      - name:',1)[0]
    publish=text.split('      - name: Publish prepared Noema verdict on the exact live head\n',1)[1].split('\n  continue-noema-transport:',1)[0]
    assert '--prepare-verdict-file "$verdict_file"' in prepare
    assert '--publish-verdict-file "$verdict_file"' in publish
    assert 'noema_existing_app_issuer.cjs' not in prepare + publish
    assert 'premerge_review_tooling.py' not in prepare + publish
    assert text.index('      - name: Prepare Noema model verdict') < text.index('      - name: Refresh repository-scoped Noema GitHub App token for publication') < text.index('      - name: Publish prepared Noema verdict on the exact live head')


def test_existing_app_signing_original_body_controller_and_cleanup(tmp_path):
    """Real RSA signing and private delivery feed the controller, then revoke."""
    assert HELPER.exists(), 'existing Secret to original issuer response composition is missing'
    import hashlib
    import sys
    from tests.test_noema_issuer_producer_controls import bootstrap_case
    private, source, entry, _, admission = bootstrap_case(tmp_path)
    scope = {'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
             'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    entry.write_text('import os,sys\nfrom pathlib import Path\n'
        'assert os.environ["GH_TOKEN"]=="FIXTURE_WRITE"\n'
        'assert "NOEMA_GITHUB_APP_PRIVATE_KEY" not in os.environ\n'
        'assert "NOEMA_LLM_API_KEY" not in os.environ\n'
        'p=Path(sys.argv[sys.argv.index("--publish-verdict-file")+1]);p.unlink()\n')
    manifest = {'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'c'*40,
                'tree':'d'*40,'entrypoint':entry.relative_to(source).as_posix(),
                'files':{entry.relative_to(source).as_posix():hashlib.sha256(entry.read_bytes()).hexdigest()}}
    admission.update(scope=scope,installation_id=7,app_id=11)
    tooling=private/'tooling';(tooling/entry.relative_to(source)).parent.mkdir(parents=True)
    (tooling/entry.relative_to(source)).write_bytes(entry.read_bytes())
    mf,af=tmp_path/'manifest',tmp_path/'admission';mf.write_text(json.dumps(manifest));af.write_text(json.dumps(admission))
    envelope={'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
              'expected_head':scope['head'],'expected_base':scope['base'],'reviewer_actor':scope['reviewer'],
              'pull_request_author':'writer','verdict':{'decision':'approve'}}
    verdict=private/'verdict.json';verdict.write_text(json.dumps(envelope));verdict.chmod(0o600)
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},'head':{'sha':scope['head']},
        'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    gh=tmp_path/'gh';gh.write_text('#!/bin/sh\n[ "$GH_TOKEN" = FIXTURE_READ_0 ] || exit 77\n'+"printf '%s' '"+json.dumps(pr)+"'\n");gh.chmod(0o755)
    config={'python':sys.executable,'controller':str(ROOT/'scripts/ci/premerge_review_tooling.py'),
            'path':str(tmp_path)+':/usr/bin:/bin','args':['--publish-production','--tooling-root',str(tooling),
            '--manifest',str(mf),'--accepted-digest',hashlib.sha256(mf.read_bytes()).hexdigest(),
            '--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),
            '--repo',scope['repository'],'--pr-number','7','--expected-head',scope['head'],'--verdict-file',str(verdict)]}
    configpath=tmp_path/'config.json';configpath.write_text(json.dumps(config))
    script = tmp_path/'composition.cjs'
    script.write_text(r'''
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const issuer = require(process.argv[2]);
(async () => {
 const {privateKey, publicKey} = crypto.generateKeyPairSync('rsa', {modulusLength:2048});
 const jwt = issuer.signApp('Iv1.fixture', privateKey.export({type:'pkcs8',format:'pem'}), 2000000000);
 const pieces = jwt.split('.');
 const claims = JSON.parse(Buffer.from(pieces[1], 'base64url'));
 assert.equal(claims.iss, 'Iv1.fixture');
 assert.equal(claims.iat, 1999999940); assert.equal(claims.exp, 2000000300);
 assert(crypto.verify('RSA-SHA256', Buffer.from(pieces.slice(0,2).join('.')), publicKey, Buffer.from(pieces[2],'base64url')));
 const parent=path.join(process.argv[3],'private');
 const events=[];let lastBody;const rawTokens=[];
 const scope={repository:'ContextualWisdomLab/example',number:7,head:'a'.repeat(40),base:'b'.repeat(40),author:'writer',reviewer:'cwl-noema-review[bot]'};
 const transport=async(method,route,payload,credential)=>{
  events.push([method,route]);assert(credential);
  if(route==='/app')return Buffer.from('{"id":11,"slug":"cwl-noema-review"}');
  if(route.endsWith('/installation'))return Buffer.from('{"id":7,"app_id":11}');
  if(method==='DELETE')return Buffer.alloc(0);
  const token=payload.permissions.pull_requests==='write'?'FIXTURE_WRITE':'FIXTURE_READ_'+rawTokens.length;
  rawTokens.push(token);
  const raw=Buffer.from(JSON.stringify({token,expires_at:'2033-05-18T04:33:20Z',permissions:payload.permissions,repositories:[{full_name:scope.repository}]}));
  lastBody=raw;return raw;
 };
 let fenced=false;
 const cfg=JSON.parse(fs.readFileSync(process.argv[4]));
 const controller=async(file,env)=>{
    assert(fenced);assert.deepEqual(fs.readFileSync(file),lastBody);
    assert.equal(fs.statSync(file).mode&0o777,0o600);assert.equal(fs.statSync(file).nlink,1);
    assert(!('NOEMA_GITHUB_APP_PRIVATE_KEY' in env));
    assert(!('LLM_GATEWAY_API_KEY' in env));assert(!('NOEMA_LLM_API_KEY' in env));
    const result=require('node:child_process').spawnSync(cfg.python,['-I','-B',cfg.controller,...cfg.args,'--phase-issuance',file],
      {env:{PATH:cfg.path,GH_TOKEN:env.GH_TOKEN},encoding:'utf8',timeout:15000});
    assert.equal(result.status,0,'real Python controller and inert publisher child refused');return result.status;
 };
 await issuer.runPhase({phase:'publish',scope,appId:11,installationId:7,privateParent:parent,
   clientId:'Iv1.fixture',privateKey:privateKey.export({type:'pkcs8',format:'pem'}),now:()=>2000000000,
   transport,fence:async(token,phase)=>{assert(token.startsWith('FIXTURE_READ'));assert.equal(phase,'publish');fenced=true;},
   controller});
 assert.equal(events.filter(e=>e[0]==='DELETE').length,2);
 assert(!fs.existsSync(path.join(parent,'publish.json')));
 assert.equal(rawTokens.length,2);
 console.log('SYNTHETIC_COMPOSITION_PASS');
})().catch(()=>{console.error('SYNTHETIC_COMPOSITION_FAIL');process.exitCode=1});
''')
    result = subprocess.run([shutil.which('node'),str(script),str(HELPER),str(tmp_path),str(configpath)],
                            env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=20)
    assert result.returncode == 0 and result.stdout.strip() == 'SYNTHETIC_COMPOSITION_PASS', result.stderr


def test_real_issuer_main_fences_then_runs_prepare_and_publish_without_external_jwt(tmp_path):
    """Execute both real CLIs with only synthetic HTTPS and inert phase children."""
    import hashlib
    import sys
    from tests.test_noema_issuer_producer_controls import bootstrap_case
    private, source, entry, _, admission=bootstrap_case(tmp_path)
    scope={'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
           'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'}
    envelope={'schema_version':1,'repository':scope['repository'],'pull_request_number':7,
              'expected_head':scope['head'],'expected_base':scope['base'],'reviewer_actor':scope['reviewer'],
              'pull_request_author':'writer','verdict':{'decision':'approve'}}
    entry.write_text('import os,sys\nfrom pathlib import Path\n'
        'a=sys.argv\n'
        'assert "NOEMA_GITHUB_APP_PRIVATE_KEY" not in os.environ\n'
        'if "--prepare-verdict-file" in a:\n'
        ' assert os.environ["GH_TOKEN"]=="MAIN_READ_0"\n'
        ' assert os.environ["NOEMA_LLM_MODEL"]=="auto"\n'
        ' p=Path(a[a.index("--prepare-verdict-file")+1]);p.write_text('+repr(json.dumps(envelope))+');p.chmod(0o600)\n'
        'else:\n'
        ' assert os.environ["GH_TOKEN"]=="MAIN_WRITE_2"\n'
        ' assert "LLM_GATEWAY_API_KEY" not in os.environ and "NOEMA_LLM_API_KEY" not in os.environ\n'
        ' p=Path(a[a.index("--publish-verdict-file")+1]);Path(str(p)+".marker").write_text("INERT_NATIVE_PUBLISH");p.unlink()\n')
    mf,af=tmp_path/'manifest',tmp_path/'admission'
    manifest={'schema_version':1,'repository':'ContextualWisdomLab/.github','commit':'c'*40,'tree':'d'*40,
              'entrypoint':entry.relative_to(source).as_posix(),
              'files':{entry.relative_to(source).as_posix():hashlib.sha256(entry.read_bytes()).hexdigest()}}
    node=Path(shutil.which('node')).resolve()
    admission.update(scope=scope,installation_id=7,app_id=11)
    admission['dependencies'][str(node)]=hashlib.sha256(node.read_bytes()).hexdigest()
    mf.write_text(json.dumps(manifest));af.write_text(json.dumps(admission))
    from scripts.ci import noema_bootstrap_producer as producer
    producer.materialize_tooling(source,private/'tooling',mf.read_bytes(),accepted_digest=hashlib.sha256(mf.read_bytes()).hexdigest(),
                                 admission=admission,private_parent=private)
    pr={'base':{'sha':scope['base'],'repo':{'full_name':scope['repository']}},'head':{'sha':scope['head']},
        'number':7,'user':{'login':'writer'},'state':'open','draft':False}
    gh=tmp_path/'gh';gh.write_text('#!/bin/sh\ncase "$GH_TOKEN" in MAIN_READ_0|MAIN_READ_1) ;; *) exit 77;; esac\n'+"printf '%s' '"+json.dumps(pr)+"'\n");gh.chmod(0o755)
    common=['--private-parent',str(private),'--source-root',str(source),'--manifest',str(mf),
            '--accepted-digest',hashlib.sha256(mf.read_bytes()).hexdigest(),'--admission',str(af),
            '--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),'--repo',scope['repository'],
            '--pr-number','7','--expected-head',scope['head'],'--verdict-file',str(private/'verdict.json')]
    cfg=tmp_path/'cfg.json';cfg.write_text(json.dumps({'common':common,'path':str(tmp_path)+':/usr/bin:/bin','parent':str(private)}))
    script=tmp_path/'main.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),https=require('node:https');
const {EventEmitter}=require('node:events');const helper=require(process.argv[2]);
const config=JSON.parse(fs.readFileSync(process.argv[3]));const events=[];let issued=0;
https.request=(options,callback)=>{
 const req=new EventEmitter();let body='';req.setTimeout=()=>{};req.write=chunk=>{body+=chunk};req.destroy=()=>{};
 req.end=()=>{
  events.push([options.method,options.path]);
  assert.equal(options.hostname,'api.github.com');
  assert(!('NOEMA_GITHUB_APP_PRIVATE_KEY' in options));
  let raw;const res=new EventEmitter();res.statusCode=options.method==='DELETE'?204:options.method==='POST'?201:200;res.complete=true;
  if(options.path==='/app')raw=Buffer.from('{"id":11,"slug":"cwl-noema-review"}');
  else if(options.path.endsWith('/installation'))raw=Buffer.from('{"id":7,"app_id":11}');
  else if(options.method==='DELETE')raw=Buffer.alloc(0);
  else {const p=JSON.parse(body);if(p.permissions.pull_requests==='write')assert(fs.existsSync(config.parent+'/verdict.json'));
    raw=Buffer.from(JSON.stringify({token:(p.permissions.pull_requests==='write'?'MAIN_WRITE_':'MAIN_READ_')+(issued++),
    expires_at:new Date(Date.now()+3600000).toISOString(),permissions:p.permissions,repositories:[{full_name:'ContextualWisdomLab/example'}]}));}
  res.headers={'content-length':String(raw.length)};callback(res);
  queueMicrotask(()=>{res.emit('data',raw);res.emit('end')});
 };return req;
};
(async()=>{
 const pair=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
 const env={PATH:config.path,NOEMA_GITHUB_APP_CLIENT_ID:'Iv1.fixture',NOEMA_GITHUB_APP_PRIVATE_KEY:pair.privateKey.export({type:'pkcs8',format:'pem'}),LLM_GATEWAY_API_KEY:'SYNTHETIC_EXISTING_INFERENCE'};
 assert.equal(await helper.main(['--phase','prepare',...config.common],env),0,'real prepare fence or controller missing');
 assert.equal(await helper.main(['--phase','publish',...config.common],env),0,'real publisher composition missing');
 assert.equal(issued,3);assert.equal(events.filter(x=>x[0]==='DELETE').length,3);
 assert.equal(fs.readFileSync(config.parent+'/verdict.json.marker','utf8'),'INERT_NATIVE_PUBLISH');
 console.log('MAIN_COMPOSITION_PASS');
})().catch(()=>{console.error('MAIN_COMPOSITION_FAIL');process.exitCode=1});
''')
    result=subprocess.run([str(node),str(script),str(HELPER),str(cfg)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=25)
    assert result.returncode==0 and result.stdout.strip()=='MAIN_COMPOSITION_PASS','real prepare fence or controller missing: '+result.stderr


def test_issuer_parses_duplicate_responses_fail_closed_and_cleans_token(tmp_path):
    """Duplicate permission keys cannot rewrite an original grant into acceptance."""
    script=tmp_path/'duplicate.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');const issuer=require(process.argv[2]);
(async()=>{
 const parent=process.argv[3]+'/private';fs.mkdirSync(parent,{mode:0o700});let deletes=0,controller=0;
 const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
 await assert.rejects(issuer.runPhase({phase:'prepare',scope:{repository:'ContextualWisdomLab/example',reviewer:'cwl-noema-review[bot]'},appId:11,installationId:7,
  privateParent:parent,clientId:'Iv1.fixture',privateKey:key,now:()=>2000000000,
  transport:async(method,route)=>{
   if(method==='DELETE'){deletes++;return Buffer.alloc(0);}
   if(route==='/app')return Buffer.from('{"id":11,"slug":"cwl-noema-review"}');
   if(route.endsWith('/installation'))return Buffer.from('{"id":7,"app_id":11}');
   return Buffer.from('{"token":"DUPLICATE_FIXTURE","expires_at":"2033-05-18T04:33:20Z","permissions":{"contents":"write","contents":"read","metadata":"read","pull_requests":"read"},"repositories":[{"full_name":"ContextualWisdomLab/example"}]}');
  },fence:async()=>{},controller:async()=>{controller++;return 0;}}));
 assert.equal(controller,0);assert.equal(deletes,1,'safely parsed unique token lost revocation custody');
 console.log('DUPLICATE_REJECTED');
})().catch(()=>{console.error('DUPLICATE_FAIL');process.exitCode=1});
''')
    result=subprocess.run([shutil.which('node'),str(script),str(HELPER),str(tmp_path)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and result.stdout.strip()=='DUPLICATE_REJECTED', 'duplicate original grant accepted or cleanup lost'


def test_fixed_origin_http_response_framing_and_missing_signer_refuse(tmp_path):
    """Characterize bounded original-body framing with synthetic HTTP events."""
    script=tmp_path/'framing.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),https=require('node:https'),{EventEmitter}=require('node:events');
const issuer=require(process.argv[2]);
(async()=>{
 for(const mutation of ['complete','short','redirect','oversize','incomplete']){
  https.request=(opts,callback)=>{
   assert.equal(opts.hostname,'api.github.com');assert.equal(opts.port,443);
   const req=new EventEmitter();req.setTimeout=()=>{};req.write=()=>{};req.end=()=>{
    const res=new EventEmitter();res.statusCode=mutation==='redirect'?302:200;
    res.complete=mutation!=='incomplete';res.destroy=()=>{};
    const raw=mutation==='oversize'?Buffer.alloc(2*1024*1024+1):Buffer.from('{"ok":true}');
    res.headers={'content-length':String(raw.length+(mutation==='short'?3:0))};callback(res);
    queueMicrotask(()=>{res.emit('data',raw);res.emit('end')});
   };return req;
  };
  if(mutation==='complete')assert.deepEqual(await issuer.transport('GET','/app',null,'FIXTURE_JWT'),Buffer.from('{"ok":true}'));
  else await assert.rejects(issuer.transport('GET','/app',null,'FIXTURE_JWT'));
 }
 assert.throws(()=>issuer.signApp('Iv1.fixture','',2000000000));
 await assert.rejects(issuer.transport('GET','/foreign',null,'FIXTURE_JWT'));
 console.log('HTTP_CONTROLS_PASS');
})().catch(()=>{console.error('HTTP_CONTROLS_FAIL');process.exitCode=1});
''')
    result=subprocess.run([shutil.which('node'),str(script),str(HELPER)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and result.stdout.strip()=='HTTP_CONTROLS_PASS',result.stderr


def test_write_scope_revocation_during_app_wait_never_posts_write(tmp_path):
    """A scope change while publisher authentication waits must block write POST."""
    script=tmp_path/'wait.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');const issuer=require(process.argv[2]);
(async()=>{
 const parent=process.argv[3]+'/private';fs.mkdirSync(parent,{mode:0o700});let appReads=0,writes=0,revoked=false,deletes=0;
 const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
 await assert.rejects(issuer.runPhase({phase:'publish',scope:{repository:'ContextualWisdomLab/example',reviewer:'cwl-noema-review[bot]'},appId:11,installationId:7,
  privateParent:parent,clientId:'Iv1.fixture',privateKey:key,now:()=>2000000000,
  transport:async(method,route,payload)=>{
   if(method==='DELETE'){deletes++;return Buffer.alloc(0);}
   if(route==='/app'){if(++appReads===2)revoked=true;return Buffer.from('{"id":11,"slug":"cwl-noema-review"}');}
   if(route.endsWith('/installation'))return Buffer.from('{"id":7,"app_id":11}');
   if(payload.permissions.pull_requests==='write')writes++;
   return Buffer.from(JSON.stringify({token:'WAIT_FIXTURE',expires_at:'2033-05-18T04:33:20Z',permissions:payload.permissions,repositories:[{full_name:'ContextualWisdomLab/example'}]}));
  },fence:async()=>{if(revoked)throw Error('SCOPE_REVOKED');},controller:async()=>0}));
 assert.equal(writes,0,'scope revoked during App authentication reached write issuance');assert.equal(deletes,1);
 console.log('WAIT_REVOKED');
})().catch(()=>{console.error('WAIT_FAIL');process.exitCode=1});
''')
    result=subprocess.run([shutil.which('node'),str(script),str(HELPER),str(tmp_path)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and result.stdout.strip()=='WAIT_REVOKED','scope revoked during App authentication reached write issuance'


def test_publication_action_mints_only_scoped_write_capability():
    """A fresh App token alone receives the permission needed to publish."""
    text=(ROOT/'.github/workflows/noema-review.yml').read_text()
    refresh=text.split('      - name: Refresh repository-scoped Noema GitHub App token for publication\n',1)[1].split('      - name:',1)[0]
    assert 'permission-pull-requests: write' in refresh
    assert 'permission-contents: read' in refresh
    assert 'permission-metadata: read' in refresh
    assert 'permission-actions:' not in refresh


def test_issuer_main_refuses_unpinned_python_before_executing_it(tmp_path):
    """Accepted admission must bind executable bytes before any subprocess spawn."""
    import hashlib
    import sys
    from tests.test_noema_issuer_producer_controls import bootstrap_case
    private,source,entry,raw,admission=bootstrap_case(tmp_path)
    marker=tmp_path/'executed'
    fake=tmp_path/'fake-python';fake.write_text('#!/bin/sh\nprintf RUN > '+str(marker)+'\nexit 0\n');fake.chmod(0o755)
    admission['interpreter']={'path':str(fake),'sha256':'0'*64}
    admission.update(scope={'repository':'ContextualWisdomLab/example','number':7,'head':'a'*40,
                            'base':'b'*40,'author':'writer','reviewer':'cwl-noema-review[bot]'},
                     app_id=11,installation_id=7)
    node=Path(shutil.which('node')).resolve();admission['dependencies'][str(node)]=hashlib.sha256(node.read_bytes()).hexdigest()
    mf,af=tmp_path/'manifest',tmp_path/'admission';mf.write_bytes(raw);af.write_text(json.dumps(admission))
    args=['--phase','prepare','--private-parent',str(private),'--source-root',str(source),
          '--manifest',str(mf),'--accepted-digest',hashlib.sha256(raw).hexdigest(),
          '--admission',str(af),'--admission-digest',hashlib.sha256(af.read_bytes()).hexdigest(),
          '--repo','ContextualWisdomLab/example','--pr-number','7','--expected-head','a'*40,
          '--verdict-file',str(private/'verdict.json')]
    cfg=tmp_path/'config.json';cfg.write_text(json.dumps(args))
    script=tmp_path/'python-pin.cjs'
    script.write_text(r'''
const fs=require('node:fs'),crypto=require('node:crypto'),https=require('node:https'),{EventEmitter}=require('node:events');
const issuer=require(process.argv[2]);
https.request=(opts,callback)=>{const req=new EventEmitter();req.setTimeout=()=>{};req.write=()=>{};req.end=()=>{
 const raw=Buffer.from(opts.path==='/app'?'{"id":11,"slug":"cwl-noema-review"}':opts.path.endsWith('/installation')?'{"id":7,"app_id":11}':opts.method==='DELETE'?'':JSON.stringify({token:'INTERPRETER_FIXTURE',expires_at:new Date(Date.now()+3600000).toISOString(),permissions:{contents:'read',metadata:'read',pull_requests:'read'},repositories:[{full_name:'ContextualWisdomLab/example'}]}));
 const res=new EventEmitter();res.statusCode=opts.method==='DELETE'?204:opts.method==='POST'?201:200;res.complete=true;res.headers={'content-length':String(raw.length)};callback(res);queueMicrotask(()=>{res.emit('data',raw);res.emit('end')});};return req;};
const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
issuer.main(JSON.parse(fs.readFileSync(process.argv[3])),{PATH:'/usr/bin:/bin',NOEMA_GITHUB_APP_CLIENT_ID:'Iv1.fixture',NOEMA_GITHUB_APP_PRIVATE_KEY:key}).then(()=>{process.exitCode=2}).catch(()=>{process.exitCode=1});
''')
    result=subprocess.run([str(node),str(script),str(HELPER),str(cfg)],env={'PATH':'/usr/bin:/bin'},
        capture_output=True,text=True,timeout=15)
    assert result.returncode != 0
    assert not marker.exists(), 'unadmitted executable ran before interpreter byte check'


def test_multi_hour_preparation_settles_expired_read_grant_without_blocking_result(tmp_path):
    """Known expiry after the model is not an unconfirmed live credential leak."""
    script=tmp_path/'long-model.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');const issuer=require(process.argv[2]);
(async()=>{
 const parent=process.argv[3]+'/private';fs.mkdirSync(parent,{mode:0o700});let now=2000000000,deletes=0;
 const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
 const outcome=await issuer.runPhase({phase:'prepare',scope:{repository:'ContextualWisdomLab/example',reviewer:'cwl-noema-review[bot]'},appId:11,installationId:7,
  privateParent:parent,clientId:'Iv1.fixture',privateKey:key,now:()=>now,
  transport:async(method,route,payload)=>{
   if(method==='DELETE'){deletes++;const error=Error('FIXTURE_EXPIRED');error.statusCode=401;throw error;}
   if(route==='/app')return Buffer.from('{"id":11,"slug":"cwl-noema-review"}');
   if(route.endsWith('/installation'))return Buffer.from('{"id":7,"app_id":11}');
   return Buffer.from(JSON.stringify({token:'LONG_MODEL_READ_ONLY',expires_at:new Date((now+3600)*1000).toISOString(),permissions:payload.permissions,repositories:[{full_name:'ContextualWisdomLab/example'}]}));
  },fence:async()=>{},controller:async()=>{now+=10800;return 0;}});
 assert.equal(outcome,0);assert.equal(deletes,1);assert(!fs.existsSync(parent+'/prepare.json'));
 console.log('LONG_MODEL_PASS');
})().catch(()=>{console.error('LONG_MODEL_FAIL');process.exitCode=1});
''')
    result=subprocess.run([shutil.which('node'),str(script),str(HELPER),str(tmp_path)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and result.stdout.strip()=='LONG_MODEL_PASS','expired readonly cleanup blocks completed multi-hour model'


def test_prepare_controller_does_not_impose_a_model_deadline():
    """The new wrapper must preserve the existing unlimited inference contract."""
    source=HELPER.read_text()
    assert "timeout:phase==='prepare'?" not in source, 'issuer adds a fixed model deadline'


def test_rejected_grants_and_downstream_errors_keep_revocation_custody(tmp_path):
    """Exercise new issuer negatives without touching completed composition cases."""
    script=tmp_path/'controls.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const issuer=require(process.argv[2]);
(async()=>{
 const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
 const scope={repository:'ContextualWisdomLab/example',reviewer:'cwl-noema-review[bot]'};
 for(const mutation of ['bad_signer','stale_scope','expiry','permission','wrong_app','wrong_install','wrong_repo','downstream','cleanup','delivery']){
  const parent=path.join(process.argv[3],mutation);fs.mkdirSync(parent,{mode:0o700});
  let posts=0,deletes=0,controllers=0;
  const originalWrite=fs.writeFileSync;
  const request=async(method,route,payload)=>{
   if(method==='DELETE'){deletes++;if(mutation==='cleanup')throw Error('DENIED');return Buffer.alloc(0);}
   if(route==='/app')return Buffer.from(JSON.stringify({id:mutation==='wrong_app'?12:11,slug:'cwl-noema-review'}));
   if(route.endsWith('/installation'))return Buffer.from(JSON.stringify({id:mutation==='wrong_install'?8:7,app_id:11}));
   posts++;
   return Buffer.from(JSON.stringify({token:'FIXTURE_CONTROL',expires_at:mutation==='expiry'?'2000-01-01T00:00:00Z':'2033-05-18T04:33:20Z',
    permissions:mutation==='permission'?{...payload.permissions,contents:'write'}:payload.permissions,
    repositories:[{full_name:mutation==='wrong_repo'?'ContextualWisdomLab/other':scope.repository}]}));
  };
  if(mutation==='delivery')fs.writeFileSync=(...args)=>{if(typeof args[0]==='number'){originalWrite(args[0],Buffer.from('PARTIAL'));throw Error('IO');}return originalWrite(...args);};
  try{
   await assert.rejects(issuer.runPhase({phase:'publish',scope,appId:11,installationId:7,privateParent:parent,
    clientId:'Iv1.fixture',privateKey:mutation==='bad_signer'?'BAD_SYNTHETIC_KEY':key,now:()=>2000000000,transport:request,
    fence:async()=>{if(mutation==='stale_scope')throw Error('STALE');},
    controller:async()=>{controllers++;throw Error('DOWNSTREAM');}}));
   if(['bad_signer','wrong_app','wrong_install'].includes(mutation)){assert.equal(posts,0);assert.equal(deletes,0);}
   else if(mutation==='stale_scope'){assert.equal(posts,1);assert.equal(deletes,1);}
   else if(['expiry','permission','wrong_repo'].includes(mutation)){assert.equal(posts,1);assert.equal(deletes,1);assert.equal(controllers,0);}
   else {assert.equal(posts,2);assert.equal(deletes,2);}
   assert(!fs.existsSync(path.join(parent,'publish.json')),'partial delivery survived cleanup');
  }finally{fs.writeFileSync=originalWrite;}
 }
 console.log('ISSUER_CONTROLS_PASS');
})().catch(()=>{console.error('ISSUER_CONTROLS_FAIL');process.exitCode=1});
''')
    result=subprocess.run([shutil.which('node'),str(script),str(HELPER),str(tmp_path)],env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and result.stdout.strip()=='ISSUER_CONTROLS_PASS','partial delivery survived cleanup or missing issuer denial: '+result.stderr
