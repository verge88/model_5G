"""Whole-pair admission with live user budget control and separate study stages."""
import argparse, hashlib, json, random, shutil, subprocess, time, sys, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from evaluate_article import audit, matched_experimental_conditions
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'
BUDGET=43200

def budget_limit():
    control=STATE/'budget-control.json'
    if control.exists() and json.loads(control.read_text()).get('unlimited') is True:
        return None
    return BUDGET

def handoff_ready(state):
    return not state.get('failure') and all(
        any(r['item']==entry['item'] and r['eligible_pair'] for r in state['results'])
        for entry in state.get('in_flight',[]))

def plan(phase):
    if phase=='pilot':cells=[('swrr',.2,101),('random',.2,103)];warmup=200;cycles=600;series='pilot-closeout-v2'
    elif phase=='prep':cells=[('swrr',.7,9001),('random',.7,9001)];warmup=300;cycles=3300;series='main-v2-preparation'
    else:
        gate=json.loads((STATE/'warmup-decision.json').read_text())
        if not gate['accepted']:raise RuntimeError('Preparation gate not accepted')
        if phase=='confirmation':
            selected=json.loads((STATE/'confirmation-plan.json').read_text())
            return [dict(policy=c['policy'],rho=c['rho'],seed=s,warmup=gate['warmup'],
                         cycles=gate['warmup']+3000,series_id='main-v2-confirmation')
                    for c in selected for s in c['seeds']]
        cells=[];rng=random.Random(20261003)
        for seed in range(101,106):
            block=[(p,r,seed) for p in ['swrr','random'] for r in [.2,.5,.7]]
            rng.shuffle(block);cells+=block
        warmup=gate['warmup'];cycles=warmup+3000;series='main-v2'
    return [dict(policy=p,rho=r,seed=s,warmup=warmup,cycles=cycles,series_id=series) for p,r,s in cells]

def save(state):
    state['updated_at']=time.time()
    state['controller_pid']=os.getpid()
    temp=STATE/'ledger.tmp';temp.write_text(json.dumps(state,indent=2));temp.replace(STATE/'ledger.json')

def execute(item,worker,allowance,attempt):
    started=time.monotonic();records=[]
    info=json.loads(subprocess.check_output(['docker','inspect',worker['name']],text=True))[0]
    if info['HostConfig']['CpusetCpus']!=worker['cpus']:raise RuntimeError('CPU allocation changed')
    resource={k:info['HostConfig'].get(k) for k in ['CpusetCpus','Memory','NanoCpus','CpuQuota','CpuPeriod']}
    resource_hash=hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest()
    for index,alpha in enumerate([0,.5] if item['seed']%2==0 else [.5,0]):
        name=f"{item['series_id']}-{item['policy']}-r{round(item['rho']*100)}-s{item['seed']}-a{int(alpha*100)}-attempt{attempt}"
        remaining=allowance-(time.monotonic()-started)
        cmd=['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],
             '-e','LAB_RESOURCE_CONFIGURATION='+resource_hash,worker['name'],'python','/work/scripts/run_lab.py',
             '--out','runs/'+name,'--series-id',item['series_id'],'--compact-storage',
             '--deadline',str(time.time()+remaining/(2-index)-30),
             '--policy',item['policy'],'--seed',str(item['seed']),
             '--active',str(round(300*item['rho'])),'--ues',str(round(300*item['rho'])+12),
             '--capacity','100','--reported-capacity','100','--alpha',str(alpha),
             '--warmup',str(item['warmup']),'--cycles',str(item['cycles']),'--interval','.01']
        begin=time.monotonic()
        with (STATE/(name+'.log')).open('w') as stream:
            completed=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT)
        record=dict(name=name,exit_code=completed.returncode,seconds=time.monotonic()-begin);records.append(record)
        manifest=ROOT/'runs'/name/'manifest.json'
        if completed.returncode or not manifest.exists():break
        record['audit'],_=audit(manifest.parent)
        if not record['audit']['eligible']:break
    valid=len(records)==2 and all(r.get('audit',{}).get('eligible') for r in records)
    if valid:
        a,b=[r['audit'] for r in records]
        valid=matched_experimental_conditions(a,b) and a['workload_hash']==b['workload_hash']
    return dict(item=item,worker=worker['name'],resource=resource,attempt=attempt,records=records,
                eligible_pair=valid,seconds=time.monotonic()-started)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['pilot','prep','main','confirmation'],required=True)
    parser.add_argument('--launch',action='store_true')
    parser.add_argument('--handoff',action='store_true');args=parser.parse_args()
    items=plan(args.phase)
    if not args.launch:print(json.dumps(items,indent=2));return
    if (STATE/'pause-request.json').exists():
        raise SystemExit('Experiment paused by user. Explicit resume must archive the pause request first.')
    STATE.mkdir(exist_ok=True)
    lock=STATE/'controller.lock'
    if args.handoff:
        state=json.loads((STATE/'ledger.json').read_text())
        if budget_limit() is not None or not handoff_ready(state):
            raise RuntimeError('Unsafe handoff: unfinished pairs or missing unlimited authorization')
        if lock.exists():lock.rename(STATE/f'controller.pre-unlimited-{time.time_ns()}.lock-archive')
    with lock.open('x') as stream:stream.write(str(time.time()))
    try:
        path=STATE/'ledger.json'
        state=json.loads(path.read_text()) if path.exists() else dict(approved_seconds=BUDGET,results=[],started=time.time())
        limit=budget_limit()
        if state.get('approved_seconds')!=limit:
            state.setdefault('budget_history',[]).append(dict(previous_seconds=state.get('approved_seconds'),
                                                            new_seconds=limit,changed_at=time.time(),source='budget-control.json'))
        state['approved_seconds']=limit
        state['budget_mode']='unlimited' if limit is None else 'limited'
        pending=[i for i in items if not any(r['item']==i and r['eligible_pair'] for r in state['results'])]
        state.update(phase=args.phase,plan=items,status='running',failure=None,
                     finished=None,stop_reason=None,phase_complete=False,failure_pending=[])
        used=sum(r['seconds'] for r in state['results']);running={}
        idle=json.loads((ROOT/'results/workers.json').read_text())
        with ThreadPoolExecutor(max_workers=4) as pool:
            while pending or running:
                while pending and idle:
                    if (STATE/'pause-request.json').exists():break
                    item=pending[0]
                    prior=[r['seconds'] for r in state['results'] if r['eligible_pair'] and r['item']['cycles']==item['cycles']]
                    allowance=max(prior)*1.25+90 if prior else (1000 if args.phase=='pilot' else 4800)
                    allowance=max(allowance,600)
                    limit=budget_limit()
                    state['approved_seconds']=limit
                    state['budget_mode']='unlimited' if limit is None else 'limited'
                    available=float('inf') if limit is None else limit-used-sum(v[2] for v in running.values())-120
                    if available<allowance or shutil.disk_usage(ROOT).free<2*1024**3:break
                    if args.phase=='main' and running and item['seed']>min(v[1]['seed'] for v in running.values()):break
                    pending.pop(0);worker=idle.pop(0)
                    attempt=1+sum(r['item']==item for r in state['results'])
                    future=pool.submit(execute,item,worker,allowance,attempt)
                    running[future]=(worker,item,allowance)
                    print('START',worker['name'],item,flush=True)
                state.update(active_seconds=used,pending=pending,
                             in_flight=[dict(worker=w['name'],item=i,reserved_seconds=a) for w,i,a in running.values()])
                save(state)
                if not running:break
                done,_=wait(running,timeout=20,return_when=FIRST_COMPLETED)
                for future in done:
                    worker,item,allowance=running.pop(future)
                    try:result=future.result()
                    except Exception as error:
                        result=dict(item=item,worker=worker['name'],eligible_pair=False,seconds=allowance,error=repr(error),records=[])
                    used+=result['seconds'];state['results'].append(result);idle.append(worker)
                    print('DONE',item,result['eligible_pair'],round(result['seconds']),flush=True)
                    if not result['eligible_pair']:
                        state['failure_pending']=pending;pending=[];state['failure']=result.get('error','run_or_audit_failure')
                    state['active_seconds']=used
                    save(state)
                    subprocess.run([sys.executable,str(ROOT/'scripts/report_main_v2.py')],check=True)
        complete=all(any(r['item']==i and r['eligible_pair'] for r in state['results']) for i in items)
        paused=(STATE/'pause-request.json').exists()
        state.update(active_seconds=used,in_flight=[],pending=pending,finished=time.time(),status='paused' if paused else 'stopped',
                     phase_complete=complete,stop_reason='user_requested_after_current_pairs' if paused else ('complete' if complete else ('failure' if state['failure'] else 'budget_or_disk')))
        save(state);print(json.dumps({k:state[k] for k in ['phase_complete','active_seconds','stop_reason']}),flush=True)
    finally:lock.unlink(missing_ok=True)
    if args.phase=='main' and complete and not (STATE/'pause-request.json').exists():
        subprocess.run([sys.executable,str(ROOT/'scripts/assess_precision.py')],check=True)
        selected=json.loads((STATE/'confirmation-plan.json').read_text())
        if selected:
            subprocess.run([sys.executable,__file__,'--phase','confirmation','--launch'],check=True)
            subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_article.py'),
                            '--prefix','main-v2-confirmation-','--series','main-v2-confirmation',
                            '--out',str(STATE/'confirmation-evaluation')],check=True)

if __name__=='__main__':main()
