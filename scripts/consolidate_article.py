"""Freeze the selected experimental cohorts for the 2026-10-07 manuscript."""
import csv,hashlib,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/article-final-20261007'

def dump(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
def table(path,rows):
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def main():
    OUT.mkdir(exist_ok=True)
    inventory=[];excluded=[];cohorts=[];seen=set();inputs={}
    for stage,expected in [('main-v2-execution',60),('detector-v1',27),('robustness-v1',24),
                           ('quantization-v1',12),('delay-burst-v1',36),('timeaware-v1',24)]:
        path=ROOT/'results'/stage/'ledger.json';d=json.loads(path.read_text())
        inputs[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        selected=[]
        for result in d['results']:
            if stage=='main-v2-execution' and result['item']['series_id']!='main-v2':continue
            eligible=result.get('eligible_pair',result.get('eligible',False))
            records=result.get('records',[result])
            if not eligible:
                excluded.extend(dict(stage=stage,run=r.get('name','unknown'),reason=r.get('error',result.get('error','incomplete pair'))) for r in records)
                continue
            for r in records:
                name=r['name'];a=r['audit'];folder=ROOT/'runs'/name
                m=json.loads((folder/'manifest.json').read_text())
                assert name not in seen and a['eligible'] and all(a['checks'].values()) and m['complete']
                assert a['established']==m['actual_established']==m['expected_established']
                assert a['n']==m.get('expected_measured_creates',m['cycles']-m['warmup'])
                assert a['radio_failures']==0 and a['broken_causal_chains']==0
                seen.add(name)
                row=dict(stage=stage,run=name,seed=m['seed'],policy=m['policy'],alpha=m['alpha'],
                    active=m['active'],capacity3=m.get('capacity3') or m['capacity'],
                    heartbeat=m.get('heartbeat',1),nfm_delay_ms=m.get('nfm_delay_ms',0),burst=m.get('burst',False),
                    measured=a['n'],established=a['established'],
                    manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
                    binary_fingerprint=hashlib.sha256(json.dumps(a['binary_sha256'],sort_keys=True).encode()).hexdigest())
                inventory.append(row);selected.append(row)
        assert len(selected)==expected,(stage,len(selected))
        cohorts.append(dict(stage=stage,runs=len(selected),measured=sum(r['measured'] for r in selected),established=sum(r['established'] for r in selected)))
    assert len(inventory)==183
    table(OUT/'selected-runs.csv',inventory);table(OUT/'cohorts.csv',cohorts);dump(OUT/'excluded-attempts.json',excluded)
    effects=list(csv.DictReader((ROOT/'results/main-v2-execution/main-evaluation/effect-summary.csv').open()))
    pairs=list(csv.DictReader((ROOT/'results/main-v2-execution/main-evaluation/paired-effects.csv').open()))
    assert len(pairs)==30
    for p in pairs:assert p['honest_run'] in seen and p['attack_run'] in seen
    table(OUT/'effects.csv',effects)
    comparisons=[]
    for stage,model in [('detector-v1','residual'),('robustness-v1','residual'),('robustness-v1','residual_quantized'),('quantization-v1','residual_quantized'),('delay-burst-v1','residual_quantized')]:
        source=ROOT/'results'/stage/'evaluation.json';e=json.loads(source.read_text());inputs[str(source.relative_to(ROOT))]=hashlib.sha256(source.read_bytes()).hexdigest()
        rows=[r for r in e['by_run'] if r['model']==model]
        for scenario,policy in sorted({(r.get('scenario',r.get('cohort','')+'-a'+str(r.get('alpha',''))),r['policy']) for r in rows}):
            values=[r for r in rows if r.get('scenario',r.get('cohort','')+'-a'+str(r.get('alpha','')))==scenario and r['policy']==policy]
            comparisons.append(dict(stage=stage,model=model,scenario=scenario,policy=policy,runs=len(values),
                mean_alarm_fraction=statistics.mean(r['alarm_fraction'] for r in values),
                min_run=min(r['alarm_fraction'] for r in values),max_run=max(r['alarm_fraction'] for r in values),
                windows=sum(r['windows'] for r in values),alarms=sum(r['alarms'] for r in values)))
    e=json.loads((ROOT/'results/timeaware-v1/evaluation.json').read_text())
    for c in e['cells']:
        values=[r for r in e['by_run'] if r['item']['stage']==c['scenario'] and r['item']['policy']==c['policy']]
        comparisons.append(dict(stage='timeaware-v1',model='age_aware',scenario=c['scenario'],policy=c['policy'],runs=len(values),
            mean_alarm_fraction=c['mean_alarm_fraction'],min_run=min(r['alarms']/r['windows'] for r in values),
            max_run=max(r['alarms']/r['windows'] for r in values),windows=sum(r['windows'] for r in values),alarms=sum(r['alarms'] for r in values)))
    table(OUT/'detector-comparison.csv',comparisons)
    for name in ['scripts/age_aware_detector.py','scripts/timeaware_stage.py','scripts/run_lab.py']:
        frozen=json.loads((ROOT/'results/timeaware-v1/measurement-code.json').read_text())
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==frozen[Path(name).name]
    for name in ['results/timeaware-v1/evaluation.json',
                 'results/main-v2-execution/main-evaluation/effect-summary.csv',
                 'results/main-v2-execution/main-evaluation/paired-effects.csv',
                 'results/robustness-v1/onoff-temporal-evaluation.json',
                 'results/quantization-v1/acceptance.json']:
        inputs[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    summary=dict(cohorts=cohorts,total_runs=len(inventory),total_measured=sum(r['measured'] for r in inventory),
        total_established=sum(r['established'] for r in inventory),distinct_binary_fingerprints=len({r['binary_fingerprint'] for r in inventory}),
        excluded_attempt_records=len(excluded),checks='Selected manifests and recorded audit checks cross-validated; no re-execution of raw-trace audit.',
        primary_measurement_code_matches_frozen_hashes=True,inputs_sha256=inputs)
    dump(OUT/'summary.json',summary);print(json.dumps(summary,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
