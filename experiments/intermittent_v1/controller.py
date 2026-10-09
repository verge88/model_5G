"""Frozen specialist under weak intermittent attacks, jitter and population steps."""
import bisect,hashlib,importlib.util,json,random,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'experiments/specialist_v1'))
import detector,joblib
import robustness_stage as engine
from detector_stage import write as save,check_build
from evaluate_article import audit
from ml_features import score_run
from analyze import events
from delay_burst_stage import validate_delay
spec=importlib.util.spec_from_file_location('adaptive_temporal',ROOT/'experiments/adaptive_v1/controller.py')
temporal_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(temporal_module)
STATE=ROOT/'results/intermittent-v1';MODEL=ROOT/'results/specialist-v1/model.joblib'
FREEZE=ROOT/'results/specialist-v1/freeze.json'

def plan():
    items=[dict(stage=tag,policy=p,rho=.5,seed=s,alpha=0 if tag=='honest' else .02)
           for s in [1701,1702,1703] for p in ['swrr','random'] for tag in ['honest','onoff']]
    random.Random(2001).shuffle(items);return items

def clearing(folder,values,predictions):
    m=json.loads((folder/'manifest.json').read_text());begin=m['measurement_start_us'];end=m['measurement_end_us']
    rows=sorted([e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)],key=lambda e:int(e['t']))
    loads=[e for e in rows if e['kind']=='LOAD' and e['source']=='smf3.log'];truth={e['version']:e for e in loads}
    ids={e['nf'] for e in loads};assert len(ids)==1;target=next(iter(ids));states=[]
    import math
    for e in rows:
        if e['kind']=='NRF' and e.get('nf')==target:
            t=int(e['t']);active=float(e['stored'])<math.floor(float(truth[e['version']]['reference']))
            if not states or active!=states[-1][1]:states.append((t,active))
    output={}
    for model,alarms in predictions.items():
        episodes=[]
        for i in range(1,len(states)-1):
            start,active=states[i];finish=states[i+1][0]
            if active or not (begin<=start<finish<=end):continue
            candidates=[(begin+(v['window']+1)*1e7,a) for v,a in zip(values,alarms)
                        if begin+v['window']*1e7>=start and begin+(v['window']+1)*1e7<=finish]
            clean=[t for t,a in candidates if not a]
            episodes.append(dict(off_receipt_us=start,next_on_receipt_us=finish,full_windows=len(candidates),
                alarm_windows=sum(a for t,a in candidates),first_clear_s=(min(clean)-start)/1e6 if clean else None))
        output[model]=episodes
    return output

def execute(item,worker,attempt,state_dir=None,series=None):
    name=f"intermittent-v1-{item['stage']}-{item['policy']}-s{item['seed']}-a{round(item['alpha']*100)}-attempt{attempt}"
    folder=ROOT/'runs'/name;started=time.time()
    if not folder.exists():
        info=json.loads(subprocess.check_output(['docker','inspect',worker['name']],text=True))[0]['HostConfig']
        assert info['CpusetCpus']==worker['cpus']
        resource={k:info.get(k) for k in ['CpusetCpus','Memory','NanoCpus','CpuQuota','CpuPeriod']}
        command=['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],'-e','LAB_RESOURCE_CONFIGURATION='+hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest(),
            worker['name'],'python','/work/scripts/run_lab_ml.py','--out','runs/'+name,'--series-id','intermittent-v1','--compact-storage',
            '--deadline',str(time.time()+3600),'--policy',item['policy'],'--seed',str(item['seed']),
            '--active','150','--ues','222','--capacity','100','--reported-capacity','100','--alpha',str(item['alpha']),
            '--attack-mode','onoff','--warmup','300','--cycles','3300','--interval','.01',
            '--heartbeat','1','--nfm-delay-ms','50','--nfm-delay-max-ms','450','--burst']
        with (STATE/(name+'.log')).open('w') as out:status=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT).returncode
        if status:return dict(item=item,name=name,eligible=False,error='runner_exit_'+str(status))
    checked,features=audit(folder);check_build(checked);assert features
    if not checked['eligible']:return dict(item=item,name=name,eligible=False,audit=checked,error='audit_failure')
    values=score_run(folder,features)['window_scores'];bundle=joblib.load(MODEL)
    threshold=json.loads(FREEZE.read_text())['threshold'];pred=detector.decisions(values,bundle,threshold)
    temporal=temporal_module.temporal(folder,values,pred)
    clear=clearing(folder,values,pred)
    save(STATE/(name+'.features.json'),features)
    save(STATE/(name+'.scores.json'),dict(values=values,predictions=pred,temporal=temporal,clearing=clear))
    return dict(item=item,name=name,eligible=True,audit=checked,temporal=temporal,clearing=clear,
                delay_validation=validate_delay(folder),seconds=time.time()-started)

def summarize(state):
    good=[r for r in state['results'] if r['eligible']];cells=[];pairs=[]
    for scenario in ['honest','onoff']:
        for policy in ['swrr','random']:
            rs=[r for r in good if r['item']['stage']==scenario and r['item']['policy']==policy]
            for model in ['age_fixed','memory_rule','specialist']:
                if not rs:continue
                groups={label:{key:sum(r['temporal']['models'][model]['groups'][label][key] for r in rs)
                    for key in ['windows','alarms']} for label in ['on','off','mixed']}
                on=[e for r in rs for e in r['temporal']['models'][model]['complete_episodes']]
                off=[e for r in rs for e in r['clearing'][model]]
                cells.append(dict(scenario=scenario,policy=policy,model=model,runs=len(rs),groups=groups,
                    complete_on_episodes=len(on),missed_on_episodes=sum(e['delay_s'] is None for e in on),
                    on_delay_seconds=[e['delay_s'] for e in on if e['delay_s'] is not None],
                    complete_off_episodes=len(off),uncleared_off_episodes=sum(e['first_clear_s'] is None for e in off),
                    clearing_seconds=[e['first_clear_s'] for e in off if e['first_clear_s'] is not None],
                    mean_run_fractions={label:statistics.mean(g['alarms']/g['windows'] for r in rs
                        if (g:=r['temporal']['models'][model]['groups'][label])['windows'])
                        for label in ['on','off','mixed'] if any(r['temporal']['models'][model]['groups'][label]['windows'] for r in rs)}))
    for r in good:
        if r['item']['stage']!='onoff':continue
        controls=[c for c in good if c['item']['stage']=='honest' and c['item']['seed']==r['item']['seed'] and c['item']['policy']==r['item']['policy']]
        if controls:
            c=controls[0];assert c['audit']['workload_hash']==r['audit']['workload_hash']
            pairs.append(dict(seed=r['item']['seed'],policy=r['item']['policy'],delta_share_pp=100*(r['audit']['s3']-c['audit']['s3'])))
    save(STATE/'evaluation.json',dict(complete=len(good)==12,cells=cells,paired_effects=pairs,
        threshold=json.loads(FREEZE.read_text())['threshold'],
        limitations=['Frozen-model transfer test; no tuning on this cohort.',
        'Labels and episode boundaries refer to integer underreport at NRF receipt.',
        'Complete episodes and fully labelled windows only; mixed windows separate.',
        'Three seeds per condition; descriptive pilot, dependent episodes.',
        'On/off uses 30 load versions, about 30 s, not subsecond pulses; delay applies per TCP chunk.']))

def write(path,value):
    save(path,value)
    if path.name=='ledger.json':
        (STATE/'PROGRESS.md').write_text(f"# Слабая прерывистая атака\n\nСостояние: {value.get('status')}\nЗачтено: {sum(r['eligible'] for r in value['results'])} / 12\nТекущих запусков: {len(value.get('in_flight',[]))}\nОбновлено: {time.strftime('%Y-%m-%d %H:%M:%S')}\nОшибка: {value.get('error')}\n\nПауза после текущих запусков: pause-request.json в этой папке.\n",encoding='utf-8')

def main():
    STATE.mkdir(exist_ok=True)
    sys.stdout=(STATE/'controller.stdout.log').open('a',buffering=1,encoding='utf-8')
    sys.stderr=(STATE/'controller.stderr.log').open('a',buffering=1,encoding='utf-8')
    assert not list((ROOT/'results').rglob('controller.lock'))
    assert not (STATE/'pause-request.json').exists()
    prior=json.loads((ROOT/'results/ml-v1/measurement-code.json').read_text())
    assert all(hashlib.sha256((ROOT/'scripts'/n).read_bytes()).hexdigest()==h for n,h in prior.items())
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest()==json.loads(FREEZE.read_text())['model_sha256']
    paths=[Path(__file__),ROOT/'experiments/specialist_v1/detector.py',ROOT/'experiments/adaptive_v1/controller.py',MODEL,FREEZE]
    code={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    snap=STATE/'measurement-code.json'
    if snap.exists():assert json.loads(snap.read_text())==code
    else:save(snap,code)
    for containers in [['model5g-db','model5g-db2','model5g-db3','model5g-db4'],['model5g-runtime','model5g-worker2','model5g-worker3','model5g-worker4']]:
        subprocess.run(['docker','start']+containers,check=True,stdout=sys.stdout,stderr=sys.stderr)
    time.sleep(5)
    engine.STATE=STATE;engine.SERIES='intermittent-v1';engine.plan=plan;engine.execute=execute;engine.summarize=summarize;engine.write=write
    engine.main()

if __name__=='__main__':main()
