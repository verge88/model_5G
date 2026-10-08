"""Causal SCP history-range detector; no attacker timestamps enter scores."""
import json, math
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit
from analyze import events, context_key
from evaluate_article import HOSTS

HISTORY_MS=500

def distance_to_range(reported,values):
    return max(min(values)-reported,reported-max(values),0)

def score_run(folder,features):
    manifest=json.loads((folder/'manifest.json').read_text())
    rows=sorted([e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)],key=lambda e:int(e['t']))
    rows=[e for e in rows if int(e['t'])<=manifest['observation_end_us']]
    # Lab inventory mapping only. LOAD values, times and versions are not features.
    identity={}
    for i,host in enumerate(HOSTS,1):
        ids={e['nf'] for e in rows if e['kind']=='LOAD' and e['source']==f'smf{i}.log'}
        assert len(ids)==1
        identity[next(iter(ids))]=host
    target=next(nf for nf,h in identity.items() if h==HOSTS[2])
    capacity=manifest.get('capacity3') or manifest['capacity']
    count=0;contexts={};callbacks={};reports=set();history=deque([(-math.inf,0)])
    windows={};begin=manifest['measurement_start_us'];end=manifest['measurement_end_us']
    for e in rows:
        t=int(e['t']);old=count
        if e['kind']=='SCP':
            status=int(e['status']);location=e.get('location','-')
            if status==201 and '/sm-contexts/' in location:
                key=context_key(location);host=urlsplit(key).hostname
                assert key not in contexts
                if host in HOSTS:
                    contexts[key]=host
                    if host==HOSTS[2]:count+=1
                    if e.get('callback','-')!='-':callbacks[urlsplit(e['callback']).path]=key
            if 200<=status<300:
                key=None
                if e.get('released')=='1':key=callbacks.get(urlsplit(e['uri']).path)
                elif e['uri'].endswith('/release'):key=context_key(e['uri'][:-8],e.get('target',''))
                if key in contexts:
                    if contexts.pop(key)==HOSTS[2]:count-=1
        if count!=old:history.append((t,math.floor(min(100,100*count/capacity))))
        cutoff=t-HISTORY_MS*1000
        while len(history)>1 and history[1][0]<=cutoff:history.popleft()
        if e['kind']=='NRF' and e.get('nf') in identity:
            reports.add(e['nf'])
            if e['nf']==target and len(reports)==3 and begin<=t<=end:
                reported=float(e['stored']);current=math.floor(min(100,100*count/capacity))
                score=distance_to_range(reported,[v for _,v in history])
                window=int((t-begin)//10000000)
                values=windows.setdefault(window,dict(age_aware=0,baseline=0,samples=0))
                values['age_aware']=max(values['age_aware'],score)
                values['baseline']=max(values['baseline'],abs(reported-current))
                values['samples']+=1
    selected=[]
    for f in features:
        value=windows[f['window']]
        assert math.isclose(value['baseline'],f['residual_quantized'],abs_tol=1e-9),'Baseline replay mismatch'
        assert value['age_aware']<=value['baseline']+1e-9
        selected.append(dict(window=f['window'],**value))
    return dict(run=folder.name,history_ms=HISTORY_MS,threshold=0,windows=len(selected),
                alarms=sum(v['age_aware']>0 for v in selected),
                baseline_alarms=sum(v['baseline']>0 for v in selected),window_scores=selected)
