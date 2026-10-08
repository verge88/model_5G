"""Independent calibration followed by a fixed weak-attack validation matrix."""
import concurrent.futures as cf
import csv
import ctypes
import hashlib
import json
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from evaluate_article import audit, quantile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'results/detector-v1'
MODELS = ['residual', 'residual_quantized', 'nrf_only', 'scp_only', 'nrf_scp', 'full_peer']

def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)

def plan():
    return [dict(stage='cal', policy='swrr', rho=r, seed=s, alpha=0)
            for s in [201,202,203] for r in [.2,.5,.7]] + [
            dict(stage='weak', policy=p, rho=r, seed=s, alpha=.25)
            for s in [301,302,303] for p in ['swrr','random'] for r in [.2,.5,.7]]

def selected_main():
    ledger = json.loads((ROOT/'results/main-v2-execution/ledger.json').read_text())
    pairs = [r for r in ledger['results'] if r['eligible_pair'] and r['item']['series_id']=='main-v2']
    if len(pairs)!=30: raise RuntimeError('Expected 30 completed main pairs')
    return {v['name']:v['audit'] for r in pairs for v in r['records']}

def check_build(result):
    reference = next(iter(selected_main().values()))
    for key in ['binary_sha256','sbi_library_sha256','ueransim_sha256','rls_heartbeat_threshold_ms','warmup','cycles','capacity']:
        if result.get(key)!=reference.get(key): raise RuntimeError('Incompatible measurement: '+key)

def execute(item, worker, attempt, state_dir=None, series='detector-v1'):
    state_dir = STATE if state_dir is None else state_dir
    name = f"{series}-{item['stage']}-{item['policy']}-r{round(item['rho']*100)}-s{item['seed']}-a{round(item['alpha']*100)}-attempt{attempt}"
    destination = ROOT/'runs'/name
    start = time.time()
    if not destination.exists():
        info = json.loads(subprocess.check_output(['docker','inspect',worker['name']],text=True))[0]['HostConfig']
        if info['CpusetCpus']!=worker['cpus']: raise RuntimeError('CPU allocation mismatch')
        resource = {k:info.get(k) for k in ['CpusetCpus','Memory','NanoCpus','CpuQuota','CpuPeriod']}
        digest = hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest()
        cmd = ['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],
               '-e','LAB_RESOURCE_CONFIGURATION='+digest,worker['name'],'python','/work/scripts/run_lab.py',
               '--out','runs/'+name,'--series-id',series,'--compact-storage',
               '--deadline',str(time.time()+3600),'--policy',item['policy'],'--seed',str(item['seed']),
               '--active',str(round(300*item['rho'])),'--ues',str(round(300*item['rho'])+12),
               '--capacity','100','--reported-capacity','100','--alpha',str(item['alpha']),
               '--warmup','300','--cycles','3300','--interval','.01']
        cmd += item.get('extra',[])
        with (state_dir/(name+'.log')).open('w') as stream:
            result = subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode: return dict(item=item,name=name,eligible=False,error='runner_exit_'+str(result.returncode))
    result, features = audit(destination)
    check_build(result)
    if not features: raise RuntimeError('No detector windows')
    write(state_dir/(name+'.features.json'),features)
    return dict(item=item,name=name,eligible=result['eligible'],seconds=time.time()-start,audit=result)

def freeze(state):
    path = STATE/'thresholds.json'
    cal = [r for r in state['results'] if r['eligible'] and r['item']['stage']=='cal']
    if len(cal)!=9: raise RuntimeError('Calibration incomplete')
    if path.exists():
        frozen=json.loads(path.read_text())
        if sorted(frozen['calibration_runs'])!=sorted(r['name'] for r in cal): raise RuntimeError('Frozen calibration changed')
        return frozen
    features=[f for r in cal for f in json.loads((STATE/(r['name']+'.features.json')).read_text())]
    frozen=dict(created=time.time(),calibration_runs=[r['name'] for r in cal],
                primary='residual',quantile=.99,comparison='strictly_greater',
                thresholds={m:quantile([f[m] for f in features],.99) for m in MODELS})
    write(path,frozen)
    return frozen

def evaluate(state):
    frozen=freeze(state); main=selected_main()
    with (ROOT/'results/main-v2-execution/main-evaluation/features.csv').open() as stream:
        features=[dict(f,cohort='main') for f in csv.DictReader(stream) if f['run'] in main]
    for r in state['results']:
        if r['eligible'] and r['item']['stage']=='weak':
            features += [dict(f,cohort='weak') for f in json.loads((STATE/(r['name']+'.features.json')).read_text())]
    summaries=[]; by_run=[]
    for model in MODELS:
        for run in sorted({f['run'] for f in features}):
            rows=[f for f in features if f['run']==run]; f=rows[0]
            alarms=sum(float(v[model])>frozen['thresholds'][model] for v in rows)
            by_run.append(dict(model=model,run=run,cohort=f['cohort'],policy=f['policy'],rho=float(f['rho']),
                               alpha=float(f['alpha']),windows=len(rows),alarms=alarms,alarm_fraction=alarms/len(rows)))
    for model,cohort,policy,rho,alpha in sorted({(r['model'],r['cohort'],r['policy'],r['rho'],r['alpha']) for r in by_run}):
        rows=[r for r in by_run if (r['model'],r['cohort'],r['policy'],r['rho'],r['alpha'])==(model,cohort,policy,rho,alpha)]
        values=[r['alarm_fraction'] for r in rows]; rng=random.Random(731)
        samples=[statistics.mean(rng.choices(values,k=len(values))) for _ in range(5000)]
        summaries.append(dict(model=model,cohort=cohort,policy=policy,rho=rho,alpha=alpha,runs=len(rows),
                              mean_run_alarm_fraction=statistics.mean(values),low=quantile(samples,.025),high=quantile(samples,.975)))
    write(STATE/'evaluation.json',dict(thresholds=frozen,by_run=by_run,summary=summaries,
          limitations=['Retrospective main-series evaluation; weak attacks are prospective.',
                       'Window alarm fractions, not independent-window inference or alarm-episode rates.',
                       'Few independent runs; exploratory run bootstrap.',
                       'Attack onset latency and changing attacks require a separate stage.']))

def main():
    STATE.mkdir(exist_ok=True)
    lock=STATE/'controller.lock'
    with lock.open('x') as stream: stream.write(str(__import__('os').getpid()))
    state=json.loads((STATE/'ledger.json').read_text()) if (STATE/'ledger.json').exists() else dict(results=[])
    workers=json.loads((ROOT/'results/workers.json').read_text())
    try:
        if sys.platform=='win32' and not ctypes.windll.kernel32.SetThreadExecutionState(0x80000001):
            raise RuntimeError('Cannot prevent idle sleep')
        state.update(status='running',error=None)
        for stage in ['cal','weak']:
            pending=[i for i in plan() if i['stage']==stage and not any(r['item']==i and r['eligible'] for r in state['results'])]
            idle=list(workers);running={};failure=False
            with cf.ThreadPoolExecutor(max_workers=4) as pool:
                while pending or running:
                    paused=(STATE/'pause-request.json').exists()
                    while pending and idle and not failure and not paused:
                        if shutil.disk_usage(ROOT).free<3*1024**3: failure=True;state['error']='low_disk';break
                        item=pending.pop(0);worker=idle.pop(0)
                        attempt=1+sum(r['item']==item for r in state['results'])
                        running[pool.submit(execute,item,worker,attempt)]=(item,worker)
                        print('START',worker['name'],item,flush=True)
                    state.update(stage=stage,updated_at=time.time(),pending=pending,
                                 in_flight=[dict(item=i,worker=w['name']) for i,w in running.values()])
                    write(STATE/'ledger.json',state)
                    if not running: break
                    done,_=cf.wait(running,timeout=20,return_when=cf.FIRST_COMPLETED)
                    for future in done:
                        item,worker=running.pop(future);idle.append(worker)
                        try: result=future.result()
                        except Exception as error: result=dict(item=item,eligible=False,error=repr(error))
                        state['results'].append(result)
                        print('DONE',item,result['eligible'],flush=True)
                        if not result['eligible']:failure=True;state['error']=result.get('error','audit_failure')
            if failure or (STATE/'pause-request.json').exists():
                state['status']='failed' if failure else 'paused';return
            freeze(state)
            evaluate(state)
        state['status']='complete'
    except Exception as error:
        state.update(status='failed',error=repr(error));raise
    finally:
        state.update(updated_at=time.time(),in_flight=[]);write(STATE/'ledger.json',state)
        subprocess.run(['docker','stop']+[w['name'] for w in workers]+['model5g-db','model5g-db2','model5g-db3','model5g-db4'])
        if sys.platform=='win32':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lock.unlink(missing_ok=True)

if __name__=='__main__':main()
