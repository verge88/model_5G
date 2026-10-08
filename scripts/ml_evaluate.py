"""Freeze models using train runs and thresholds using separate honest calibration."""
import hashlib,json,statistics
from pathlib import Path
import joblib,numpy as np,sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from detector_stage import write
from ml_features import FEATURES
ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'results/ml-v1'

def rows(records):
    return [(r,json.loads((STATE/(r['name']+'.ml.json')).read_text())['window_scores']) for r in records]

def freeze(records):
    target=STATE/'frozen-models.joblib'
    if target.exists():return
    train=[r for r in records if r['eligible'] and r['item']['stage']=='train']
    cal=[r for r in records if r['eligible'] and r['item']['stage']=='cal']
    assert len(train)==24 and len(cal)==6
    X=[];y=[];weights=[]
    for r,values in rows(train):
        label=int(r['item']['alpha']>0)
        X.extend(v['x'] for v in values);y.extend([label]*len(values))
        weights.extend([1/(len(values)*(18 if label else 6))]*len(values))
    weights=np.asarray(weights);weights*=len(weights)/weights.sum()
    models={'logistic':make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=2000,random_state=1701)),
            'boosting':GradientBoostingClassifier(n_estimators=100,max_depth=2,learning_rate=.05,random_state=1701)}
    models['logistic'].fit(X,y,logisticregression__sample_weight=weights)
    models['boosting'].fit(X,y,sample_weight=weights)
    calibration={k:[] for k in ['logistic','boosting','cusum','age_calibrated']}
    for r,values in rows(cal):
        for name,model in models.items():calibration[name].append(model.predict_proba([v['x'] for v in values])[:,1].tolist())
        calibration['cusum'].append([v['cusum'] for v in values])
        calibration['age_calibrated'].append([v['age_aware'] for v in values])
    thresholds={}
    for name,runs in calibration.items():
        candidates=sorted({v for run in runs for v in run})
        thresholds[name]=next(t for t in candidates if statistics.mean(sum(v>t for v in run)/len(run) for run in runs)<=.01)
    joblib.dump(dict(models=models,thresholds=thresholds,features=FEATURES),target)
    write(STATE/'freeze.json',dict(sklearn=sklearn.__version__,features=FEATURES,thresholds=thresholds,
        train=[r['name'] for r in train],calibration=[r['name'] for r in cal],
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),primary='boosting',
        threshold_rule='Smallest observed calibration score with mean run alarm fraction <= .01; strict >'))

def evaluate(records):
    path=STATE/'frozen-models.joblib'
    if not path.exists():return
    frozen=json.loads((STATE/'freeze.json').read_text());assert hashlib.sha256(path.read_bytes()).hexdigest()==frozen['sha256']
    bundle=joblib.load(path);by_run=[]
    for r,values in rows([r for r in records if r['eligible'] and r['item']['stage']=='test']):
        scores={name:model.predict_proba([v['x'] for v in values])[:,1].tolist() for name,model in bundle['models'].items()}
        scores.update(cusum=[v['cusum'] for v in values],age_calibrated=[v['age_aware'] for v in values],age_fixed=[v['age_aware'] for v in values])
        for name,vs in scores.items():
            threshold=bundle['thresholds'].get(name,0);alarms=[v>threshold for v in vs]
            first=next((10*(values[i]['window']+1) for i,a in enumerate(alarms) if a),None)
            by_run.append(dict(run=r['name'],seed=r['item']['seed'],policy=r['item']['policy'],alpha=r['item']['alpha'],
                model=name,windows=len(vs),alarms=sum(alarms),fraction=sum(alarms)/len(vs),
                first_alarm_from_measurement_start_s=first))
    cells=[]
    for name,policy,alpha in sorted({(r['model'],r['policy'],r['alpha']) for r in by_run}):
        rs=[r for r in by_run if (r['model'],r['policy'],r['alpha'])==(name,policy,alpha)]
        cells.append(dict(model=name,policy=policy,alpha=alpha,runs=len(rs),mean_fraction=statistics.mean(r['fraction'] for r in rs),
            min_fraction=min(r['fraction'] for r in rs),max_fraction=max(r['fraction'] for r in rs)))
    write(STATE/'evaluation.json',dict(complete=sum(r['eligible'] and r['item']['stage']=='test' for r in records)==24,
        primary='boosting',by_run=by_run,cells=cells,
        limitations=['Three test seeds; windows are dependent. Descriptive feasibility results.',
                    'Test workload and delay distribution both shift; failure cannot be attributed to one factor.',
                    'First alarm is measured from measurement start, not attack onset; attack is active during warmup.',
                    'No adaptive attack or second core implementation in ML-v1.']))
