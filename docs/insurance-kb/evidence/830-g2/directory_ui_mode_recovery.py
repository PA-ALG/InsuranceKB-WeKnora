"""One frozen frontend build and one isolated G2 UI replacement; no model calls."""
import argparse, hashlib, json, os, pathlib, re, subprocess, sys, time, urllib.request
if sys.flags.optimize: raise RuntimeError('Optimized Python forbidden')
os.umask(0o077)
R=pathlib.Path('/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g2-concept-free-wiki')
P=pathlib.Path('/private/tmp/weknora-g2-594'); E=R/'docs/insurance-kb/evidence/830-g2'
ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['build','upgrade'],required=True);ap.add_argument('--head',required=True);args=ap.parse_args()
assert re.fullmatch('[0-9a-f]{40}',args.head)
def command(argv, **kw):
 r=subprocess.run(argv,capture_output=True,**kw)
 if r.returncode:
  (P/'directory-ui-mode-error.private.log').write_bytes(r.stdout+r.stderr)
  raise RuntimeError('Command failed; private diagnostic retained')
 return r.stdout
def docker(*argv):return command(['colima','ssh','--profile','default','--','sudo','docker',*argv])
def inspect(name):return json.loads(docker('inspect',name))[0]
def builder(*argv):return command(['docker','--context','colima-g1-build',*argv])
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def guard():
 assert command(['git','rev-parse','HEAD'],cwd=R).decode().strip()==args.head
 assert not command(['git','status','--porcelain','--','frontend'],cwd=R).strip()
def dist_digest():
 files=sorted(p for p in (R/'frontend/dist').rglob('*') if p.is_file())
 assert files and (R/'frontend/dist/index.html').is_file()
 return hashlib.sha256(b''.join(str(p.relative_to(R/'frontend/dist')).encode()+b'\0'+hashlib.sha256(p.read_bytes()).digest() for p in files)).hexdigest()
guard()
plan_raw=(E/'directory-ui-mode-recovery-plan.json').read_bytes();plan=json.loads(plan_raw)
assert plan['source_head']==args.head and plan['status']=='REGISTERED'
review=json.loads((E/'directory-ui-mode-recovery-review.json').read_text())
assert review['blockers']==0 and review['source_head']==args.head
assert review['script_sha256']==hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
assert review['plan_sha256']==hashlib.sha256(plan_raw).hexdigest()
artifact_path=E/'directory-frontend-mode-recovery-artifact.json'
def mode_manifest():
 entries=[R/'frontend/dist']+sorted((R/'frontend/dist').rglob('*'))
 assert not any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in entries)
 return {str(p.relative_to(R/'frontend/dist')):oct(p.stat().st_mode & 0o777) for p in entries}
def mode_guard():
 modes=mode_manifest()
 assert all(mode==('0o755' if (R/'frontend/dist'/name).is_dir() else '0o644') for name,mode in modes.items())
 return hashlib.sha256(json.dumps(modes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
if args.phase=='build':
 state=P/'directory-ui-mode-build-state.json';assert not state.exists() and not artifact_path.exists()
 assert dist_digest()==plan['dist_content_sha256']
 before=mode_manifest();write(P/'directory-ui-modes-before.json',before)
 v={'status':'STARTED','source_head':args.head,'static_builds':0,'image_builds':0,'provider_calls':0,'modes_before_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()};write(state,v)
 for name in before:
  target=R/'frontend/dist'/name;target.chmod(0o755 if target.is_dir() else 0o644)
 mode_sha=mode_guard();assert dist_digest()==plan['dist_content_sha256']
 write(P/'directory-ui-modes-after.json',mode_manifest())
 dist=dist_digest();tag='weknora-ui:g2-mode-'+args.head[:12]
 labels={'io.insurancekb.g2.frontend.source-head':args.head,'io.insurancekb.g2.frontend.dist-sha256':dist}
 argv=['docker','--context','colima-g1-build','build','--platform','linux/arm64']
 for k,value in labels.items():argv+=['--label',k+'='+value]
 argv+=['-f','frontend/Dockerfile','-t',tag,'frontend/']
 v.update(image_builds=1,dist_sha256=dist,modes_after_sha256=mode_sha);write(state,v)
 with (P/'directory-ui-mode-image-build.log').open('wb') as log:
  result=subprocess.run(argv,cwd=R,stdout=log,stderr=subprocess.STDOUT)
 assert result.returncode==0,'Image-only recovery build failed; inspect retained log'
 image=json.loads(builder('image','inspect',tag))[0];guard();assert dist_digest()==dist and mode_guard()==mode_sha
 assert image['Architecture']=='arm64' and image['Os']=='linux'
 assert all(image['Config']['Labels'].get(k)==value for k,value in labels.items())
 v.update(status='PASS',contract='830-g2-directory-frontend-mode-artifact.v1',image_id=image['Id'],labels=labels,platform='linux/arm64')
 write(state,v);write(artifact_path,v);print(json.dumps(v));sys.exit(0)
artifact_raw=artifact_path.read_bytes();a=json.loads(artifact_raw)
assert a['status']=='PASS' and a['source_head']==args.head and a['static_builds']==0 and a['image_builds']==1
assert a['contract']=='830-g2-directory-frontend-mode-artifact.v1' and a['platform']=='linux/arm64'
assert re.fullmatch('[0-9a-f]{64}',a['dist_sha256']) and dist_digest()==a['dist_sha256']
expected_labels={'io.insurancekb.g2.frontend.source-head':args.head,'io.insurancekb.g2.frontend.dist-sha256':a['dist_sha256']}
assert a['labels']==expected_labels and mode_guard()==a['modes_after_sha256']
image_id=a['image_id'];assert re.fullmatch('sha256:[0-9a-f]{64}',image_id)
state=P/'directory-ui-mode-upgrade-state.json';assert not state.exists()
name='weknora-g2-594-ui';backup='weknora-g2-594-ui-before-mode-recovery'
old=inspect(name);app=inspect('weknora-g2-594-app')
assert app['Image']=='sha256:600a5a1cf93f4d2ecbe5466b7733c8d82395cdcad99fb501fb50ddf224220b19' and app['State']['Running']
assert old['Image']=='sha256:a22aa7feb2ac810144aebecdfa3dfdca2af052c760615a8bf8eadf8a1ad459f1' and old['State']['Running']
assert old['Mounts']==[] and old['HostConfig']['PortBindings']=={'80/tcp':[{'HostIp':'127.0.0.1','HostPort':'18195'}]}
assert old['HostConfig']['RestartPolicy']['Name']=='no' and not old['HostConfig']['Privileged']
assert not old['HostConfig'].get('CapAdd') and not old['HostConfig'].get('Devices')
networks={'weknora-g2-594-internal','weknora-g2-594-egress'}
assert set(old['NetworkSettings']['Networks'])==networks
env=dict(s.split('=',1) for s in old['Config']['Env'])
expected={'APP_HOST':'weknora-g2-594-app','APP_PORT':'8080','APP_SCHEME':'http','SCHEMA_WIKI_MVP_ENTRY_KB_ID':'b1f1764c-443d-46b8-98e3-d5aa5e55eb42','SCHEMA_WIKI_MVP_SERVING_KB_ID':'8d5695de-f255-42d5-9a41-042ba86e97b9'}
assert all(env.get(k)==value for k,value in expected.items())
assert backup not in docker('ps','-a','--format','{{.Names}}').decode().splitlines()
auth=json.loads((P/'auth.private.json').read_text())
url='http://127.0.0.1:18195/api/v1/knowledgebase/8d5695de-f255-42d5-9a41-042ba86e97b9/wiki/release-scopes/a8751a40-83ce-55c8-a160-079b283483ca/raw/b1f1764c-443d-46b8-98e3-d5aa5e55eb42/current'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def head():
 with opener.open(urllib.request.Request(url,headers={'Authorization':'Bearer '+auth['token']}),timeout=60) as resp:
  assert resp.status==200;return json.load(resp)['data']
expected_head={'release_id':'release-0236279f-df73-4433-bebc-cad70f95b989','activation_epoch':4}
assert head()==expected_head
v={'status':'STARTED','source_head':args.head,'artifact_sha256':hashlib.sha256(artifact_raw).hexdigest(),'image_id':image_id,'previous_container_id':old['Id'],'provider_calls':0,'steps':[]}
def save(step):v['steps'].append(step);write(state,v);print(step,flush=True)
save('Old UI identity, isolated app and active release guards PASS')
archive=P/'directory-ui-mode-image.tar';assert not archive.exists()
builder('image','save','-o',str(archive),image_id)
with archive.open('rb') as stream:
 result=subprocess.run(['colima','ssh','--profile','default','--','sudo','docker','load'],stdin=stream,capture_output=True)
assert result.returncode==0,'Image load failed; archive retained'
loaded=json.loads(docker('image','inspect',image_id))[0]
assert loaded['Id']==image_id and loaded['Architecture']=='arm64' and loaded['Os']=='linux'
assert {k:value for k,value in loaded['Config']['Labels'].items() if k.startswith('io.insurancekb.g2.frontend.')}==expected_labels
guard();assert dist_digest()==a['dist_sha256'] and mode_guard()==a['modes_after_sha256'] and head()==expected_head
save('Frozen UI image transferred and checked')
docker('stop',name);docker('rename',name,backup);save('Old UI preserved for rollback')
argv=['create','--pull=never','--restart=no','--name',name,'--label','goal=830-g2','--network','weknora-g2-594-internal','-p','127.0.0.1:18195:80']
for k,value in expected.items():argv+=['-e',k+'='+value]
docker(*argv,image_id);docker('network','connect','weknora-g2-594-egress',name);docker('start',name)
save('Replacement UI started on existing loopback port')
healthy=False
for _ in range(20):
 try:
  with opener.open('http://127.0.0.1:18195/',timeout=5) as resp:
   body=resp.read();healthy=resp.status==200 and b'<html' in body.lower()
  if healthy:break
 except OSError:pass
 time.sleep(1)
assert healthy,'UI not healthy; state retained, no automatic rollback or retry'
new=inspect(name);assert new['Image']==image_id and new['Mounts']==[]
assert new['HostConfig']['PortBindings']==old['HostConfig']['PortBindings'] and set(new['NetworkSettings']['Networks'])==networks
assert head()==expected_head and inspect('weknora-g2-594-app')['Id']==app['Id']
v.update(status='PASS',container_id=new['Id'],head=expected_head,index_http=200,index_sha256=hashlib.sha256(body).hexdigest(),browser_verification='NOT_RUN')
save('UI identity, index and same active release PASS')
write(E/'directory-ui-mode-upgrade-receipt.json',v)
