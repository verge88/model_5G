"""Grouped training, mask-specific honest calibration, and causal-stream scoring."""
import argparse,hashlib,json,math
from pathlib import Path
import joblib,numpy as np,sklearn
from sklearn.ensemble import HistGradientBoostingClassifier,IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from detector import FEATURES,matrix,config_digest

def load_dataset(path):
    manifest=json.loads(path.read_text(encoding='utf-8'));parts={p:[] for p in ['train','calibration','test']};seeds={p:set() for p in parts};runs=set();hashes={}
    for record in manifest['runs']:
        split=record['split'];run=record['run_id'];seed=str(record['seed'])
        if split not in parts or run in runs:raise ValueError('Invalid split or duplicate run')
        runs.add(run);seeds[split].add(seed)
        fp=(path.parent/record['features']).resolve();lp=(path.parent/record['labels']).resolve()
        hashes[str(fp)]=hashlib.sha256(fp.read_bytes()).hexdigest();hashes[str(lp)]=hashlib.sha256(lp.read_bytes()).hexdigest()
        rows=[json.loads(line) for line in fp.read_text().splitlines() if line.strip()]
        labels=[json.loads(line) for line in lp.read_text().splitlines() if line.strip()]
        def identity(r):return (float(r['observed_at']),tuple(r['entity'][k] for k in ['consumer','nf_type','service']))
        truth={identity(r):r['label'] for r in labels}
        if len(truth)!=len(labels) or len({identity(r) for r in rows})!=len(rows):raise ValueError('Duplicate row/label identity')
        if set(truth)!={identity(r) for r in rows}:raise ValueError('Features and labels must align exactly')
        for row in rows:
            if set(row['features'])!=set(FEATURES):raise ValueError('Feature schema mismatch')
            label=truth[identity(row)]
            if label not in [0,1,None]:raise ValueError('Label must be 0, 1 or null for censored/ambiguous')
            if label is None:continue
            parts[split].append(dict(row,run_id=run,seed_group=seed,label=label))
    for a,b in [('train','calibration'),('train','test'),('calibration','test')]:
        if seeds[a]&seeds[b]:raise ValueError('Seed group leaks across splits')
    if not all(parts.values()):raise ValueError('All three splits need labelled rows')
    if any(r['label'] for r in parts['calibration']):raise ValueError('Calibration must contain honest runs only')
    if {r['label'] for r in parts['train']}!={0,1}:raise ValueError('Training needs both classes')
    return parts,hashes

def threshold_for(scores,target_fpr):
    if not 0<=target_fpr<1:raise ValueError('target_fpr must be in [0,1)')
    values=np.asarray(scores,dtype=float)
    if not len(values) or not np.isfinite(values).all():raise ValueError('Invalid calibration scores')
    # Strict >: choose the smallest observed threshold satisfying the empirical tail budget.
    count=int(math.floor(target_fpr*len(values)))
    return float(np.sort(values)[len(values)-count-1])

def make_weights(rows):
    counts={}
    for r in rows:counts[(r['label'],r['run_id'])]=counts.get((r['label'],r['run_id']),0)+1
    groups={label:sum(c[0]==label for c in counts) for label in [0,1]}
    w=np.array([1/(counts[(r['label'],r['run_id'])]*groups[r['label']]) for r in rows]);return w*len(w)/w.sum()

def calibrate(rows,values,minimum_runs,minimum_rows,fpr):
    thresholds={}
    for mask in sorted({r['availability_mask'] for r in rows}):
        idx=[i for i,r in enumerate(rows) if r['availability_mask']==mask and r['sufficient_evidence']]
        run_count=len({rows[i].get('seed_group',rows[i]['run_id']) for i in idx})
        if len(idx)>=minimum_rows and run_count>=minimum_runs:
            thresholds[mask]=dict(threshold=threshold_for([values[i] for i in idx],fpr),rows=len(idx),runs=run_count)
    return thresholds

def score_rows(rows,bundle,model='specialist'):
    if bundle['features']!=FEATURES:raise ValueError('Model feature schema mismatch')
    if any(r.get('config_sha256')!=bundle['config_sha256'] for r in rows):raise ValueError('Feature observer configuration mismatch')
    if not rows:return []
    X=matrix(rows)
    scores=bundle['specialist'].predict_proba(X)[:,1] if model=='specialist' else -bundle['isolation'].score_samples(X)
    results=[]
    for r,score in zip(rows,scores):
        calibration=bundle['thresholds'][model].get(r['availability_mask'])
        usable=r['sufficient_evidence'] and calibration is not None
        alarm=bool(score>calibration['threshold']) if usable else None
        status=('protocol_violation' if r['protocol_violation'] else 'semantic_inconsistency' if r['rules_alarm']
                else 'insufficient_evidence' if not usable else 'ml_suspected' if alarm else 'no_alarm')
        results.append(dict(observed_at=r['observed_at'],entity=r['entity'],status=status,
            rules_alarm=r['rules_alarm'],ml_alarm=alarm,score=float(score) if usable else None,
            availability_mask=r['availability_mask'],reason='Uncalibrated mask or insufficient independent observations' if not usable else None))
    return results

def evaluate(rows,bundle):
    output={}
    for model in ['specialist','isolation']:
        scored=score_rows(rows,bundle,model);by_run=[]
        for run in sorted({r['run_id'] for r in rows}):
            pairs=[(r,s) for r,s in zip(rows,scored) if r['run_id']==run];group={}
            for label in [0,1]:
                all_rows=[(r,s) for r,s in pairs if r['label']==label];usable=[(r,s) for r,s in all_rows if s['ml_alarm'] is not None]
                group[str(label)]=dict(total=len(all_rows),scored=len(usable),abstained=len(all_rows)-len(usable),
                    ml_alarms=sum(s['ml_alarm'] for r,s in usable),rules_alarms=sum(r['rules_alarm'] for r,s in all_rows),
                    rules_alarms_on_same_scored_rows=sum(r['rules_alarm'] for r,s in usable),
                    alarm_fraction_scored=sum(s['ml_alarm'] for r,s in usable)/len(usable) if usable else None)
            by_run.append(dict(run=run,labels=group))
        output[model]=by_run
    return dict(by_model=output,notes=['Empirical window rates, not population FPR guarantees.',
        'Abstentions are separate; do not report them as true negatives.',
        'Use matched scored rows for comparisons; also report full coverage.',
        'Attack-onset/first-authentication-failure latency needs separately audited episode annotations.'])

def train(manifest,out,config_path,target_fpr=.001,minimum_runs=3,minimum_rows=1000):
    if minimum_runs<1 or minimum_rows<1 or not 0<=target_fpr<1:raise ValueError('Invalid calibration requirements')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'model.joblib').exists():raise ValueError('Refuse to overwrite a frozen model')
    parts,hashes=load_dataset(manifest);rows=parts['train'];X=matrix(rows);y=[r['label'] for r in rows]
    config_sha256=config_digest(json.loads(config_path.read_text(encoding='utf-8')))
    if any(r.get('config_sha256')!=config_sha256 for split in parts.values() for r in split):
        raise ValueError('Dataset observer configuration mismatch')
    # Explicit missing sentinel also handles features absent throughout training.
    # All physical features are nonnegative; -1 cannot mean a real zero.
    model=make_pipeline(SimpleImputer(strategy='constant',fill_value=-1,add_indicator=True,keep_empty_features=True),
        HistGradientBoostingClassifier(max_iter=150,max_leaf_nodes=7,min_samples_leaf=20,l2_regularization=2,
            learning_rate=.05,early_stopping=False,random_state=20261009))
    model.fit(X,y,histgradientboostingclassifier__sample_weight=make_weights(rows))
    honest=[r for r in rows if not r['label']]
    isolation=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
        IsolationForest(n_estimators=200,random_state=20261009,n_jobs=1))
    isolation.fit(matrix(honest))
    cal=parts['calibration'];cx=matrix(cal)
    masks={r['availability_mask'] for r in rows}
    thresholds={name:calibrate(cal,values,minimum_runs,minimum_rows,target_fpr) for name,values in
        [('specialist',model.predict_proba(cx)[:,1]),('isolation',-isolation.score_samples(cx))]}
    thresholds={name:{k:v for k,v in ts.items() if k in masks} for name,ts in thresholds.items()}
    origin=json.loads(manifest.read_text(encoding='utf-8')).get('data_origin','unspecified')
    bundle=dict(features=FEATURES,specialist=model,isolation=isolation,thresholds=thresholds,
        config_sha256=config_sha256,data_origin=origin)
    joblib.dump(bundle,out/'model.joblib')
    report=dict(sklearn=sklearn.__version__,data_origin=origin,target_empirical_fpr=target_fpr,minimum_calibration_runs=minimum_runs,
        numpy=np.__version__,joblib=joblib.__version__,
        source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ['detector.py','model.py']},
        minimum_calibration_rows=minimum_rows,thresholds=thresholds,inputs_sha256=hashes,
        dataset_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),config_sha256=bundle['config_sha256'],
        model_sha256=hashlib.sha256((out/'model.joblib').read_bytes()).hexdigest(),
        validation_status='No calibrated masks; abstain' if not thresholds['specialist'] else 'Evaluate held-out test; not a deployment certificate')
    (out/'freeze.json').write_text(json.dumps(report,indent=2))
    (out/'test-evaluation.json').write_text(json.dumps(evaluate(parts['test'],bundle),indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('train');a.add_argument('--dataset',required=True);a.add_argument('--config',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('score');a.add_argument('--features',required=True);a.add_argument('--config',required=True);a.add_argument('--model-dir',required=True);a.add_argument('--out',required=True)
    args=p.parse_args()
    if args.command=='train':print(json.dumps(train(Path(args.dataset),Path(args.out),Path(args.config)),indent=2))
    else:
        folder=Path(args.model_dir);freeze=json.loads((folder/'freeze.json').read_text());path=folder/'model.joblib'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=freeze['model_sha256']:raise ValueError('Model integrity mismatch')
        if config_digest(json.loads(Path(args.config).read_text(encoding='utf-8')))!=freeze['config_sha256']:raise ValueError('Observer configuration changed; recalibration required')
        rows=[json.loads(line) for line in Path(args.features).read_text().splitlines() if line.strip()]
        # joblib must only load a locally trusted model artifact; a matching untrusted hash is not authentication.
        results=score_rows(rows,joblib.load(path))
        Path(args.out).write_text(''.join(json.dumps(r)+'\n' for r in results))
