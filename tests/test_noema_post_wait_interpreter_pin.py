"""New post-wait interpreter admission controls, with no operational authority."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('drift', ['app', 'installation', 'issuance', 'controller', 'same_bytes_inode', 'none'])
def test_post_wait_shared_child_refuses_changed_interpreter(tmp_path, drift):
    """Actual issuer main must reject drift before either shared spawn boundary."""
    script = tmp_path/'probe.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),https=require('node:https');
const {EventEmitter}=require('node:events');const issuer=require(process.argv[2]);
(async()=>{
 const root=process.argv[3],drift=process.argv[4],parent=root+'/private';fs.mkdirSync(parent,{mode:0o700});
 const marker=root+'/launched',foreign=root+'/foreign',python=root+'/python';
 const original='#!/bin/sh\nprintf X >> "'+marker+'"\n'+(drift==='controller'?'cp "'+root+'/replacement" "'+python+'"\n':'')+'exit 0\n';
 const replacement='#!/bin/sh\nprintf BAD >> "'+foreign+'"\nexit 0\n';
 fs.writeFileSync(python,original,{mode:0o700});fs.writeFileSync(root+'/replacement',replacement);
 const digest=raw=>crypto.createHash('sha256').update(raw).digest('hex');
 const admission={scope:{repository:'ContextualWisdomLab/example',number:7,head:'a'.repeat(40),base:'b'.repeat(40),author:'writer',reviewer:'cwl-noema-review[bot]'},app_id:11,installation_id:7,
  interpreter:{path:python,sha256:digest(fs.readFileSync(python))},dependencies:{[fs.realpathSync(process.execPath)]:digest(fs.readFileSync(process.execPath))}};
 const af=root+'/admission';fs.writeFileSync(af,JSON.stringify(admission));let deletes=0,changed=false;
 https.request=(opts,callback)=>{const req=new EventEmitter();let body='';req.setTimeout=()=>{};req.write=c=>body+=c;req.end=()=>{
  let raw;
  if(opts.method==='DELETE'){deletes++;raw=Buffer.alloc(0);}
  else if(opts.path==='/app')raw=Buffer.from('{"id":11,"slug":"cwl-noema-review"}');
  else if(opts.path.endsWith('/installation'))raw=Buffer.from('{"id":7,"app_id":11}');
  else raw=Buffer.from(JSON.stringify({token:'POSTWAIT_FIXTURE',expires_at:new Date(Date.now()+3600000).toISOString(),permissions:JSON.parse(body).permissions,repositories:[{full_name:admission.scope.repository}]}));
  const stage=opts.path==='/app'?'app':opts.path.endsWith('/installation')?'installation':'issuance';
  if(!changed && opts.method!=='DELETE' && (drift===stage || (drift==='same_bytes_inode' && stage==='issuance'))){
   changed=true;if(drift==='same_bytes_inode'){fs.renameSync(python,root+'/old');fs.writeFileSync(python,original,{mode:0o700});}
   else fs.writeFileSync(python,replacement);
  }
  const res=new EventEmitter();res.complete=true;res.statusCode=opts.method==='DELETE'?204:opts.method==='POST'?201:200;res.headers={'content-length':String(raw.length)};callback(res);
  queueMicrotask(()=>{res.emit('data',raw);res.emit('end')});};return req;};
 const key=crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey.export({type:'pkcs8',format:'pem'});
 const args=['--phase','prepare','--private-parent',parent,'--source-root',root+'/source','--manifest',root+'/manifest','--accepted-digest','0'.repeat(64),'--admission',af,'--admission-digest',digest(fs.readFileSync(af)),'--repo',admission.scope.repository,'--pr-number','7','--expected-head',admission.scope.head,'--verdict-file',parent+'/verdict.json'];
 let rejected=false;try{await issuer.main(args,{PATH:'/usr/bin:/bin',NOEMA_GITHUB_APP_CLIENT_ID:'Iv1.fixture',NOEMA_GITHUB_APP_PRIVATE_KEY:key,LLM_GATEWAY_API_KEY:'INERT_INFERENCE'});}catch{rejected=true;}
 const launches=fs.existsSync(marker)?fs.readFileSync(marker,'utf8').length:0;
 assert(!fs.existsSync(foreign),'unadmitted post-wait interpreter executed');
 if(drift==='none'){assert(!rejected);assert.equal(launches,2);}
 else {assert(rejected,'post-wait interpreter drift was admitted');assert.equal(launches,drift==='controller'?1:0);}
 assert.equal(deletes,1);assert(!fs.existsSync(parent+'/prepare.json'));
 console.log('POST_WAIT_CONTROL_PASS');
})().catch(error=>{console.error(error.message);process.exitCode=1});
''')
    result = subprocess.run([shutil.which('node'), str(script), str(ROOT/'scripts/ci/noema_existing_app_issuer.cjs'), str(tmp_path), drift],
                            env={'PATH':'/usr/bin:/bin'}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and result.stdout.strip() == 'POST_WAIT_CONTROL_PASS', result.stderr
