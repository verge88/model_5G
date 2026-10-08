"""Post-hoc temporal validation of existing on/off traces; no threshold tuning."""
import bisect
import json
import math
import statistics
from pathlib import Path
from urllib.parse import urlsplit
from analyze import events, context_key
from evaluate_article import HOSTS, quantile

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/robustness-v1'

def distribution(values):
    return dict(n=len(values),median=statistics.median(values) if values else None,
                p95=quantile(values,.95) if values else None,max=max(values) if values else None)

def analyze(name, thresholds):
    folder=ROOT/'runs'/name
    meta=json.loads((folder/'manifest.json').read_text())
    begin=meta['measurement_start_us'];end=meta['measurement_end_us']
    rows=sorted([e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)],key=lambda e:int(e['t']))
    rows=[e for e in rows if int(e['t'])<=meta['observation_end_us']]
    identity={}
    for i,host in enumerate(HOSTS,1):
        ids={e['nf'] for e in rows if e['source']==f'smf{i}.log' and e['kind']=='LOAD'}
        assert len(ids)==1
        identity[next(iter(ids))]=host
    target=next(nf for nf,h in identity.items() if h==HOSTS[2])
    loads=[e for e in rows if e['kind']=='LOAD' and e.get('nf')==target]
    truth={e['version']:e for e in loads}
    transitions=[]
    for e in loads:
        state=(int(e['version'])//30)%2
        if not transitions or transitions[-1]['active']!=state:
            transitions.append(dict(t=int(e['t']),active=state))
    times=[e['t'] for e in transitions]
    def active_at(t):
        index=bisect.bisect_right(times,t)-1
        assert index>=0
        return transitions[index]['active']
    counts={h:0 for h in HOSTS};contexts={};callbacks={};reports={};samples=[]
    for e in rows:
        t=int(e['t'])
        if e['kind']=='SCP':
            status=int(e['status']);location=e.get('location','-')
            if status==201 and '/sm-contexts/' in location:
                key=context_key(location);host=urlsplit(key).hostname
                assert key not in contexts
                if host in counts:
                    contexts[key]=host;counts[host]+=1
                    if e.get('callback','-')!='-':callbacks[urlsplit(e['callback']).path]=key
            if 200<=status<300:
                key=None
                if e.get('released')=='1':key=callbacks.get(urlsplit(e['uri']).path)
                elif e['uri'].endswith('/release'):key=context_key(e['uri'][:-8],e.get('target',''))
                if key in contexts:counts[contexts.pop(key)]-=1
        elif e['kind']=='NRF' and e.get('nf') in identity:
            reports[identity[e['nf']]]=float(e['stored'])
            if begin<=t<=end and e['nf']==target and len(reports)==3:
                observed=min(100,100*counts[HOSTS[2]]/(meta.get('capacity3') or meta['capacity']))
                # Scores use only SCP and NRF. LOAD/version is evaluation truth only.
                load=truth[e['version']]
                assert int(load['t'])<=t
                samples.append(dict(t=t,window=int((t-begin)//10000000),
                    active=(int(e['version'])//30)%2,origin=int(load['t']),
                    residual=abs(float(e['stored'])-observed),
                    residual_quantized=abs(float(e['stored'])-math.floor(observed))))
    features=json.loads((STATE/(name+'.features.json')).read_text())
    result=dict(run=name,policy=meta['policy'],seed=meta['seed'],models={})
    for model in ['residual','residual_quantized']:
        tau=thresholds[model];windows=[]
        for f in features:
            start=begin+f['window']*10000000;finish=start+10000000
            selected=[s for s in samples if s['window']==f['window']]
            assert selected and math.isclose(max(s[model] for s in selected),f[model],abs_tol=1e-9)
            mixed=any(start<x['t']<finish for x in transitions)
            label='mixed' if mixed else ('on' if active_at(start) else 'off')
            windows.append(dict(start=start,end=finish,label=label,alarm=f[model]>tau,
                active_alarm=any(s['active'] and s[model]>tau for s in selected)))
        groups={label:dict(windows=len(v:=[w for w in windows if w['label']==label]),
                           alarms=sum(w['alarm'] for w in v)) for label in ['on','off','mixed']}
        event_groups={label:dict(samples=len(v:=[s for s in samples if s['active']==active]),
                    alarms=sum(s[model]>tau for s in v)) for label,active in [('on',1),('off',0)]}
        episodes=[];clearing=[];censored=0
        for index,transition in enumerate(transitions):
            if not begin<=transition['t']<end:continue
            next_t=transitions[index+1]['t'] if index+1<len(transitions) else end+1
            if next_t>end:
                censored+=1;continue
            if transition['active']:
                hits=[s for s in samples if transition['t']<=s['origin']<next_t and s['active'] and s[model]>tau]
                decisions=[w for w in windows if transition['t']<w['end']<=next_t and w['active_alarm']]
                episodes.append(dict(onset=transition['t'],offset=next_t,
                    first_observation_ms=(hits[0]['t']-transition['t'])/1000 if hits else None,
                    window_decision_seconds=(decisions[0]['end']-transition['t'])/1e6 if decisions else None))
            else:
                clear=[w for w in windows if w['start']>=transition['t'] and w['end']<=next_t and not w['alarm']]
                clearing.append((clear[0]['end']-transition['t'])/1e6 if clear else None)
        result['models'][model]=dict(threshold=tau,windows=groups,events=event_groups,episodes=episodes,
            complete_on_episodes=len(episodes),missed_window_episodes=sum(e['window_decision_seconds'] is None for e in episodes),
            observation_latency_ms=distribution([e['first_observation_ms'] for e in episodes if e['first_observation_ms'] is not None]),
            window_latency_seconds=distribution([e['window_decision_seconds'] for e in episodes if e['window_decision_seconds'] is not None]),
            clearing_seconds=distribution([v for v in clearing if v is not None]),
            uncleared_off_episodes=sum(v is None for v in clearing),right_censored_intervals=censored)
    return result

def main():
    ledger=json.loads((STATE/'ledger.json').read_text())
    runs=[r['name'] for r in ledger['results'] if r['eligible'] and r['item']['stage']=='attack-onoff']
    assert len(runs)==6
    thresholds=json.loads((STATE/'frozen-thresholds.json').read_text())['thresholds']
    results=[]
    for name in runs:
        results.append(analyze(name,thresholds));print('VERIFIED',name,flush=True)
    aggregate={}
    for model in ['residual','residual_quantized']:
        data=[r['models'][model] for r in results]
        aggregate[model]=dict(
            windows={label:{key:sum(d['windows'][label][key] for d in data) for key in ['windows','alarms']} for label in ['on','off','mixed']},
            events={label:{key:sum(d['events'][label][key] for d in data) for key in ['samples','alarms']} for label in ['on','off']},
            complete_on_episodes=sum(d['complete_on_episodes'] for d in data),
            missed_window_episodes=sum(d['missed_window_episodes'] for d in data),
            observation_latency_ms=distribution([e['first_observation_ms'] for d in data for e in d['episodes'] if e['first_observation_ms'] is not None]),
            window_latency_seconds=distribution([e['window_decision_seconds'] for d in data for e in d['episodes'] if e['window_decision_seconds'] is not None]))
    output=dict(by_run=results,aggregate=aggregate,limitations=[
        'Post-hoc trace replay, not an online deployed detector.',
        'Latency starts at the first malicious load computation; observation latency excludes log collection and detector runtime.',
        'Window decisions occur at the close of the existing non-overlapping 10-second windows.',
        'Mixed transition windows are separate; complete episodes only, boundaries censored.',
        'LOAD version labels evaluation truth only; scores reproduce existing SCP/NRF features exactly.',
        'Quantization-aware score was a pre-existing secondary detector; promoting it requires prospective validation.',
        'Episodes within six runs are dependent; no independent-episode confidence claim.'])
    (STATE/'onoff-temporal-evaluation.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(aggregate,indent=2))

if __name__=='__main__':main()
