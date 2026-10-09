"""Retrospective selection of a causal memory-reset threshold."""
import bisect,hashlib,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from analyze import events
OUT=ROOT/'results/reset-v1'

def predict(values,threshold):
    last=None;result=[]
    for v in values:
        if v['age_aware']>0:last=v['window'];alarm=True
        else:
            if v['x'][0]<=threshold:last=None
            alarm=last is not None and v['window']-last<=2
        result.append(bool(alarm))
    return result

def labels(folder,values):
    m=json.loads((folder/'manifest.json').read_text());begin=m['measurement_start_us']
    rows=sorted([e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)],key=lambda e:int(e['t']))
    loads=[e for e in rows if e['kind']=='LOAD' and e['source']=='smf3.log'];truth={e['version']:e for e in loads}
    ids={e['nf'] for e in loads};assert len(ids)==1;target=next(iter(ids));states=[]
    for e in rows:
        if e['kind']=='NRF' and e.get('nf')==target:
            active=float(e['stored'])<math.floor(float(truth[e['version']]['reference']))
            if not states or active!=states[-1][1]:states.append((int(e['t']),active))
    times=[t for t,a in states];result=[]
    for v in values:
        start=begin+v['window']*1e7;finish=start+1e7;i=bisect.bisect_right(times,start)-1;assert i>=0
        mixed=bisect.bisect_left(times,finish)>bisect.bisect_right(times,start)
        result.append('mixed' if mixed else ('on' if states[i][1] else 'off'))
    return result

def main():
    OUT.mkdir(exist_ok=True);cache=OUT/'development-data.json';data=[];hashes={}
    for series,phase in [('specialist-v1','test'),('intermittent-v1','')]:
        folder=ROOT/'results'/series/phase
        for r in json.loads((folder/'ledger.json').read_text())['results']:
            if not r['eligible']:continue
            path=folder/(r['name']+('.specialist.json' if phase else '.scores.json'))
            values=json.loads(path.read_text())['values'];tag=r['item']['stage']
            ls=labels(ROOT/'runs'/r['name'],values) if tag=='onoff' else ['off' if tag=='honest' else 'on']*len(values)
            data.append(dict(run=r['name'],series=series,tag=tag,policy=r['item']['policy'],values=values,labels=ls))
            hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
            print('LOADED',r['name'],flush=True)
    cache.write_text(json.dumps(data))
    summaries=[]
    for threshold in [0,.25,.5,.75,1,1.5,2]:
        by_run=[]
        for r in data:
            pred=predict(r['values'],threshold)
            for label in ['on','off']:
                idx=[i for i,l in enumerate(r['labels']) if l==label]
                if idx:by_run.append(dict(run=r['run'],tag=r['tag'],label=label,windows=len(idx),
                    fraction=sum(pred[i] for i in idx)/len(idx),baseline=sum(r['values'][i]['age_aware']>0 for i in idx)/len(idx)))
        select=lambda tag,label:statistics.mean(x['fraction'] for x in by_run if x['tag']==tag and x['label']==label)
        gain=select('budget','on')-statistics.mean(x['baseline'] for x in by_run if x['tag']=='budget')
        summaries.append(dict(threshold=threshold,honest=select('honest','off'),off=select('onoff','off'),
            on=select('onoff','on'),budget=select('budget','on'),budget_gain=gain,by_run=by_run))
    eligible=[s for s in summaries if s['honest']<=.01 and s['off']<=.01 and s['on']>=.95]
    best=max(eligible,key=lambda s:(s['budget_gain'],-s['threshold'])) if eligible else None
    result=dict(candidates=summaries,selected=best,source_sha256=hashes,
        selection='Among honest<=1%, off<=1%, on>=95%, maximize constant-attack gain; ties choose smaller threshold.',
        note='Previously inspected cohorts used for development only; not independent evidence.')
    (OUT/'development.json').write_text(json.dumps(result,indent=2))
    print(json.dumps([{k:v for k,v in s.items() if k!='by_run'} for s in summaries],indent=2))
    print('SELECTED',None if best is None else best['threshold'])

if __name__=='__main__':main()
