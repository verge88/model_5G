"""Provision three isolated copies of the existing laboratory, without host ports."""
from pathlib import Path
import subprocess,json
R=Path(__file__).resolve().parents[1]
def call(*args):return subprocess.check_output(['docker',*map(str,args)],text=True).strip()
payload=R/'tmp/worker-payload';payload.mkdir(parents=True,exist_ok=True)
for source in ['/opt/model5g-patched','/build/model5g-ueransim/build','/build/model5g-ueransim/config']:
    subprocess.run(['docker','cp','model5g-runtime:'+source,str(payload)],check=True)
workers=[{'name':'model5g-runtime','cpus':'0-3'}]
for i,cpus in [(2,'4-7'),(3,'8-11'),(4,'12-15')]:
    database=f'model5g-db{i}';worker=f'model5g-worker{i}'
    existing=call('ps','-a','--format','{{.Names}}').splitlines()
    if database in existing or worker in existing:raise RuntimeError('Refusing to reuse an unknown existing worker')
    call('run','-d','--name',database,'--label','model5g.article=20261002','mongo:7.0','mongod','--bind_ip','127.0.0.1')
    call('run','-d','--name',worker,'--label','model5g.article=20261002',
         '--network','container:'+database,'--cap-add','NET_ADMIN','--cpuset-cpus',cpus,
         '--mount','type=bind,source='+str(R)+',target=/work','--entrypoint','sleep','model5g-lab:v2.8.0','infinity')
    for name,target in [('model5g-patched','/opt/model5g-patched'),('build','/build/model5g-ueransim/build'),('config','/build/model5g-ueransim/config')]:
        call('cp',str(payload/name)+'/.',worker+':'+target)
    call('exec',worker,'python','-c','import yaml,h2,pymongo; print("runtime dependencies ready")')
    workers.append({'name':worker,'cpus':cpus,'database':database})
(R/'results/workers.json').write_text(json.dumps(workers,indent=2))
print(json.dumps(workers,indent=2))
