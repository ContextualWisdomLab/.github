/* Existing-App phase issuer. Only trusted workflow steps supply Secret inputs.
 * No key/JWT/token is projected into stdout, argv, artifacts or child env.
 * Callbacks below are trusted fixture seams, never PR-provided code.
 */
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const https = require('node:https');
const {spawnSync} = require('node:child_process');
const LIMIT = 2 * 1024 * 1024;

function signApp(clientId, pem, now) {
  if (typeof clientId !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(clientId) ||
      typeof pem !== 'string' || !Number.isSafeInteger(now)) throw new Error('signer refused');
  const key = crypto.createPrivateKey(pem);
  if (key.asymmetricKeyType !== 'rsa' || key.asymmetricKeyDetails.modulusLength < 2048)
    throw new Error('signer refused');
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const body = encode({alg:'RS256',typ:'JWT'}) + '.' + encode({iat:now-60,exp:now+300,iss:clientId});
  return body + '.' + crypto.sign('RSA-SHA256',Buffer.from(body),key).toString('base64url');
}

function parse(raw, captureToken) {
  if (!Buffer.isBuffer(raw) || !raw.length || raw.length > LIMIT) throw new Error('response refused');
  const text = new TextDecoder('utf-8',{fatal:true}).decode(raw);
  const value = JSON.parse(text);
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('response refused');
  // Native JSON.parse validates syntax but silently keeps the last duplicate.
  // Walk that validated grammar to reject duplicates at every object depth.
  let cursor=0,duplicate=false,duplicateToken=false;
  function whitespace(){while(/\s/.test(text[cursor]||'') && cursor<text.length)cursor++;}
  function string(){const m=text.slice(cursor).match(/^"(?:[^"\\]|\\.)*"/s);if(!m)throw new Error('response refused');cursor+=m[0].length;return JSON.parse(m[0]);}
  function walk(depth){
    if(depth>128)throw new Error('response refused');whitespace();
    const c=text[cursor];
    if(c==='"'){string();return;}
    if(c==='{' || c==='['){
      cursor++;whitespace();const keys=new Set(),end=c==='{'?'}':']';
      if(text[cursor]===end){cursor++;return;}
      for(;;){
        if(c==='{'){
          const key=string();if(keys.has(key)){duplicate=true;if(depth===0 && key==='token')duplicateToken=true;}keys.add(key);
          whitespace();cursor++; // colon: syntax was already validated above
        }
        walk(depth+1);whitespace();const separator=text[cursor++];
        if(separator===end)break;whitespace();
      }
      return;
    }
    const m=text.slice(cursor).match(/^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/);
    if(!m)throw new Error('response refused');cursor+=m[0].length;
  }
  walk(0);
  if(captureToken && !duplicateToken && typeof value.token==='string' && value.token.trim() && !/\s/.test(value.token))
    captureToken(value.token);
  if(duplicate)throw new Error('response duplicate refused');
  return value;
}

function transport(method, route, payload, credential) {
  if (!['GET','POST','DELETE'].includes(method) ||
      !/^\/(app|repos\/ContextualWisdomLab\/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+\/installation|app\/installations\/[1-9][0-9]*\/access_tokens|installation\/token)$/.test(route))
    return Promise.reject(new Error('endpoint refused'));
  return new Promise((resolve,reject) => {
    const body = payload === null ? null : Buffer.from(JSON.stringify(payload));
    const req = https.request({hostname:'api.github.com',port:443,path:route,method,
      headers:{Authorization:'Bearer '+credential,Accept:'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28','User-Agent':'cwl-noema-issuer',
        ...(body ? {'Content-Type':'application/json','Content-Length':body.length}: {})}}, res => {
      const chunks=[];let size=0;
      res.on('data',chunk=>{size+=chunk.length;if(size>LIMIT){res.destroy();reject(new Error('response refused'));}else chunks.push(chunk);});
      res.on('aborted',()=>reject(new Error('response refused')));
      res.on('error',()=>reject(new Error('response refused')));
      res.on('end',()=>{
        const length=res.headers['content-length'];
        if (res.statusCode !== (method==='DELETE'?204:method==='POST'?201:200) ||
            !res.complete || (length!==undefined && (!/^[0-9]+$/.test(length) || Number(length)!==size)))
          {const error=new Error('response refused');error.statusCode=res.statusCode;reject(error);}
        else resolve(Buffer.concat(chunks));
      });
    });
    req.setTimeout(60000,()=>req.destroy(new Error('request refused')));
    req.on('error',()=>reject(new Error('request refused')));
    if(body)req.write(body);req.end();
  });
}

function privateParent(parent) {
  if (!path.isAbsolute(parent) || path.resolve(parent)!==parent) throw new Error('custody refused');
  for(let p=parent;;p=path.dirname(p)){
    if(fs.lstatSync(p).isSymbolicLink())throw new Error('custody refused');
    if(path.dirname(p)===p)break;
  }
  const s=fs.lstatSync(parent);
  if(!s.isDirectory() || s.uid!==process.getuid() || (s.mode&0o077))throw new Error('custody refused');
  return s;
}

async function runPhase(options) {
  const {phase,scope,appId,installationId,privateParent:parent,clientId,privateKey,
    fence,controller,transport:request=transport,now=()=>Math.floor(Date.now()/1000)}=options;
  if (!['prepare','publish'].includes(phase) || !Number.isSafeInteger(appId) || appId<1 ||
      !Number.isSafeInteger(installationId) || installationId<1 ||
      !/^ContextualWisdomLab\/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$/.test(scope.repository) ||
      scope.reviewer!=='cwl-noema-review[bot]')throw new Error('identity refused');
  const initial=privateParent(parent);const target=path.join(parent,phase+'.json');
  if(fs.existsSync(target) || fs.lstatSync(parent).ino!==initial.ino)throw new Error('delivery refused');
  const tokens=[];const expiries=new Map();let delivered=false;let primary;let result;let cleanupFailed=false;
  async function issue(grant, readToken) {
    // Short-lived App authentication is created inside each issuer phase, not
    // supplied by an absent external JWT producer or retained across the model.
    const jwt=signApp(clientId,privateKey,now());
    const app=parse(await request('GET','/app',null,jwt));
    if(app.id!==appId || app.slug!=='cwl-noema-review')throw new Error('identity refused');
    if(readToken)await fence(readToken,phase);
    const install=parse(await request('GET','/repos/'+scope.repository+'/installation',null,jwt));
    if(install.id!==installationId || install.app_id!==appId)throw new Error('identity refused');
    if(readToken)await fence(readToken,phase);
    const permissions={contents:'read',metadata:'read',pull_requests:grant};
    const raw=await request('POST','/app/installations/'+installationId+'/access_tokens',
      {repositories:[scope.repository.split('/')[1]],permissions},jwt);
    const response=parse(raw, token => tokens.push(token));
    // Capture a safely parsed token before checking grant/expiry/delivery so
    // rejected issuance is still revocation-owned. Never use it for fallback.
    if(!tokens.includes(response.token))throw new Error('token refused');
    if(Object.keys(response.permissions||{}).length!==3 ||
        Object.entries(permissions).some(([k,v])=>response.permissions[k]!==v) ||
        !Array.isArray(response.repositories) || response.repositories.length!==1 ||
        response.repositories[0].full_name!==scope.repository)throw new Error('grant refused');
    const expires=Date.parse(response.expires_at);
    if(!Number.isFinite(expires) || expires<=now()*1000+60000)throw new Error('expiry refused');
    expiries.set(response.token,expires);
    return {raw,token:response.token};
  }
  try {
    const read=await issue('read');
    await fence(read.token,phase);
    let selected=read;
    if(phase==='publish'){
      selected=await issue('write',read.token);
      await fence(read.token,phase);
    }
    const current=privateParent(parent);
    if(current.dev!==initial.dev || current.ino!==initial.ino || current.mode!==initial.mode)
      throw new Error('custody refused');
    const fd=fs.openSync(target,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
    delivered=true;
    try{fs.writeFileSync(fd,selected.raw);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    const env={PATH:'/usr/bin:/bin',GH_TOKEN:read.token};
    // The controller's live metadata read uses the read grant; its publisher
    // child receives the separately issued write grant from the original file.
    result=await controller(target,env);
    if(result!==0)throw new Error('controller refused');
  } catch(error){primary=error;}
  finally {
    for(const token of tokens){
      try{await request('DELETE','/installation/token',null,token);}
      catch(error){
        if(!(error.statusCode===401 && expiries.has(token) && expiries.get(token)<=now()*1000))cleanupFailed=true;
      }
    }
    if(delivered){try{fs.unlinkSync(target);}catch{cleanupFailed=true;}}
  }
  if(cleanupFailed)throw new Error('issuer cleanup unconfirmed');
  if(primary)throw primary;
  return result;
}

module.exports={signApp,runPhase,transport};

async function main(argv=process.argv.slice(2), environment=process.env) {
  const values={};
  const names=['phase','private-parent','source-root','manifest','accepted-digest','admission',
    'admission-digest','repo','pr-number','expected-head','verdict-file'];
  if(argv.length%2)throw new Error('arguments refused');
  for(let i=0;i<argv.length;i+=2){
    const name=argv[i].slice(2);
    if(argv[i]!=='--'+name || !names.includes(name) || name in values)throw new Error('arguments refused');
    values[name]=argv[i+1];
  }
  if(names.some(n=>!values[n]) || !['prepare','publish'].includes(values.phase) ||
      !/^[1-9][0-9]*$/.test(values['pr-number']) || !/^[a-f0-9]{40}$/.test(values['expected-head']))
    throw new Error('arguments refused');
  const phase=values.phase,parent=values['private-parent'];privateParent(parent);
  const admissionRaw=fs.readFileSync(values.admission);
  if(!/^[a-f0-9]{64}$/.test(values['admission-digest']) ||
      crypto.createHash('sha256').update(admissionRaw).digest('hex')!==values['admission-digest'])
    throw new Error('admission refused');
  const admission=parse(admissionRaw),scope=admission.scope;
  if(scope.repository!==values.repo || scope.number!==Number(values['pr-number']) ||
      scope.head!==values['expected-head'] || values['verdict-file']!==path.join(parent,'verdict.json'))
    throw new Error('scope refused');
  const python=admission.interpreter?.path;
  if(!python || !path.isAbsolute(python) ||
      !/^[a-f0-9]{64}$/.test(admission.interpreter.sha256) ||
      crypto.createHash('sha256').update(fs.readFileSync(python)).digest('hex')!==admission.interpreter.sha256)
    throw new Error('interpreter refused');
  const pythonIdentity=fs.statSync(python);
  const pythonRealpath=fs.realpathSync(python);
  const pinnedNode=admission.dependencies?.[fs.realpathSync(process.execPath)];
  if(!pinnedNode || crypto.createHash('sha256').update(fs.readFileSync(process.execPath)).digest('hex')!==pinnedNode)
    throw new Error('issuer interpreter refused');
  const root=path.resolve(__dirname,'../..');
  const common=['--private-parent',parent,'--source-root',values['source-root'],
    '--manifest',values.manifest,'--accepted-digest',values['accepted-digest'],
    '--admission',values.admission,'--admission-digest',values['admission-digest'],
    '--repo',values.repo,'--pr-number',values['pr-number'],'--expected-head',values['expected-head']];
  function child(script,args,env){
    // Revalidate after every issuer wait, before either credential-bearing child.
    // This is not atomic pathname execution; exclusive runtime custody remains required.
    const current=fs.statSync(python);
    if(!current.isFile() || fs.realpathSync(python)!==pythonRealpath ||
        ['dev','ino','mode','uid','gid'].some(key=>current[key]!==pythonIdentity[key]) ||
        crypto.createHash('sha256').update(fs.readFileSync(python)).digest('hex')!==admission.interpreter.sha256)
      throw new Error('interpreter refused');
    const result=spawnSync(python,['-I','-B',path.join(root,'scripts/ci',script),...args],
      {env,cwd:root,stdio:'ignore'});
    if(result.error || result.signal || result.status===null)throw new Error('child refused');
    return result.status;
  }
  const runtimePath=environment.PATH;
  if(!runtimePath)throw new Error('runtime refused');
  const fence=async(token,requested)=>{
    const mode=requested==='publish'?'--revalidate-publish':'--revalidate-prepare';
    const args=[mode,...common];
    if(requested==='publish')args.push('--verdict-file',values['verdict-file']);
    if(child('noema_bootstrap_producer.py',args,{PATH:runtimePath,GH_TOKEN:token})!==0)
      throw new Error('scope refused');
  };
  const controller=async(file,metadataEnvironment)=>{
    // Do not inherit Secret/JWT, workflow write token or inference into publisher.
    const env={PATH:runtimePath,GH_TOKEN:metadataEnvironment.GH_TOKEN};
    if(phase==='prepare'){
      if(!environment.LLM_GATEWAY_API_KEY)throw new Error('inference refused');
      env.LLM_GATEWAY_API_KEY=environment.LLM_GATEWAY_API_KEY;
    }
    const args=['--'+phase+'-production','--tooling-root',path.join(parent,'tooling'),
      '--manifest',values.manifest,'--accepted-digest',values['accepted-digest'],
      '--admission',values.admission,'--admission-digest',values['admission-digest'],
      '--repo',values.repo,'--pr-number',values['pr-number'],'--expected-head',values['expected-head'],
      '--verdict-file',values['verdict-file'],'--phase-issuance',file];
    return child('premerge_review_tooling.py',args,env);
  };
  return runPhase({phase,scope,appId:admission.app_id,installationId:admission.installation_id,
    privateParent:parent,clientId:environment.NOEMA_GITHUB_APP_CLIENT_ID,
    privateKey:environment.NOEMA_GITHUB_APP_PRIVATE_KEY,fence,controller});
}
module.exports.main=main;
if(require.main===module){
  main().then(status=>{process.exitCode=status;}).catch(()=>{
    // Fixed, credential-free disposition also covers unconfirmed revocation.
    console.error('Noema existing-App issuer refused; issuance or cleanup unconfirmed');process.exitCode=1;
  });
}
