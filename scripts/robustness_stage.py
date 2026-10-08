"""Fixed detector robustness matrix using the frozen detector-v1 thresholds."""
import concurrent.futures as cf
import ctypes
import hashlib
import json
import shutil
import statistics
import random
import subprocess
import sys
import time
from pathlib import Path
from detector_stage import execute, write, MODELS
from evaluate_article import quantile

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/robustness-v1'
SERIES='robustness-v1'

def plan():
    scenarios=[('honest-hb5',0,['--heartbeat','5']),
               ('attack-hb5',.25,['--heartbeat','5']),
               ('honest-cap70',0,['--capacity3','70']),
               ('attack-onoff',.25,['--attack-mode','onoff'])]
    return [dict(stage=tag,policy=policy,rho=.5,seed=seed,alpha=alpha,extra=extra)
            for seed in [401,402,403] for tag,alpha,extra in scenarios for policy in ['swrr','random']]

def summarize(state):
    frozen=json.loads((STATE/'frozen-thresholds.json').read_text())
    results=[]
    for run in state['results']:
        if not run['eligible']:continue
        features=json.loads((STATE/(run['name']+'.features.json')).read_text())
        for model in MODELS:
            alarms=sum(f[model]>frozen['thresholds'][model] for f in features)
            results.append(dict(run=run['name'],scenario=run['item']['stage'],policy=run['item']['policy'],
                seed=run['item']['seed'],model=model,windows=len(features),alarms=alarms,
                alarm_fraction=alarms/len(features)))
    write(STATE/'evaluation.json',dict(by_run=results,thresholds=frozen,
        interpretation='On/off alarm fraction mixes active and inactive attack periods; it is not detection probability.',
        limitations=['No network delivery-delay injection; heartbeat scenario changes update frequency.',
                     'Attack onset latency requires event-level evaluation.',
                     'Three independent seeds per scenario; exploratory robustness evidence.']))
    if SERIES=='quantization-v1':
        cells=[]
        for policy in ['swrr','random']:
            for scenario in ['honest-cap70','attack-cap70']:
                values=[r['alarm_fraction'] for r in results if r['model']=='residual_quantized'
                        and r['policy']==policy and r['scenario']==scenario]
                if not values:continue
                rng=random.Random(731)
                boot=[statistics.mean(rng.choices(values,k=len(values))) for _ in range(5000)]
                mean=statistics.mean(values)
                cells.append(dict(policy=policy,scenario=scenario,runs=len(values),mean=mean,
                    exploratory_low=quantile(boot,.025),exploratory_high=quantile(boot,.975),
                    decision='incomplete' if len(values)!=3 else
                    ('pass' if (mean<=.01 if scenario=='honest-cap70' else mean>=.95) else 'fail')))
        write(STATE/'acceptance.json',dict(primary='residual_quantized',cells=cells,
            complete=len(cells)==4 and all(c['runs']==3 for c in cells),
            note='Empirical predeclared acceptance; three-run bootstrap is exploratory, not an error-rate guarantee.'))

def main():
    STATE.mkdir(exist_ok=True)
    if (STATE/'pause-request.json').exists():raise RuntimeError('Pause request active')
    lock=STATE/'controller.lock'
    with lock.open('x') as stream:stream.write(str(__import__('os').getpid()))
    workers=json.loads((ROOT/'results/workers.json').read_text())
    state=json.loads((STATE/'ledger.json').read_text()) if (STATE/'ledger.json').exists() else dict(results=[])
    try:
        source=(ROOT/'results/detector-v1/thresholds.json').read_bytes()
        frozen=STATE/'frozen-thresholds.json'
        if frozen.exists() and frozen.read_bytes()!=source:raise RuntimeError('Calibration thresholds changed')
        if not frozen.exists():frozen.write_bytes(source)
        write(STATE/'plan.json',dict(items=plan(),thresholds_sha256=hashlib.sha256(source).hexdigest(),
             runner_sha256=hashlib.sha256((ROOT/'scripts/run_lab.py').read_bytes()).hexdigest()))
        if sys.platform=='win32' and not ctypes.windll.kernel32.SetThreadExecutionState(0x80000001):
            raise RuntimeError('Cannot prevent idle sleep')
        pending=[i for i in plan() if not any(r['item']==i and r['eligible'] for r in state['results'])]
        state.update(status='running',error=None)
        idle=list(workers);running={};failed=False
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            while pending or running:
                paused=(STATE/'pause-request.json').exists()
                while pending and idle and not failed and not paused:
                    if shutil.disk_usage(ROOT).free<3*1024**3:failed=True;state['error']='low_disk';break
                    item=pending.pop(0);worker=idle.pop(0)
                    attempt=1+sum(r['item']==item for r in state['results'])
                    running[pool.submit(execute,item,worker,attempt,STATE,SERIES)]=(item,worker)
                    print('START',worker['name'],item,flush=True)
                state.update(updated_at=time.time(),pending=pending,
                    in_flight=[dict(item=i,worker=w['name']) for i,w in running.values()])
                write(STATE/'ledger.json',state)
                if not running:break
                done,_=cf.wait(running,timeout=20,return_when=cf.FIRST_COMPLETED)
                for future in done:
                    item,worker=running.pop(future);idle.append(worker)
                    try:result=future.result()
                    except Exception as error:result=dict(item=item,eligible=False,error=repr(error))
                    state['results'].append(result)
                    print('DONE',item,result['eligible'],flush=True)
                    if not result['eligible']:failed=True;state['error']=result.get('error','audit_failure')
                    summarize(state)
        state['status']='failed' if failed else ('paused' if (STATE/'pause-request.json').exists() else 'complete')
    except Exception as error:
        state.update(status='failed',error=repr(error));raise
    finally:
        state.update(updated_at=time.time(),in_flight=[]);write(STATE/'ledger.json',state)
        subprocess.run(['docker','stop']+[w['name'] for w in workers]+['model5g-db','model5g-db2','model5g-db3','model5g-db4'])
        if sys.platform=='win32':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lock.unlink(missing_ok=True)

if __name__=='__main__':main()
