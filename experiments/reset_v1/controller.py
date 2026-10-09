"""Independent validation of causal reset against frozen baselines and ML."""
import hashlib,importlib.util,json,random,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent))
from develop import predict
spec=importlib.util.spec_from_file_location('intermittent_engine',ROOT/'experiments/intermittent_v1/controller.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
STATE=ROOT/'results/reset-v1';THRESHOLD=.5

def plan():
    items=[dict(stage=tag,policy=p,rho=.5,seed=s,alpha=.1 if tag=='budget' else (.02 if tag=='onoff' else 0))
        for s in [1801,1802,1803] for p in ['swrr','random'] for tag in ['honest-fixed','budget','honest-variable','onoff']]
    random.Random(2101).shuffle(items);return items

def execute(item,worker,attempt,state_dir=None,series=None):
    name=f"reset-v1-{item['stage']}-{item['policy']}-s{item['seed']}-a{round(item['alpha']*100)}-attempt{attempt}"
    folder=ROOT/'runs'/name;started=time.time();variable=item['stage'] in ['honest-variable','onoff']
    if not folder.exists():
        info=json.loads(subprocess.check_output(['docker','inspect',worker['name']],text=True))[0]['HostConfig']
        assert info['CpusetCpus']==worker['cpus']
        resource={k:info.get(k) for k in ['CpusetCpus','Memory','NanoCpus','CpuQuota','CpuPeriod']}
        cmd=['docker','exec','-e','LAB_EXECUTION_WORKER='+worker['name'],'-e','LAB_RESOURCE_CONFIGURATION='+hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest(),
             worker['name'],'python','/work/scripts/run_lab_ml.py','--out','runs/'+name,'--series-id','reset-v1','--compact-storage',
             '--deadline',str(time.time()+3600),'--policy',item['policy'],'--seed',str(item['seed']),
             '--active','150','--ues','222' if variable else '162','--capacity','100','--reported-capacity','100',
             '--alpha',str(item['alpha']),'--attack-mode','onoff' if variable else 'constant',
             '--warmup','300','--cycles','3300','--interval','.01','--heartbeat','1' if variable else '5',
             '--nfm-delay-ms','50' if variable else '200','--nfm-delay-max-ms','450' if variable else '200']
        if variable:cmd.append('--burst')
        if item['stage']=='budget':cmd+=['--residual-budget','1']
        with (STATE/(name+'.log')).open('w') as out:status=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT).returncode
        if status:return dict(item=item,name=name,eligible=False,error='runner_exit_'+str(status))
    checked,features=base.audit(folder);base.check_build(checked);assert features
    if not checked['eligible']:return dict(item=item,name=name,eligible=False,audit=checked,error='audit_failure')
    values=base.score_run(folder,features)['window_scores']
    pred=base.detector.decisions(values,base.joblib.load(base.MODEL),json.loads(base.FREEZE.read_text())['threshold'])
    pred['reset']=predict(values,THRESHOLD)
    temporal=base.temporal_module.temporal(folder,values,pred);clear=base.clearing(folder,values,pred)
    base.save(STATE/(name+'.features.json'),features)
    base.save(STATE/(name+'.scores.json'),dict(values=values,predictions=pred,temporal=temporal,clearing=clear))
    return dict(item=item,name=name,eligible=True,audit=checked,temporal=temporal,clearing=clear,
        delay_validation=base.validate_delay(folder),seconds=time.time()-started)

def summarize(state):
    good=[r for r in state['results'] if r['eligible']];cells=[];pairs=[]
    for scenario in ['honest-fixed','budget','honest-variable','onoff']:
        for policy in ['swrr','random']:
            rs=[r for r in good if r['item']['stage']==scenario and r['item']['policy']==policy]
            for model in ['age_fixed','memory_rule','specialist','reset']:
                if not rs:continue
                groups={label:{key:sum(r['temporal']['models'][model]['groups'][label][key] for r in rs)
                    for key in ['windows','alarms']} for label in ['on','off','mixed']}
                on=[e for r in rs for e in r['temporal']['models'][model]['complete_episodes']]
                off=[e for r in rs for e in r['clearing'][model]]
                cells.append(dict(scenario=scenario,policy=policy,model=model,runs=len(rs),groups=groups,
                    complete_on_episodes=len(on),missed_on_episodes=sum(e['delay_s'] is None for e in on),
                    on_delay_seconds=[e['delay_s'] for e in on if e['delay_s'] is not None],
                    complete_off_episodes=len(off),off_without_full_window=sum(e['full_windows']==0 for e in off),
                    uncleared_with_full_window=sum(e['full_windows']>0 and e['first_clear_s'] is None for e in off),
                    clearing_seconds=[e['first_clear_s'] for e in off if e['first_clear_s'] is not None],
                    mean_run_fractions={label:statistics.mean(g['alarms']/g['windows'] for r in rs
                        if (g:=r['temporal']['models'][model]['groups'][label])['windows'])
                        for label in ['on','off','mixed'] if any(r['temporal']['models'][model]['groups'][label]['windows'] for r in rs)}))
    for r in good:
        tag=r['item']['stage']
        if tag not in ['budget','onoff']:continue
        control='honest-fixed' if tag=='budget' else 'honest-variable'
        cs=[c for c in good if c['item']['stage']==control and c['item']['seed']==r['item']['seed'] and c['item']['policy']==r['item']['policy']]
        if cs:
            c=cs[0];assert c['audit']['workload_hash']==r['audit']['workload_hash']
            pairs.append(dict(scenario=tag,seed=r['item']['seed'],policy=r['item']['policy'],delta_share_pp=100*(r['audit']['s3']-c['audit']['s3'])))
    base.save(STATE/'evaluation.json',dict(complete=len(good)==24,reset_threshold=THRESHOLD,cells=cells,paired_effects=pairs,
        note='New seeds; frozen reset, baselines and ML. Three-seed descriptive comparison. Report benefit and clearing tradeoffs together.'))

def write(path,value):
    base.save(path,value)
    if path.name=='ledger.json':
        (STATE/'PROGRESS.md').write_text(f"# Проверка сброса памяти\n\nСостояние: {value.get('status')}\nЗачтено: {sum(r['eligible'] for r in value['results'])} / 24\nТекущих запусков: {len(value.get('in_flight',[]))}\nОбновлено: {time.strftime('%Y-%m-%d %H:%M:%S')}\nОшибка: {value.get('error')}\n\nДля паузы после текущих запусков создайте pause-request.json в этой папке.\n",encoding='utf-8')

def main():
    development=json.loads((STATE/'development.json').read_text())
    assert development['selected']['threshold']==THRESHOLD
    paths=[Path(__file__),Path(__file__).with_name('develop.py'),STATE/'development.json',ROOT/'results/intermittent-v1/measurement-code.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frozen=STATE/'reset-freeze.json'
    if frozen.exists():assert json.loads(frozen.read_text())==hashes
    else:base.save(frozen,hashes)
    base.STATE=STATE;base.plan=plan;base.execute=execute;base.summarize=summarize;base.write=write
    base.main()

if __name__=='__main__':main()
