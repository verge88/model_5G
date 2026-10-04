"""Descriptive occupancy and selection stability; never calls windows replicates."""
from bisect import bisect_right
import json, statistics
from pathlib import Path
from analyze import events
ROOT=Path(__file__).resolve().parents[1]

def diagnostic(folder):
    m=json.loads((folder/'manifest.json').read_text())
    paths=list(folder.glob('*.log'))+list(folder.glob('*.log.gz'))
    rows=sorted((e for p in paths for e in events(p)),key=lambda e:int(e['t']))
    creates=[e for e in rows if e['kind']=='SCP' and int(e['status'])==201 and '/sm-contexts/' in e.get('location','')]
    replacement=creates[m['active']:]
    times=[int(e['t']) for e in replacement]
    blocks={}
    for e in rows:
        if e['kind']!='LOAD' or e['source'] not in ['smf1.log','smf2.log','smf3.log']:continue
        index=bisect_right(times,int(e['t']))
        if index<=0 or index>m['cycles']:continue
        block=(index-1)//300
        blocks.setdefault(block,{}).setdefault(e['source'],[]).append(int(e['active']))
    summaries=[]
    for block,values in sorted(blocks.items()):
        subset=replacement[block*300:(block+1)*300]
        summaries.append(dict(first_replacement=block*300+1,last_replacement=min((block+1)*300,m['cycles']),
                              mean_active={k:statistics.mean(v) for k,v in values.items()},
                              s3=sum('127.0.0.33:' in e['location'] for e in subset)/len(subset)))
    def contrast(warmup):
        early=[b for b in summaries if warmup<b['first_replacement']<=warmup+600]
        late=summaries[-2:]
        return {node:statistics.mean(b['mean_active'][node] for b in early)-
                statistics.mean(b['mean_active'][node] for b in late) for node in ['smf1.log','smf2.log','smf3.log']}
    return dict(run=folder.name,policy=m['policy'],alpha=m['alpha'],blocks=summaries,
                early_minus_late_active_300=contrast(300),early_minus_late_active_1200=contrast(1200))

if __name__=='__main__':
    folders=sorted((ROOT/'runs').glob('main-v2-preparation-*-attempt*'))
    reports=[diagnostic(f) for f in folders if json.loads((f/'manifest.json').read_text()).get('complete')]
    result={'runs':reports,'criterion':'Descriptive screen: each node early/late mean occupancy differs by <= 5 sessions. Not a statistical proof of stationarity.',
            'threshold_sessions':5,'required_runs':4}
    (ROOT/'results/main-v2-execution/warmup-diagnostics.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
