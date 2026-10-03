"""Four isolated worker namespaces, disjoint CPUs, cumulative experiment budget.

All admission and output mutations run on the coordinator thread. Each future
owns one worker, one log and one unique destination. No simultaneous reuse.
"""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import json,subprocess,sys,time

R=Path(__file__).resolve().parents[1]
def docker(*args,check=True):
    return subprocess.run(['docker',*map(str,args)],capture_output=True,text=True,check=check)

# Let the in-flight sequential experiment finish; its scheduler is SIGSTOP'd.
while docker('exec','model5g-runtime','pgrep','-f',r'^/opt/venv/bin/python /work/scripts/run_lab.py ',check=False).returncode==0:
    time.sleep(5)
docker('exec','model5g-runtime','kill','-TERM','36350',check=False)
docker('exec','model5g-runtime','kill','-CONT','36350',check=False)
old=R/'results/article-resume2-20261002/matrix.json'
state=json.loads(old.read_text());state.update(finished=time.time(),stop_reason='handoff_to_isolated_workers')
old.write_text(json.dumps(state,indent=2))
docker('update','--cpuset-cpus','0-3','model5g-runtime')
workers=json.loads((R/'results/workers.json').read_text())
original=json.loads((R/'results/article-20261001/matrix.json').read_text())
done=[];spent=0
for path in (R/'runs').glob('*/manifest.json'):
    m=json.loads(path.read_text());spent+=max(0,m.get('finished',m['started'])-m['started'])
    if m.get('complete'):done.append(path.parent.name)
def finished(tag):return any(name=='article-20261001-'+tag or name.startswith('article-20261001-'+tag+'-') for name in done)
plan=[dict(item,attempt=0) for item in original['plan'] if not finished(item['tag'])]
for item in plan:
    if item['seed']==801:item.update(warmup=100,measured=200)
control=dict(tag='honest-capacity70',rho=.5,seed=811,alpha=0,policy='swrr',extra=['--capacity3','70'],warmup=100,measured=200,attempt=0)
if not finished(control['tag']):plan.insert(next((i for i,r in enumerate(plan) if r['seed']==102),len(plan)),control)
out=R/'results/article-parallel-20261002';out.mkdir(exist_ok=False)
status={'started':time.time(),'complete':False,'previous_active_seconds':spent,'budget_seconds':14400,
        'reserve_seconds':180,'workers':workers,'runs':[],'plan':plan.copy(),
        'amendment':'Remaining pilot runs use four independent network/database namespaces and disjoint four-CPU sets. Budget is cumulative active-run seconds, not four hours per worker. Each new job has a hard per-run deadline. Earlier sequential runs are marked separately.'}
def save(): (out/'matrix.json').write_text(json.dumps(status,indent=2))
save()
def launch(worker,item,allowance):
    name='article-20261001-'+item['tag']+'-parallel'+str(item['attempt']+1)
    cmd=['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],worker['name'],'python',
         '/work/scripts/run_lab.py','--out','runs/'+name,'--deadline',str(time.time()+allowance-5),
         '--ues',str(round(300*item['rho'])+12),'--active',str(round(300*item['rho'])),'--capacity','100',
         '--seed',str(item['seed']),'--alpha',str(item['alpha']),'--policy',item['policy'],
         '--warmup',str(item['warmup']),'--cycles',str(item['warmup']+item['measured']),
         '--interval','.01',*item['extra']]
    started=time.monotonic()
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    return dict(item=item,name=name,worker=worker['name'],seconds=time.monotonic()-started,exit_code=result.returncode)
used=spent;running={};idle=workers.copy();stopped_for_budget=False
with ThreadPoolExecutor(max_workers=len(workers)) as pool:
    while plan or running:
        while plan and idle:
            item=plan[0]
            estimate=35+300*item['rho']*.3+(item['warmup']+item['measured'])*.5
            free=14400-180-used-sum(v[2] for v in running.values())
            if free<estimate:
                if not running:stopped_for_budget=True
                break
            allowance=min(estimate+120,free)
            worker=idle.pop(0);plan.pop(0)
            print('START',worker['name'],item['tag'],flush=True)
            future=pool.submit(launch,worker,item,allowance);running[future]=(worker,item,allowance)
        if not running:break
        finished_futures,_=wait(running,timeout=30,return_when=FIRST_COMPLETED)
        for future in finished_futures:
            worker,item,allowance=running.pop(future);result=future.result();idle.append(worker)
            used+=result['seconds'];status['runs'].append(result);status['active_seconds']=used;save()
            print('DONE',result['name'],result['exit_code'],round(result['seconds'],1),flush=True)
            if result['exit_code'] and item['attempt']==0:
                plan.append(dict(item,attempt=1))
        if finished_futures:
            subprocess.run([sys.executable,str(R/'scripts/evaluate_article.py')],check=True)
status['finished']=time.time();status['complete']=not plan and all(
    any(r['item']['tag']==p['tag'] and r['exit_code']==0 for r in status['runs']) for p in status['plan'])
status['stop_reason']='budget' if stopped_for_budget or plan else ('complete' if status['complete'] else 'failed_runs')
status['unstarted']=plan;save()
subprocess.run([sys.executable,str(R/'scripts/evaluate_article.py')],check=True)
print('MATRIX_STOP',status['stop_reason'],'active_seconds',round(used,1),flush=True)
