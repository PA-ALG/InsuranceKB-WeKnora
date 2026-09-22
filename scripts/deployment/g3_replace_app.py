"""Runs inside the default VM; env/config remain inside VM memory/private files."""
import hashlib, io, json, os, re, subprocess, sys, tarfile, tempfile, time, urllib.request
os.umask(0o077)
inputs=json.load(sys.stdin)
image=inputs['image_id']; head=inputs['source_commit']
assert image.startswith('sha256:') and len(image)==71 and len(head)==40
OLD=inputs['old_app_id']
assert re.fullmatch('[0-9a-f]{64}', OLD)
OLD_IMAGE=inputs['old_image_id']
assert re.fullmatch('sha256:[0-9a-f]{64}', OLD_IMAGE)
NEW=inputs['new_name']
assert re.fullmatch('weknora-g3-830-release-app-[a-z0-9-]+', NEW)
UI='d1f2d21ebe29e20684eea2cafb1f67df3720e97b105b72b78000644670e7bc54'
NETWORK='weknora-g3-830-internal-recovery-02'
def docker(*args, raw=None, timeout=120, check=True):
    result=subprocess.run(['sudo','docker',*args],input=raw,capture_output=True,timeout=timeout)
    if check and result.returncode: raise RuntimeError('docker operation failed: '+args[0])
    return result

def inspect(target, kind='container'):
    return json.loads(docker(kind,'inspect',target).stdout)[0]
def projection(raw):
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
        rows=[]
        for member in archive.getmembers():
            assert member.isfile() or member.isdir(), 'config must contain regular files/directories'
            name=member.name.removeprefix('./').rstrip('/')
            assert not name.startswith('/') and '..' not in name.split('/')
            rows.append((name,member.type.decode(),member.mode,member.uid,member.gid,
                         hashlib.sha256(archive.extractfile(member).read()).hexdigest() if member.isfile() else None))
        return sorted(rows)
old=inspect(OLD); img=inspect(image,'image'); ui=inspect(UI)
assert old['State']['Running'] and old['Image']==OLD_IMAGE and ui['State']['Running']
assert old['Name'].startswith('/weknora-g3-830-release-app-')
assert img['Config']['Labels']['io.insurancekb.app.build-source-head']==head
assert docker('container','inspect',NEW,check=False).returncode!=0
assert old['Config']['User']=='1000:1000' and old['Config']['Entrypoint']==['/app/WeKnora']
assert old['Config']['Cmd'] is None and not old['HostConfig']['PortBindings']
assert set(old['NetworkSettings']['Networks'])=={NETWORK}
assert { (m['Name'],m['Destination'],m['RW']) for m in old['Mounts']}=={
 ('weknora-g3-830-files','/data/files',True),
 ('weknora-g3-830-docreader-tmp','/tmp/docreader',False),
 ('weknora-g3-830-c5-authority','/run/insurancekb/c5',False)}
env=old['Config']['Env']
assert all('\n' not in row and '\r' not in row and '\0' not in row for row in env)
values=dict(row.split('=',1) for row in env)
assert len(values)==len(env) and values.get('AUTO_MIGRATE','').lower()=='false'
reserve=inputs['storage_reserve_bytes']
assert type(reserve) is int and reserve > 0
values['DOCUMENT_STORAGE_MIN_FREE_BYTES']=str(reserve)
env=[key+'='+value for key,value in values.items()]
assert os.statvfs('/var/lib/docker').f_bavail*os.statvfs('/var/lib/docker').f_frsize > reserve
scope_path=inputs['scope_path']
assert re.fullmatch(r'/api/v1/knowledgebase/[0-9a-f-]+/wiki/release-scopes/[0-9a-f-]+/raw/[0-9a-f-]+/current',scope_path)
expected_current=inputs['expected_current']
readiness_attempts=inputs.get('readiness_attempts',45)
assert type(readiness_attempts) is int and 1 <= readiness_attempts <= 45
token=inputs['access_token']
assert isinstance(token,str) and token and '\n' not in token
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise RuntimeError('redirect denied')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def ready(address,port):
    with opener.open('http://'+address+':'+str(port)+'/health',timeout=3) as response:
        if response.status!=200 or json.load(response)!={'status':'ok'}: return False
    request=urllib.request.Request('http://'+address+':'+str(port)+scope_path,headers={'Authorization':'Bearer '+token})
    with opener.open(request,timeout=8) as response:
        body=json.load(response)
        return response.status==200 and body.get('data',body)==expected_current
def read_ui_file(path):
    return docker('exec',UI,'cat',path).stdout
def write_ui_file(path,content):
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as tar:
        item=tarfile.TarInfo(os.path.basename(path));item.size=len(content);item.mode=0o644
        tar.addfile(item,io.BytesIO(content))
    docker('cp','-',UI+':'+os.path.dirname(path),raw=archive.getvalue())
template_path='/etc/nginx/templates/default.conf.template'
config_path='/etc/nginx/conf.d/default.conf'
old_template=read_ui_file(template_path);old_ui_config=read_ui_file(config_path)
template=inputs['nginx_template'].replace('${APP_HOST}',NEW)
max_size=re.search(rb'client_max_body_size\s+([^;]+);',old_ui_config).group(1).decode()
ui_values=dict(row.split('=',1) for row in ui['Config']['Env'])
rendered=template.replace('${MAX_FILE_SIZE}',max_size).replace('${APP_SCHEME}',ui_values.get('APP_SCHEME','http')).replace('${APP_PORT}',ui_values.get('APP_PORT','8080')).encode()
assert '${' not in rendered.decode()
config=docker('cp',OLD+':/app/config/.','-').stdout
config_projection=projection(config)
state={'status':'PREPARED','old_app_id':OLD,'old_image_id':OLD_IMAGE,'new_image_id':image,
       'source_commit':head,'explicit_database_mutations':0,'explicit_provider_requests':0,
       'background_effects':'NOT_MEASURED','old_container_preserved':True}
new_id=None; switched=False; retired=False
fd,path=tempfile.mkstemp(prefix='g3-product-app-env-')
try:
    with os.fdopen(fd,'w') as stream: stream.write('\n'.join(env)+'\n')
    host=old['HostConfig']
    args=['create','--name',NEW,'--pull','never','--network',NETWORK,
          '--restart','no','--user','1000:1000','--entrypoint','/app/WeKnora',
          '--cpus',str(host['NanoCpus']/1e9),'--memory',str(host['Memory']),
          '--memory-swap',str(host['MemorySwap']),'--pids-limit',str(host['PidsLimit']),
          '--shm-size',str(host['ShmSize']),'--cap-drop','ALL','--security-opt','no-new-privileges',
          '--label','goal=830-g3','--label','role=release-app',
          '--mount','type=volume,source=weknora-g3-830-files,target=/data/files',
          '--mount','type=volume,source=weknora-g3-830-docreader-tmp,target=/tmp/docreader,readonly',
          '--mount','type=volume,source=weknora-g3-830-c5-authority,target=/run/insurancekb/c5,readonly',
          '--env-file',path,image]
    new_id=docker(*args).stdout.decode().strip()
    state['new_app_id']=new_id
    docker('cp','-a','-',new_id+':/app/config',raw=config)
    assert projection(docker('cp',new_id+':/app/config/.','-').stdout)==config_projection
    created=inspect(new_id)
    assert created['Image']==image and created['Config']['User']=='1000:1000'
    assert created['Config']['Cmd'] is None and created['Config']['Entrypoint']==['/app/WeKnora']
    assert sorted(created['Config']['Env'])==sorted(env)
    # The new hostname is private. The current UI keeps routing to the old app.
    docker('start',new_id)
    healthy=False
    for _ in range(readiness_attempts):
        row=inspect(new_id)
        if not row['State']['Running']: break
        address=row['NetworkSettings']['Networks'][NETWORK]['IPAddress']
        try:
            healthy=ready(address,8080)
            if healthy: break
        except Exception: pass
        time.sleep(2)
    assert healthy, 'new APP failed authenticated business readiness'
    state['business_ready_before_cutover']=True
    assert inspect(OLD)['State']['Running']
    switched=True
    write_ui_file(template_path,template.encode())
    write_ui_file(config_path,rendered)
    docker('exec',UI,'nginx','-t')
    docker('exec',UI,'nginx','-s','reload')
    ui_address=ui['NetworkSettings']['Networks'][NETWORK]['IPAddress']
    serving=False
    for _ in range(10):
        try:
            serving=ready(ui_address,80)
            if serving:break
        except Exception:pass
        time.sleep(1)
    assert serving,'new UI route failed business readiness'
    retired=True
    docker('stop','--time','30',OLD)
    docker('network','disconnect',NETWORK,OLD)
    state.update(status='REPLACED',health=True,
        config_tree_sha256=hashlib.sha256(json.dumps(config_projection,separators=(',',':')).encode()).hexdigest(),
        ui_restarted=False,ui_configuration_sha256=hashlib.sha256(rendered).hexdigest(),
        ui_template_sha256=hashlib.sha256(template.encode()).hexdigest(),
        old_stopped_after_serving_ready=True,storage_reserve_bytes=reserve)
except BaseException as exc:
    state.update(status='FAILED',failure_type=type(exc).__name__)
    if retired:
        if NETWORK not in inspect(OLD)['NetworkSettings']['Networks']:
            docker('network','connect','--alias','app-g3',NETWORK,OLD)
        docker('start',OLD)
    if switched:
        write_ui_file(template_path,old_template)
        write_ui_file(config_path,old_ui_config)
        docker('exec',UI,'nginx','-t')
        docker('exec',UI,'nginx','-s','reload')
    if new_id:
        docker('stop','--time','20',new_id,check=False)
        docker('network','disconnect',NETWORK,new_id,check=False)
    state['rollback']='OLD_APP_PRESERVED_OR_RESTORED'
    print(json.dumps(state),flush=True)
    raise SystemExit(1)
finally:
    os.unlink(path)
print(json.dumps(state),flush=True)
