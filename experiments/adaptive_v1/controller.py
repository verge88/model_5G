"""Small dynamic-attack pilot; frozen detectors and existing measurement binaries."""
import bisect,hashlib,json,math,random,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import joblib
import robustness_stage as engine
from detector_stage import execute as base_execute,write as base_write
from ml_features import score_run,FEATURES
from analyze import events
from delay_burst_stage import validate_delay
STATE=ROOT/'results/adaptive-v1'
MODEL=ROOT/'results/ml-v1/frozen-models.joblib'

def plan():
    scenarios=[('honest',0,[]),('onoff',.1,['--attack-mode','onoff']),
               ('ramp',.1,['--attack-mode','ramp']),('budget',.1,['--residual-budget','1'])]
    items=[dict(stage=tag,policy=p,rho=.5,seed=s,alpha=a,
                extra=['--heartbeat','5','--nfm-delay-ms','200']+extra)
           for s in [1401,1402,1403] for p in ['swrr','random'] for tag,a,extra in scenarios]
    random.Random(1801).shuffle(items);return items

def temporal(folder,values,predictions):
    m=json.loads((folder/'manifest.json').read_text());begin=m['measurement_start_us'];end=m['measurement_end_us']
    rows=sorted([e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)],key=lambda e:int(e['t']))
    loads=[e for e in rows if e['kind']=='LOAD' and e['source']=='smf3.log']
    ids={e['nf'] for e in loads};assert len(ids)==1;target=next(iter(ids))
    truth={e['version']:e for e in loads};states=[];versions=[]
    for e in rows:
        if e['kind']=='NRF' and e.get('nf')==target:
            t=int(e['t']);load=truth[e['version']]
            active=float(e['stored'])<math.floor(float(load['reference']))
            if not states or states[-1][1]!=active:states.append((t,active))
            if begin<=t<=end:versions.append(int(e['version']))
    assert versions
    if m['attack_mode']=='ramp':assert min(versions)<120,'Ramp ended before measurement'
    times=[t for t,a in states];labels=[]
    for value in values:
        start=begin+value['window']*1e7;finish=start+1e7
        index=bisect.bisect_right(times,start)-1;assert index>=0
        mixed=bisect.bisect_left(times,finish)>bisect.bisect_right(times,start)
        labels.append('mixed' if mixed else ('on' if states[index][1] else 'off'))
    result={}
    for model,alarms in predictions.items():
        groups={label:dict(windows=sum(x==label for x in labels),alarms=sum(a for a,l in zip(alarms,labels) if l==label)) for label in ['on','off','mixed']}
        episodes=[]
        for j,(start,active) in enumerate(states[:-1]):
            finish=states[j+1][0]
            if active and begin<=start<finish<=end:
                # Restrict to fully active windows to avoid attributing a pre-onset alarm.
                decisions=[begin+(v['window']+1)*1e7 for v,a,l in zip(values,alarms,labels)
                           if a and l=='on' and start<=begin+v['window']*1e7 and begin+(v['window']+1)*1e7<=finish]
                episodes.append(dict(onset_receipt_us=start,offset_receipt_us=finish,
                    delay_s=(min(decisions)-start)/1e6 if decisions else None))
        result[model]=dict(groups=groups,complete_episodes=episodes,
            all_window_alarm_fraction=sum(alarms)/len(alarms))
    return dict(models=result,min_measured_version=min(versions),max_measured_version=max(versions),
                label_definition='Actual integer underreport at NRF receipt; ground truth only, not a feature.')

def execute(item,worker,attempt,state_dir=None,series=None):
    result=base_execute(item,worker,attempt,STATE,'adaptive-v1')
    if not result['eligible']:return result
    folder=ROOT/'runs'/result['name'];features=json.loads((STATE/(result['name']+'.features.json')).read_text())
    scored=score_run(folder,features);values=scored['window_scores']
    bundle=joblib.load(MODEL);assert bundle['features']==FEATURES
    predictions={name:[bool(v>bundle['thresholds'][name]) for v in model.predict_proba([v['x'] for v in values])[:,1]] for name,model in bundle['models'].items()}
    predictions['age_fixed']=[v['age_aware']>0 for v in values]
    predictions['cusum']=[v['cusum']>bundle['thresholds']['cusum'] for v in values]
    result['temporal']=temporal(folder,values,predictions)
    result['delay_validation']=validate_delay(folder)
    base_write(STATE/(result['name']+'.scores.json'),dict(scores=scored,predictions=predictions,temporal=result['temporal']))
    return result

def summarize(state):
    good=[r for r in state['results'] if r['eligible']];pairs=[]
    for r in good:
        if r['item']['stage']=='honest':continue
        controls=[c for c in good if c['item']['stage']=='honest' and c['item']['seed']==r['item']['seed'] and c['item']['policy']==r['item']['policy']]
        if controls:
            c=controls[0];assert r['audit']['workload_hash']==c['audit']['workload_hash']
            pairs.append(dict(attack=r['name'],honest=c['name'],scenario=r['item']['stage'],seed=r['item']['seed'],policy=r['item']['policy'],
                              delta_share_pp=100*(r['audit']['s3']-c['audit']['s3'])))
    base_write(STATE/'evaluation.json',dict(complete=len(good)==24,paired_effects=pairs,
        by_run=[dict(run=r['name'],item=r['item'],s3=r['audit']['s3'],**r['temporal']) for r in good],
        limitations=['Pilot with three seeds per condition, no population guarantees.',
        'ML heartbeat distribution shifts to 5 seconds; matched honest controls measure its false alarms.',
        'Ramp is version-based, on/off period is 30 heartbeat versions, not short bursts.',
        'Budget attack limits local deviation to 1 percentage point; no access to detector history.',
        'Episode latency starts at NRF receipt and uses only fully active completed windows.',
        'Integer quantization is part of the intervention. No retraining or threshold adaptation.']))

def write(path,value):
    base_write(path,value)
    if path.name=='ledger.json':
        good=sum(r['eligible'] for r in value['results'])
        (STATE/'PROGRESS.md').write_text(f"# Пилот динамических атак\n\nСостояние: {value.get('status')}\nЗачтено: {good} / 24\nТекущих запусков: {len(value.get('in_flight',[]))}\nОбновлено: {time.strftime('%Y-%m-%d %H:%M:%S')}\nОшибка: {value.get('error')}\n\nДля паузы после текущих запусков создайте pause-request.json в этой папке.\n",encoding='utf-8')

def main():
    STATE.mkdir(exist_ok=True)
    sys.stdout=(STATE/'controller.stdout.log').open('a',buffering=1,encoding='utf-8')
    sys.stderr=(STATE/'controller.stderr.log').open('a',buffering=1,encoding='utf-8')
    for p in (ROOT/'results').glob('*/controller.lock'):raise RuntimeError('Existing controller '+str(p))
    assert not (STATE/'pause-request.json').exists()
    previous=json.loads((ROOT/'results/ml-v1/measurement-code.json').read_text())
    assert all(hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()==h for name,h in previous.items())
    modelhash=hashlib.sha256(MODEL.read_bytes()).hexdigest()
    assert modelhash==json.loads((ROOT/'results/ml-v1/freeze.json').read_text())['sha256']
    freeze=dict(model_sha256=modelhash,controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),original_code=previous)
    snapshot=STATE/'measurement-code.json'
    if snapshot.exists():assert json.loads(snapshot.read_text())==freeze
    else:base_write(snapshot,freeze)
    subprocess.run(['docker','start','model5g-db','model5g-db2','model5g-db3','model5g-db4'],check=True,stdout=sys.stdout,stderr=sys.stderr)
    subprocess.run(['docker','start','model5g-runtime','model5g-worker2','model5g-worker3','model5g-worker4'],check=True,stdout=sys.stdout,stderr=sys.stderr)
    time.sleep(5)
    engine.STATE=STATE;engine.SERIES='adaptive-v1';engine.plan=plan;engine.execute=execute;engine.summarize=summarize;engine.write=write
    engine.main()

if __name__=='__main__':main()
