"""One stage-1 precision assessment, without optional-stopping claims."""
import csv,json,math,random,statistics
from pathlib import Path
from evaluate_article import quantile
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def assess(rows):
    groups=[];ready=True
    for policy in ['swrr','random']:
        for rho in [.2,.5,.7]:
            values=[float(r['delta_pp']) for r in rows if r['policy']==policy and float(r['rho'])==rho and 101<=int(r['seed'])<=105]
            seeds=[int(r['seed']) for r in rows if r['policy']==policy and float(r['rho'])==rho and 101<=int(r['seed'])<=105]
            if len(seeds)!=len(set(seeds)):raise ValueError('Duplicate independent seed')
            cell=dict(policy=policy,rho=rho,pairs=len(values),target_pairs=5)
            if len(values)!=5:
                ready=False;cell['decision']='insufficient_first_stage'
            else:
                rng=random.Random(731)
                means=[statistics.mean(rng.choices(values,k=5)) for _ in range(10000)]
                low,high=quantile(means,.025),quantile(means,.975)
                width=(high-low)/2;sd=statistics.stdev(values)
                raw_n=max(3,math.ceil((1.96*sd)**2))
                cell.update(mean_pp=statistics.mean(values),bootstrap_95_low=low,bootstrap_95_high=high,
                            half_width_pp=width,sd_pp=sd,decision='precision_reached' if width<=1 else 'independent_confirmation',
                            additional_pairs=0 if width<=1 else min(5,raw_n),
                            estimated_requirement_exceeds_cap=width>1 and raw_n>5)
            groups.append(cell)
    return dict(first_stage_complete=ready,target_half_width_pp=1.0,cells=groups,
                interpretation='Exploratory bootstrap on five independent pairs. Separate fixed-size confirmation; no claim of selection-valid pooled 95% CI.')

def main():
    path=STATE/'main-completed-pairs.csv'
    rows=list(csv.DictReader(path.open())) if path.exists() else []
    result=assess(rows)
    (STATE/'precision-assessment.json').write_text(json.dumps(result,indent=2))
    if result['first_stage_complete']:
        decision=STATE/'confirmation-plan.json'
        selected=[dict(policy=c['policy'],rho=c['rho'],seeds=list(range(106,106+c['additional_pairs'])))
                  for c in result['cells'] if c['additional_pairs']]
        if decision.exists() and json.loads(decision.read_text())!=selected:
            raise RuntimeError('Previously frozen confirmation plan differs')
        if not decision.exists():decision.write_text(json.dumps(selected,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
