"""Causal 30-second specialist for ambiguous age-detector windows."""
import hashlib,json,statistics
from pathlib import Path
import joblib,numpy as np
from sklearn.ensemble import GradientBoostingClassifier
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/'results/specialist-v1'
FEATURES=['signed_mean','signed_sd','signed_min','signed_max','positive_fraction','history_span',
          'receipt_mean','receipt_sd','samples','mean30','min_window_mean30','max_window_mean30',
          'positive30','mean_sd30','span30','observed_change30','available_windows',
          'past_age_max','past_alarm_fraction','past_signed_mean']

def vectors(values):
    output=[]
    for i,v in enumerate(values):
        past=[p for p in values[max(0,i-2):i+1] if v['window']-2<=p['window']<=v['window']]
        x=v['x'];means=[p['x'][0] for p in past]
        output.append([x[0],x[1],x[2],x[3],x[4],x[7],x[8],x[9],x[10],
            statistics.mean(means),min(means),max(means),statistics.mean(p['x'][4] for p in past),
            statistics.pstdev(means),statistics.mean(p['x'][7] for p in past),
            x[6]-past[0]['x'][6],len(past),max([p['age_aware'] for p in past[:-1]] or [0]),
            statistics.mean([p['age_aware']>0 for p in past[:-1]] or [0]),
            statistics.mean([p['x'][0] for p in past[:-1]] or [0])])
    return output

def score(values,bundle):
    probability=bundle['model'].predict_proba(vectors(values))[:,1]
    result=[]
    for i,(v,p) in enumerate(zip(values,probability)):
        history=[x for x in values[max(0,i-2):i+1] if v['window']-2<=x['window']<=v['window']]
        # Current positive signed evidence prevents unconditional persistence after clearing.
        extra=float(p) if v['x'][0]>0 and len(history)==3 else 0.0
        memory=any(x['age_aware']>0 for x in history) and v['x'][0]>0
        result.append(dict(window=v['window'],baseline=v['age_aware']>0,extra=extra,
            memory=bool(v['age_aware']>0 or memory)))
    return result

def decisions(values,bundle,threshold):
    scores=score(values,bundle)
    return {'age_fixed':[s['baseline'] for s in scores],
            'memory_rule':[s['memory'] for s in scores],
            'specialist':[s['baseline'] or s['extra']>threshold for s in scores]}

def prepare():
    STATE.mkdir(exist_ok=True)
    assert not (STATE/'model.joblib').exists(),'Already prepared; do not overwrite a frozen model'
    training=[];calibration=[];sources={}
    for series in ['ml-v1','adaptive-v1']:
        folder=ROOT/'results'/series;ledger=json.loads((folder/'ledger.json').read_text())
        for r in ledger['results']:
            if not r['eligible']:continue
            item=r['item'];stage=item['stage']
            if series=='adaptive-v1' and stage not in ['honest','budget']:continue
            path=folder/(r['name']+('.ml.json' if series=='ml-v1' else '.scores.json'))
            data=json.loads(path.read_text());values=(data if series=='ml-v1' else data['scores'])['window_scores']
            label=int(item['alpha']>0)
            iscal=(series=='ml-v1' and label==0 and stage in ['cal','test']) or (series=='adaptive-v1' and item['seed']==1403)
            record=dict(name=r['name'],label=label,values=values)
            (calibration if iscal else training).append(record)
            sources[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    X=[];y=[];weights=[];used=[]
    for r in training:
        rows=[x for x,v in zip(vectors(r['values']),r['values']) if v['age_aware']==0]
        if not rows:continue
        used.append(dict(run=r['name'],label=r['label'],ambiguous_windows=len(rows)))
        X.extend(rows);y.extend([r['label']]*len(rows));weights.extend([1/len(rows)]*len(rows))
    y=np.asarray(y);weights=np.asarray(weights)
    for label in [0,1]:weights[y==label]/=weights[y==label].sum()
    weights*=len(y)/weights.sum()
    model=GradientBoostingClassifier(n_estimators=100,max_depth=2,min_samples_leaf=20,learning_rate=.05,random_state=1901)
    model.fit(X,y,sample_weight=weights);bundle=dict(model=model,features=FEATURES)
    joblib.dump(bundle,STATE/'model.joblib')
    honest=[s['extra'] for r in calibration if not r['label'] for s in score(r['values'],bundle) if not s['baseline']]
    threshold=max(honest)
    results=[]
    for r in calibration:
        pred=decisions(r['values'],bundle,threshold)
        results.append(dict(run=r['name'],label=r['label'],windows=len(r['values']),alarms={k:sum(v) for k,v in pred.items()}))
    output=dict(model_sha256=hashlib.sha256((STATE/'model.joblib').read_bytes()).hexdigest(),features=FEATURES,
        train_runs=used,retrospective_calibration_runs=[r['name'] for r in calibration],sources_sha256=sources,
        development_threshold=threshold,development=results,
        note='All prior cohorts are development data; these results do not establish superiority. New honest calibration and new test seeds are required.')
    (STATE/'development.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(dict(train_runs=len(used),ambiguous_training_windows=len(y),threshold=threshold,development=results),indent=2))

if __name__=='__main__':prepare()
