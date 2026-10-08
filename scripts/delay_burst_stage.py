"""Frozen-threshold validation with real NFM transport delay and population steps."""
import json,statistics
from pathlib import Path
import robustness_stage as engine
from analyze import events

def plan():
    scenarios=[('delay',['--nfm-delay-ms','200']),
               ('burst',['--burst','--ues','222']),
               ('combined',['--nfm-delay-ms','200','--burst','--ues','222'])]
    return [dict(stage=('honest-' if alpha==0 else 'attack-')+tag,policy=policy,rho=.5,
                 seed=seed,alpha=alpha,extra=extra)
            for seed in [701,702,703] for tag,extra in scenarios
            for alpha in [0,.25] for policy in ['swrr','random']]

def validate_delay(folder):
    rows=[e for p in list(folder.glob('*.log'))+list(folder.glob('*.log.gz')) for e in events(p)]
    ids={e['nf'] for e in rows if e['kind']=='LOAD' and e['source']=='smf3.log'}
    assert len(ids)==1
    nf=next(iter(ids));sent={e['version']:int(e['t']) for e in rows if e['kind']=='SEND' and e.get('nf')==nf}
    m=json.loads((folder/'manifest.json').read_text())
    delays=[(int(e['t'])-sent[e['version']])/1000 for e in rows
            if e['kind']=='NRF' and e.get('nf')==nf and e['version'] in sent
            and m['measurement_start_us']<=int(e['t'])<=m['measurement_end_us']]
    assert len(delays)>=5,'Insufficient delay samples'
    result=dict(samples=len(delays),median_ms=statistics.median(delays),min_ms=min(delays),max_ms=max(delays))
    assert result['median_ms']>=150,'NFM update bypassed delay proxy'
    return result

base_execute=engine.execute
def execute(item,worker,attempt,state_dir=None,series=None):
    result=base_execute(item,worker,attempt,state_dir,series)
    if result['eligible'] and '--nfm-delay-ms' in item['extra']:
        result['delay_validation']=validate_delay(engine.ROOT/'runs'/result['name'])
    return result

base_summarize=engine.summarize
def summarize(state):
    base_summarize(state)
    path=engine.STATE/'evaluation.json';data=json.loads(path.read_text())
    data.update(primary='residual_quantized',interpretation='Frozen threshold tested under NFM chunk delay and/or stepped population.',
        limitations=['Delay proxy affects all SMF3-to-NRF bytes, including registration; reverse direction has no intentional delay.',
                     '200 ms per forwarded read chunk, not a guaranteed per-message latency; measured SEND-to-NRF delay is audited.',
                     'Population steps execute serial real UE operations, not instantaneous jumps.',
                     'Three seeds per condition; exploratory run-level evidence, not deployment guarantees.'])
    engine.write(path,data)

if __name__=='__main__':
    engine.STATE=engine.ROOT/'results/delay-burst-v1'
    engine.SERIES='delay-burst-v1'
    engine.plan=plan;engine.execute=execute;engine.summarize=summarize
    engine.main()
