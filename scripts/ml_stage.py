"""Three-phase ML experiment with a strict model-freeze barrier before test."""
import concurrent.futures as cf,ctypes,hashlib,json,os,random,shutil,subprocess,sys,time
from pathlib import Path
from detector_stage import write,check_build
from evaluate_article import audit
from ml_features import score_run
from ml_evaluate import freeze,evaluate
ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'results/ml-v1'

def plan():
    result=[]
    for stage,seeds,alphas in [('train',[1101,1102,1103],[0,.02,.05,.1]),('cal',[1201,1202,1203],[0]),('test',[1301,1302,1303],[0,.02,.05,.1])]:
        items=[dict(stage=stage,seed=s,policy=p,alpha=a) for s in seeds for p in ['swrr','random'] for a in alphas]
        random.Random(1701).shuffle(items);result.extend(items)
    return result

def execute(item,worker,attempt):
    name=f"ml-v1-{item['stage']}-{item['policy']}-s{item['seed']}-a{round(100*item['alpha'])}-attempt{attempt}"
    folder=ROOT/'runs'/name;start=time.time()
    if not folder.exists():
        info=json.loads(subprocess.check_output(['docker','inspect',worker['name']],text=True))[0]['HostConfig']
        assert info['CpusetCpus']==worker['cpus']
        resource={k:info.get(k) for k in ['CpusetCpus','Memory','NanoCpus','CpuQuota','CpuPeriod']}
        cmd=['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],'-e','LAB_RESOURCE_CONFIGURATION='+hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest(),
             worker['name'],'python','/work/scripts/run_lab_ml.py','--out','runs/'+name,'--series-id','ml-v1','--compact-storage',
             '--deadline',str(time.time()+3600),'--policy',item['policy'],'--seed',str(item['seed']),'--alpha',str(item['alpha']),
             '--active','150','--ues','222' if item['stage']=='test' else '162','--capacity','100','--reported-capacity','100',
             '--warmup','300','--cycles','3300','--interval','.01','--nfm-delay-ms','50','--nfm-delay-max-ms','450' if item['stage']=='test' else '350']
        if item['stage']=='test':cmd.append('--burst')
        with (STATE/(name+'.log')).open('w') as out:status=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT).returncode
        if status:return dict(item=item,name=name,eligible=False,error='runner_exit_'+str(status))
    audited,features=audit(folder);check_build(audited)
    assert features
    write(STATE/(name+'.features.json'),features)
    scored=score_run(folder,features);write(STATE/(name+'.ml.json'),scored)
    # SEND timestamps are used only to audit delay injection, never in ML features.
    from delay_burst_stage import validate_delay
    delay=validate_delay(folder)
    return dict(item=item,name=name,eligible=audited['eligible'],audit=audited,delay=delay,seconds=time.time()-start)

def progress(state):
    good=[r for r in state['results'] if r['eligible']]
    text=['# Ход ML-эксперимента','',f"Состояние: {state.get('status')}",f"Обновлено: {time.strftime('%Y-%m-%d %H:%M:%S')}",'',
          f"Зачтено: {len(good)} / 54",f"Обучение: {sum(r['item']['stage']=='train' for r in good)} / 24",
          f"Калибровка: {sum(r['item']['stage']=='cal' for r in good)} / 6",f"Проверка: {sum(r['item']['stage']=='test' for r in good)} / 24",'',
          'Модели фиксируются до запуска проверочной серии. Ошибка останавливает выдачу новых запусков.',
          'Для паузы после текущих запусков создайте results/ml-v1/pause-request.json.',
          f"Ошибка: {state.get('error') or 'нет'}"]
    (STATE/'PROGRESS.md').write_text('\n'.join(text),encoding='utf-8')
    write(STATE/'ledger.json',state)

def main():
    STATE.mkdir(exist_ok=True)
    if (STATE/'pause-request.json').exists():raise RuntimeError('Pause requested')
    for lock in (ROOT/'results').glob('*/controller.lock'):raise RuntimeError('Existing controller: '+str(lock))
    code={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'scripts').glob('*.py')}
    snapshot=STATE/'measurement-code.json'
    if snapshot.exists():assert json.loads(snapshot.read_text())==code,'Code changed since freeze'
    else:write(snapshot,code)
    write(STATE/'plan.json',dict(items=plan()))
    lock=STATE/'controller.lock';lock.write_text(str(os.getpid()))
    state=json.loads((STATE/'ledger.json').read_text()) if (STATE/'ledger.json').exists() else dict(results=[])
    workers=json.loads((ROOT/'results/workers.json').read_text());containers=[w['name'] for w in workers]+['model5g-db','model5g-db2','model5g-db3','model5g-db4']
    try:
        if sys.platform=='win32':ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        subprocess.run(['docker','start']+containers,check=True,stdout=sys.stdout,stderr=sys.stderr);time.sleep(5)
        state.update(status='running',error=None)
        for phase in ['train','cal','test']:
            if phase=='test':freeze(state['results'])
            pending=[i for i in plan() if i['stage']==phase and not any(r['eligible'] and r['item']==i for r in state['results'])]
            idle=list(workers);running={};failed=False
            with cf.ThreadPoolExecutor(max_workers=4) as pool:
                while pending or running:
                    paused=(STATE/'pause-request.json').exists()
                    while pending and idle and not failed and not paused:
                        if shutil.disk_usage(ROOT).free<3*1024**3:failed=True;state['error']='low_disk';break
                        item=pending.pop(0);worker=idle.pop(0);attempt=1+sum(r['item']==item for r in state['results'])
                        running[pool.submit(execute,item,worker,attempt)]=(item,worker)
                        print('START',worker['name'],item,flush=True)
                    state.update(phase=phase,updated_at=time.time(),in_flight=[dict(item=i,worker=w['name']) for i,w in running.values()],pending=pending)
                    progress(state)
                    if not running:break
                    done,_=cf.wait(running,timeout=20,return_when=cf.FIRST_COMPLETED)
                    for future in done:
                        item,worker=running.pop(future);idle.append(worker)
                        try:r=future.result()
                        except Exception as error:r=dict(item=item,eligible=False,error=repr(error))
                        state['results'].append(r);print('DONE',item,r['eligible'],flush=True)
                        if not r['eligible']:failed=True;state['error']=r.get('error','audit_failure')
                        if phase=='test':evaluate(state['results'])
            if failed or (STATE/'pause-request.json').exists():
                state['status']='failed' if failed else 'paused';return
        state['status']='complete'
    except Exception as error:state.update(status='failed',error=repr(error));raise
    finally:
        state.update(updated_at=time.time(),in_flight=[]);progress(state)
        subprocess.run(['docker','stop']+containers,stdout=sys.stdout,stderr=sys.stderr)
        lock.unlink(missing_ok=True)
        if sys.platform=='win32':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

if __name__=='__main__':main()
