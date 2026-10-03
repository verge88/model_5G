"""Real-run audit, independent-SCP features, paired effects and pilot detectors.

No SMF active/reference value enters detector features. NF UUIDs are joined to
the experimental node inventory only. Ground truth is a separate audit.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
from urllib.parse import urlsplit
from analyze import events, context_key, propagation
from theory import stationary_share

HOSTS=['127.0.0.4','127.0.0.32','127.0.0.33']

def quantile(values,q):
    xs=sorted(values)
    if not xs:return None
    p=(len(xs)-1)*q;i=int(p)
    return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(p-i)

def write_csv(path,rows):
    if not rows:
        path.unlink(missing_ok=True)
        return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader();writer.writerows(rows)

def audit(folder):
    m=json.loads((folder/'manifest.json').read_text())
    rows=sorted([e for p in folder.glob('*.log') for e in events(p)],key=lambda x:int(x['t']))
    rows=[e for e in rows if int(e['t'])<=m.get('observation_end_us',math.inf)]
    sent={(e['nf'],e.get('version')):int(e['load']) for e in rows if e['kind']=='SEND'}
    send_times={(e['nf'],e.get('version')):int(e['t']) for e in rows if e['kind']=='SEND'}
    stored={(e['nf'],e.get('version')):e for e in rows if e['kind']=='NRF'}
    mismatch=[e for e in rows if e['kind']=='CANDIDATE' and
              sent.get((e['nf'],e.get('version')))!=int(e['load'])]
    broken_chain=[]
    for e in rows:
        if e['kind']!='CANDIDATE':continue
        key=e['nf'],e.get('version');nrf=stored.get(key)
        if not nrf or int(nrf['stored'])!=int(e['load']) or not (
                send_times.get(key,math.inf)<=int(nrf['t'])<=int(e['t'])):
            broken_chain.append(e)
    identity={}
    for i,host in enumerate(HOSTS,1):
        ids={e['nf'] for e in rows if e['source']==f'smf{i}.log' and e['kind']=='LOAD'}
        if len(ids)==1:identity[next(iter(ids))]=host
    begin=m.get('measurement_start_us',math.inf);end=m.get('measurement_end_us',0)
    active={};callbacks={};counts={h:0 for h in HOSTS};assigned={h:0 for h in HOSTS}
    created={h:0 for h in HOSTS};released={h:0 for h in HOSTS};reports={};caps={h:100 for h in HOSTS}
    anomalies=[];windows={};active_samples=[];truth_differences=[];saturated=0;load_samples=0
    for e in rows:
        t=int(e['t']);kind=e['kind']
        if kind=='SCP':
            status=int(e['status']);location=e.get('location','-')
            if status==201 and '/sm-contexts/' in location:
                key=context_key(location);host=urlsplit(key).hostname
                if key in active:anomalies.append('duplicate_create')
                elif host in counts:
                    active[key]=host;counts[host]+=1;created[host]+=1
                    if begin<=t<=end:assigned[host]+=1
                    if e.get('callback','-')!='-':callbacks[urlsplit(e['callback']).path]=key
            if 200<=status<300:
                key=None
                if e.get('released')=='1':key=callbacks.get(urlsplit(e['uri']).path)
                elif e['uri'].endswith('/release'):
                    key=context_key(e['uri'][:-8],e.get('target',''))
                if key in active:
                    host=active.pop(key);counts[host]-=1;released[host]+=1
        elif kind=='NRF' and e.get('nf') in identity:
            reports[identity[e['nf']]]=float(e['stored'])
        elif kind=='CANDIDATE' and e.get('nf') in identity:
            caps[identity[e['nf']]]=int(e['capacity'])
        elif kind=='LOAD' and e.get('nf') in identity:
            host=identity[e['nf']]
            # Separate ground truth audit; never fed back into scores.
            truth_differences.append(int(e['active'])-counts[host])
            load_samples+=1
            capacity=(m.get('capacity3') or m['capacity']) if host==HOSTS[2] else m['capacity']
            saturated+=int(int(e['active'])>=capacity)
        if begin<=t<=end:
            active_samples.append(sum(counts.values()))
            window=int((t-begin)//10_000_000)
            state=windows.setdefault(window,{'residual':[],'residual_quantized':[],'nrf_only':[],'peer':[],
                                              'capacity':[],'assignments':{h:0 for h in HOSTS},'t':t})
            if kind=='SCP' and int(e['status'])==201 and '/sm-contexts/' in e.get('location',''):
                host=urlsplit(e['location']).hostname
                if host in HOSTS:state['assignments'][host]+=1
            if kind=='NRF' and e.get('nf')==next((nf for nf,h in identity.items() if h==HOSTS[2]),None) and len(reports)==3:
                observed=[min(100,100*counts[h]/(m.get('capacity3') or m['capacity']
                            if h==HOSTS[2] else m['capacity'])) for h in HOSTS]
                reported=[reports[h] for h in HOSTS]
                state['residual'].append(abs(reported[2]-observed[2]))
                state['residual_quantized'].append(abs(reported[2]-math.floor(observed[2])))
                state['nrf_only'].append(abs(reported[2]-statistics.median(reported[:2])))
                state['peer'].append(abs((reported[2]-statistics.median(reported[:2]))-
                                        (observed[2]-statistics.median(observed[:2]))))
                state['capacity'].append(abs(caps[HOSTS[2]]-100))
    metric_counts={}
    for i,h in enumerate(HOSTS,1):
        text=(folder/f'smf{i}-metrics.txt').read_text()
        metric_counts[h]=sum(float(x) for x in re.findall(r'^fivegs_smffunction_sm_sessionnbr\{[^\n]*\} ([-\d.e+]+)$',text,re.M))
    ue_text=(folder/'ue.stdout').read_text(errors='replace')
    established=ue_text.count('PDU Session establishment is successful')
    workload=[json.loads(x) for x in (folder/'workload.jsonl').read_text().splitlines()]
    planned=[(e['ue'],e['command']) for e in workload if e['command']!='ps-list']
    h=hashlib.sha256(json.dumps(planned).encode()).hexdigest()
    radio_failures=ue_text.count('Radio link failure detected')
    checks={'complete':bool(m['complete']),'three_smf_ids':len(identity)==3,
            'all_creates_confirmed':sum(created.values())==established==m['expected_established'],
            'final_scp_matches_metrics':counts==metric_counts,'final_population':sum(counts.values())==m['active'],
            'no_duplicate_creates':not anomalies,'measured_population':sum(assigned.values())==m['cycles']-m.get('warmup',0),
            'all_candidates_present':sum(e['kind']=='CANDIDATE' for e in rows)==3*m['expected_established'],
            'all_selections_present':sum(e['kind']=='SELECT' for e in rows)==m['expected_established'],
            'versions_match':not mismatch,'causal_nrf_chain':not broken_chain,'no_radio_failure':radio_failures==0}
    eligible=all(checks.values())
    feature_rows=[]
    for window,w in sorted(windows.items()):
        n=sum(w['assignments'].values())
        if not w['residual'] or n<5 or begin+(window+1)*10_000_000>end:continue
        residual=max(w['residual']);cap=max(w['capacity'])
        feature_rows.append({'run':folder.name,'window':window,'seed':m['seed'],'policy':m['policy'],
            'rho':m['active']/(3*m['capacity']),'alpha':m['alpha'],
            'attack_mode':m.get('attack_mode','constant'),'residual_budget':m.get('residual_budget'),
            'capacity_reported':m.get('reported_capacity',100),
            'attack':int(m['alpha']>0 or m.get('reported_capacity',100)!=100),
            'calibration':int('-cal-' in folder.name),'nrf_only':max(w['nrf_only']),
            'scp_only':100*abs(w['assignments'][HOSTS[2]]/n-1/3),
            'residual':residual,'nrf_scp':max(residual,cap),'full_peer':max(residual,cap,max(w['peer'])),
            'residual_quantized':max(w['residual_quantized']),
            'assignments':n})
    total=sum(assigned.values())
    result={'run':folder.name,'eligible':eligible,'started':m['started'],'seed':m['seed'],'policy':m['policy'],
            'rho':m['active']/(3*m['capacity']),'alpha':m['alpha'],'capacity_reported':m.get('reported_capacity',100),
            'residual_budget':m.get('residual_budget'),'attack_mode':m.get('attack_mode','constant'),
            'capacity3':m.get('capacity3') or m['capacity'],
            'workload_hash':h,'n':total,'s3':assigned[HOSTS[2]]/total if total else None,
            'assigned':assigned,'scp_active':counts,'ground_truth_sessionnbr':metric_counts,
            'established':established,'anomalies':anomalies,
            'candidate_version_mismatches':len(mismatch),
            'checks':checks,'broken_causal_chains':len(broken_chain),'radio_failures':radio_failures,
            'rls_heartbeat_threshold_ms':m.get('rls_heartbeat_threshold_ms',2000),
            'execution_worker':m.get('execution_worker','sequential'),
            'load_samples':load_samples,'saturated_load_samples':saturated,
            'max_abs_scp_ground_truth_difference':max(map(abs,truth_differences),default=None),
            'mean_event_sampled_active':statistics.mean(active_samples) if active_samples else None,
            'propagation':{k:v for k,v in propagation(rows).items() if k!='chains'}}
    (folder/'audit.json').write_text(json.dumps(result,indent=2))
    return result,feature_rows

def evaluate(root,out,prefix):
    out.mkdir(parents=True,exist_ok=True)
    runs=[];features=[]
    for folder in sorted((root/'runs').glob(prefix+'*')):
        if not (folder/'manifest.json').exists():continue
        m=json.loads((folder/'manifest.json').read_text())
        if not m.get('complete'):continue
        a,f=audit(folder);runs.append(a)
        if a['eligible']:features+=f
    pairs_by_key={}
    for a in runs:
        if not a['eligible'] or a['alpha']!=.5 or a['capacity_reported']!=100 or a['residual_budget'] is not None or a['attack_mode']!='constant':continue
        benign=[b for b in runs if b['eligible'] and b['alpha']==0 and b['seed']==a['seed'] and b['policy']==a['policy'] and b['rho']==a['rho'] and b['capacity_reported']==100]
        if not benign:continue
        def environment(r):return r['rls_heartbeat_threshold_ms'],r['execution_worker']=='sequential'
        matched=[b for b in benign if environment(b)==environment(a)]
        b=max(matched or benign,key=lambda r:r['started'])
        if a['workload_hash']!=b['workload_hash']:raise ValueError('Paired workload mismatch')
        pair={'policy':a['policy'],'rho':a['rho'],'seed':a['seed'],'honest_s3':b['s3'],
                      'attack_s3':a['s3'],'delta_pp':100*(a['s3']-b['s3']),
                      'theory_delta_pp':100*(stationary_share(a['rho'],.5)-1/3),
                      'comparable':bool(matched),'honest_run':b['run'],'attack_run':a['run'],'attack_started':a['started']}
        key=a['policy'],a['rho'],a['seed'];previous=pairs_by_key.get(key)
        if previous is None or (pair['comparable'],pair['attack_started'])>(previous['comparable'],previous['attack_started']):
            pairs_by_key[key]=pair
    pairs=list(pairs_by_key.values())
    comparable=[p for p in pairs if p['comparable']]
    effects=[]
    for policy,rho in sorted(set((p['policy'],p['rho']) for p in comparable)):
        values=[p['delta_pp'] for p in comparable if p['policy']==policy and p['rho']==rho]
        rng=random.Random(731);means=[statistics.mean(rng.choices(values,k=len(values))) for _ in range(10000)]
        effects.append({'policy':policy,'rho':rho,'independent_pairs':len(values),'delta_pp':statistics.mean(values),
                        'bootstrap_low':quantile(means,.025) if len(values)>=3 else None,
                        'bootstrap_high':quantile(means,.975) if len(values)>=3 else None,
                        'inference':'exploratory; very few clusters' if len(values)<10 else 'run-bootstrap',
                        'theory_delta_pp':100*(stationary_share(rho,.5)-1/3)})
    models=['nrf_only','scp_only','residual','residual_quantized','nrf_scp','full_peer'];thresholds={};detection=[]
    for model in models:
        calibration=[f[model] for f in features if f['calibration'] and not f['attack']]
        if not calibration:continue
        tau=quantile(calibration,.99);thresholds[model]=tau
        for f in features:
            if f['calibration']:continue
            detection.append({'model':model,'run':f['run'],'window':f['window'],'attack':f['attack'],
                              'policy':f['policy'],'rho':f['rho'],
                              'primary_attack':int(f['alpha']==.5 and f['attack_mode']=='constant' and
                                  f['residual_budget'] is None and f['capacity_reported']==100),
                              'score':f[model],'threshold':tau,'alarm':int(f[model]>tau)})
    metrics=[]
    by_run=[]
    for model,run in sorted(set((d['model'],d['run']) for d in detection)):
        ds=[d for d in detection if d['model']==model and d['run']==run]
        meta=next(r for r in runs if r['run']==run)
        by_run.append({'model':model,'run':run,'attack':ds[0]['attack'],
                       'windows':len(ds),'alarm_fraction':statistics.mean(d['alarm'] for d in ds),
                       'rho':meta['rho'],'alpha':meta['alpha'],'policy':meta['policy'],
                       'seed':meta['seed'],'residual_budget':meta['residual_budget'],
                       'capacity_reported':meta['capacity_reported'],'attack_mode':meta['attack_mode'],
                       's3':meta['s3']})
    for model in models:
        test=[d for d in detection if d['model']==model]
        normal=[d for d in test if not d['attack']];attack=[d for d in test if d['primary_attack']]
        metrics.append({'model':model,'calibrated_threshold':thresholds.get(model),
                        'benign_windows':len(normal),'attack_windows':len(attack),
                        'empirical_fpr':statistics.mean(d['alarm'] for d in normal) if normal else None,
                        'empirical_pd':statistics.mean(d['alarm'] for d in attack) if attack else None,
                        'false_alarm_windows_per_hour':360*statistics.mean(d['alarm'] for d in normal) if normal else None,
                        'test_runs':len({d['run'] for d in test}),
                        'note':'Pd: constant alpha=.5 only; nominal calibration quantile 99%; test FPR measured, not guaranteed 1%'} )
    write_csv(out/'paired-effects.csv',pairs);write_csv(out/'effect-summary.csv',effects)
    write_csv(out/'features.csv',features);write_csv(out/'predictions.csv',detection);write_csv(out/'detectors.csv',metrics)
    write_csv(out/'detectors-by-run.csv',by_run)
    by_policy=[]
    for policy in ['swrr','random']:
        for model in models:
            ds=[d for d in detection if d['policy']==policy and d['model']==model]
            normal=[d for d in ds if not d['attack']];positive=[d for d in ds if d['primary_attack']]
            by_policy.append({'policy':policy,'model':model,'benign_windows':len(normal),'attack_windows':len(positive),
                              'empirical_fpr':statistics.mean(d['alarm'] for d in normal) if normal else None,
                              'empirical_pd':statistics.mean(d['alarm'] for d in positive) if positive else None,
                              'calibration_policy':'swrr'})
    write_csv(out/'detectors-by-policy.csv',by_policy)
    (out/'audit.json').write_text(json.dumps({'runs':runs,'effects':effects,'detectors':metrics,'thresholds':thresholds},indent=2))
    print(json.dumps({'runs':len(runs),'eligible':sum(r['eligible'] for r in runs),'pairs':len(pairs),'windows':len(features)},indent=2))
    if root==Path(__file__).resolve().parents[1]:
        from report_article import main as update_manuscript
        update_manuscript()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--prefix',default='article-20261001-');p.add_argument('--out',type=Path)
    a=p.parse_args();evaluate(a.root,a.out or a.root/'results/article-evaluation',a.prefix)
