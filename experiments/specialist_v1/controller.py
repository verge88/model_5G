"""Prospective calibration then fixed specialist/baseline comparison."""
import hashlib,json,random,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import robustness_stage as engine
from detector_stage import execute as base_execute,write as save
from ml_features import score_run
from delay_burst_stage import validate_delay
import detector
import joblib
STATE=ROOT/'results/specialist-v1';PHASE='calibration'

def plan():
    seeds=[1501,1502,1503] if PHASE=='calibration' else [1601,1602,1603]
    tags=['honest'] if PHASE=='calibration' else ['honest','budget']
    items=[dict(stage=tag,policy=p,rho=.5,seed=s,alpha=0 if tag=='honest' else .1,
                extra=['--heartbeat','5','--nfm-delay-ms','200']+([] if tag=='honest' else ['--residual-budget','1']))
           for s in seeds for p in ['swrr','random'] for tag in tags]
    random.Random(1901).shuffle(items);return items

def execute(item,worker,attempt,state_dir=None,series=None):
    r=base_execute(item,worker,attempt,engine.STATE,engine.SERIES)
    if not r['eligible']:return r
    folder=ROOT/'runs'/r['name'];fs=json.loads((engine.STATE/(r['name']+'.features.json')).read_text())
    values=score_run(folder,fs)['window_scores'];bundle=joblib.load(STATE/'model.joblib')
    scored=detector.score(values,bundle)
    save(engine.STATE/(r['name']+'.specialist.json'),dict(values=values,scores=scored))
    r['delay_validation']=validate_delay(folder)
    return r

def summarize(state):
    rows=[]
    threshold=json.loads((STATE/'freeze.json').read_text())['threshold'] if PHASE=='test' else None
    for r in state['results']:
        if not r['eligible']:continue
        values=json.loads((engine.STATE/(r['name']+'.specialist.json')).read_text())['scores']
        entry=dict(run=r['name'],item=r['item'],windows=len(values),s3=r['audit']['s3'])
        if threshold is not None:
            entry['alarms']={name:sum(v[name] for v in values) for name in ['baseline','memory']}
            entry['alarms']['specialist']=sum(v['baseline'] or v['extra']>threshold for v in values)
        rows.append(entry)
    out=dict(phase=PHASE,complete=len(rows)==len(plan()),threshold=threshold,by_run=rows)
    if PHASE=='test':
        summary={}
        for model in ['baseline','memory','specialist']:
            summary[model]={tag:statistics.mean(r['alarms'][model]/r['windows'] for r in rows if r['item']['stage']==tag)
                            for tag in ['honest','budget'] if any(r['item']['stage']==tag for r in rows)}
        out['summary']=summary
        if out['complete']:
            special=summary['specialist'];base=summary['baseline'];memory=summary['memory']
            out['observed_primary_criterion']=special['honest']<=base['honest'] and special['budget']-base['budget']>=.05
            out['observed_advantage_over_memory']=special['honest']<=memory['honest'] and special['budget']>memory['budget']
            out['note']='Observed 3-seed comparison, not a population-level guarantee; historical data were development only.'
    save(engine.STATE/'evaluation.json',out)

def write(path,value):
    save(path,value)
    if path.name=='ledger.json':
        total=0
        for phase in ['calibration','test']:
            p=STATE/phase/'ledger.json'
            if p.exists():total+=sum(r['eligible'] for r in json.loads(p.read_text())['results'])
        (STATE/'PROGRESS.md').write_text(f"# Специализированный ML-детектор\n\nЭтап: {PHASE}\nСостояние: {value.get('status')}\nЗачтено: {total} / 18\nТекущих запусков: {len(value.get('in_flight',[]))}\nОбновлено: {time.strftime('%Y-%m-%d %H:%M:%S')}\nОшибка: {value.get('error')}\n",encoding='utf-8')

def freeze_threshold():
    target=STATE/'freeze.json'
    if target.exists():return
    ledger=json.loads((STATE/'calibration/ledger.json').read_text())
    good=[r for r in ledger['results'] if r['eligible']];assert len(good)==6
    extras=[]
    for r in good:
        values=json.loads((STATE/'calibration'/(r['name']+'.specialist.json')).read_text())['scores']
        extras.extend(v['extra'] for v in values if not v['baseline'])
    development=json.loads((STATE/'development.json').read_text())
    threshold=max(development['development_threshold'],max(extras))
    save(target,dict(threshold=threshold,comparison='strict >',calibration_runs=[r['name'] for r in good],
        model_sha256=hashlib.sha256((STATE/'model.joblib').read_bytes()).hexdigest(),
        rule='max(development threshold, maximum extra score on new honest baseline-negative windows)'))

def main():
    global PHASE
    sys.stdout=(STATE/'controller.stdout.log').open('a',buffering=1,encoding='utf-8')
    sys.stderr=(STATE/'controller.stderr.log').open('a',buffering=1,encoding='utf-8')
    assert not list((ROOT/'results').rglob('controller.lock')),'Another controller exists'
    original=json.loads((ROOT/'results/ml-v1/measurement-code.json').read_text())
    assert all(hashlib.sha256((ROOT/'scripts'/n).read_bytes()).hexdigest()==h for n,h in original.items())
    code={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    code['model']=hashlib.sha256((STATE/'model.joblib').read_bytes()).hexdigest()
    frozen=STATE/'measurement-code.json'
    if frozen.exists():assert json.loads(frozen.read_text())==code
    else:save(frozen,code)
    for phase in ['calibration','test']:
        PHASE=phase;engine.STATE=STATE/phase;engine.STATE.mkdir(exist_ok=True)
        if (STATE/'pause-request.json').exists():return
        if phase=='test':freeze_threshold()
        ledger=engine.STATE/'ledger.json'
        if ledger.exists() and json.loads(ledger.read_text())['status']=='complete':continue
        subprocess.run(['docker','start','model5g-db','model5g-db2','model5g-db3','model5g-db4'],check=True,stdout=sys.stdout,stderr=sys.stderr)
        subprocess.run(['docker','start','model5g-runtime','model5g-worker2','model5g-worker3','model5g-worker4'],check=True,stdout=sys.stdout,stderr=sys.stderr)
        time.sleep(5)
        engine.SERIES='specialist-v1-'+phase;engine.plan=plan;engine.execute=execute;engine.summarize=summarize;engine.write=write
        engine.main()
        if json.loads(ledger.read_text())['status']!='complete':return

if __name__=='__main__':main()
