"""Resume the saved pilot without overwriting any run or resetting total budget."""
import json
from pathlib import Path
import subprocess
import sys
import time
import argparse

ROOT=Path('/work')
original=json.loads((ROOT/'results/article-20261001/matrix.json').read_text())
p=argparse.ArgumentParser();p.add_argument('--name',default='article-resume2-20261002');args=p.parse_args()
done=set()
for item in original['plan']:
    for manifest in (ROOT/'runs').glob('article-20261001-'+item['tag']+'*/manifest.json'):
        if json.loads(manifest.read_text()).get('complete'):done.add(item['tag'])
plan=[dict(r) for r in original['plan'] if r['tag'] not in done]
# A documented prospective amendment for robustness pilots, before observing them.
for r in plan:
    if r['seed']==801:r.update(warmup=100,measured=200)
control=dict(tag='honest-capacity70',rho=.5,seed=811,alpha=0,policy='swrr',extra=['--capacity3','70'],warmup=100,measured=200)
plan.insert(next((i for i,r in enumerate(plan) if r['seed']==102),len(plan)),control)
spent=0
for p in (ROOT/'runs').glob('*/manifest.json'):
    m=json.loads(p.read_text())
    spent+=max(0,m.get('finished',m['started'])-m['started'])
deadline=time.time()+max(0,14400-spent-180)
destination=ROOT/'results'/args.name
destination.mkdir(exist_ok=False)
status={'started':time.time(),'deadline':deadline,'previous_active_seconds':spent,
        'complete':False,'runs':[],'plan':plan,
        'amendment':'Continue original primary 200+400 runs. Robustness/control pilots reduced prospectively to 100+200; four-hour cumulative recorded experiment budget, 180s reserve. One retry of a startup failure only.'}
def save(): (destination/'matrix.json').write_text(json.dumps(status,indent=2))
save()
for item in plan:
    estimate=35+300*item['rho']*.3+(item['warmup']+item['measured'])*.5
    if time.time()+estimate>deadline:
        status['stop_reason']='cumulative_budget';break
    for attempt in range(2):
        index=1
        while (ROOT/'runs'/('article-20261001-'+item['tag']+f'-resume{index}')).exists():index+=1
        name='article-20261001-'+item['tag']+f'-resume{index}'
        cmd=[sys.executable,str(ROOT/'scripts/run_lab.py'),'--out','runs/'+name,
             '--deadline',str(deadline),'--ues',str(round(300*item['rho'])+12),
             '--active',str(round(300*item['rho'])),'--capacity','100','--seed',str(item['seed']),
             '--alpha',str(item['alpha']),'--policy',item['policy'],'--warmup',str(item['warmup']),
             '--cycles',str(item['warmup']+item['measured']),'--interval','.01',*item['extra']]
        started=time.time();print('START',name,flush=True)
        with (destination/(name+'.log')).open('w') as log:
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        seconds=time.time()-started
        status['runs'].append(dict(item,name=name,seconds=seconds,exit_code=result.returncode));save()
        if result.returncode==0:break
        if seconds>30 or attempt==1:break
        time.sleep(2)
    if result.returncode:
        status['stop_reason']='failed_run';break
    subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_article.py')],check=True)
    print('DONE',name,round(seconds,1),flush=True)
else:status['complete']=True
status['finished']=time.time();save()
print('STOP',status.get('stop_reason','complete'),flush=True)
