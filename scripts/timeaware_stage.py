"""Prospective age-aware detector validation, fixed 500 ms trusted history bound."""
import json,statistics
import robustness_stage as engine
from delay_burst_stage import validate_delay
from age_aware_detector import score_run

def plan():
    return [dict(stage=('honest-' if alpha==0 else 'attack-')+tag,policy=policy,rho=.5,seed=seed,alpha=alpha,
                 extra=['--nfm-delay-ms','200']+(['--burst','--ues','222'] if tag=='combined' else []))
            for seed in [1001,1002,1003] for tag in ['delay','combined']
            for alpha in [0,.25] for policy in ['swrr','random']]

base_execute=engine.execute
def execute(item,worker,attempt,state_dir=None,series=None):
    result=base_execute(item,worker,attempt,state_dir,series)
    if result['eligible']:
        folder=engine.ROOT/'runs'/result['name']
        result['delay_validation']=validate_delay(folder)
        features=json.loads((state_dir/(result['name']+'.features.json')).read_text())
        scored=score_run(folder,features)
        engine.write(state_dir/(result['name']+'.timeaware.json'),scored)
        result['timeaware']={k:v for k,v in scored.items() if k!='window_scores'}
    return result

def summarize(state):
    rows=[dict(item=r['item'],**r['timeaware']) for r in state['results'] if r['eligible']]
    cells=[]
    for scenario in ['honest-delay','attack-delay','honest-combined','attack-combined']:
        for policy in ['swrr','random']:
            selected=[r for r in rows if r['item']['stage']==scenario and r['item']['policy']==policy]
            if not selected:continue
            mean=statistics.mean(r['alarms']/r['windows'] for r in selected)
            cells.append(dict(scenario=scenario,policy=policy,runs=len(selected),mean_alarm_fraction=mean,
                baseline_mean=statistics.mean(r['baseline_alarms']/r['windows'] for r in selected),
                decision='incomplete' if len(selected)!=3 else ('pass' if
                    (mean<=.01 if scenario.startswith('honest') else mean>=.95) else 'fail')))
    engine.write(engine.STATE/'evaluation.json',dict(primary='age_aware',history_ms=500,threshold=0,
        complete=len(rows)==24,by_run=rows,cells=cells,
        limitations=['500 ms is a configured trusted upper-age assumption, not inferred from attacker timestamps.',
                     'Prior-data replay was development; only seeds 1001-1003 are prospective validation.',
                     'Offline replay uses a common monotonic clock; collector delay, clock skew and larger report ages remain untested.',
                     'A larger history range can conceal attacks; only alpha=.25 and this workload are tested.',
                     'Empirical three-run acceptance is not a population error-rate guarantee.']))

if __name__=='__main__':
    engine.STATE=engine.ROOT/'results/timeaware-v1';engine.SERIES='timeaware-v1'
    engine.plan=plan;engine.execute=execute;engine.summarize=summarize
    engine.main()
