"""Budget-limited real experiments, checkpointed after each run.

Paired runs share the same closed-loop UE replacement sequence. They do not
claim identical wall-clock arrival times. A failed run stops the matrix.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import sys

ROOT=Path('/work')
def main():
    p=argparse.ArgumentParser();p.add_argument('--hours',type=float,default=3.2)
    p.add_argument('--name',default='article');a=p.parse_args()
    dest=ROOT/'results'/a.name;dest.mkdir(parents=True,exist_ok=False)
    deadline=time.time()+a.hours*3600
    plan=[]
    def add(tag,rho,seed,alpha=0,policy='swrr',extra=(),warmup=200,measured=400):
        plan.append(dict(tag=tag,rho=rho,seed=seed,alpha=alpha,policy=policy,
                         extra=list(extra),warmup=warmup,measured=measured))
    # Independent benign calibration runs, separated from all test seeds.
    for rho in [.2,.5,.7]:add(f'cal-r{int(rho*100)}',rho,900+int(rho*10),warmup=100,measured=200)
    # Complete mechanistic coverage first, then independent replication.
    for seed in [101,102,103]:
        for policy in ['swrr','random']:
            for rho in [.5,.7,.2]:
                for alpha in [0,.5]:
                    add(f'{policy}-r{int(rho*100)}-s{seed}-a{int(alpha*100)}',rho,seed,alpha,policy)
        if seed==101:
            for budget in [0,1,2,4,8]:
                add(f'adaptive-b{budget}',.5,801,.5,extra=['--residual-budget',str(budget)])
            add('capacity150',.5,801,extra=['--reported-capacity','150'])
            add('adaptive-capacity150',.5,801,.5,extra=['--residual-budget','2','--reported-capacity','150'])
            add('adaptive-counterfactual',.5,801)
            add('ramp',.5,801,.5,extra=['--attack-mode','ramp'])
            add('onoff',.5,801,.5,extra=['--attack-mode','onoff'])
    status={'started':time.time(),'deadline':deadline,'complete':False,'runs':[],
            'plan':plan,'budget_hours':a.hours,'amendment':'Pilot sized to the human-approved four-hour compute budget; original 3000-assignment/10-seed protocol remains an unexecuted full protocol.'}
    path=dest/'matrix.json'
    def save():path.write_text(json.dumps(status,indent=2))
    save()
    for item in plan:
        # Do not start an experiment which cannot plausibly finish in budget.
        estimate=35+300*item['rho']*.3+(item['warmup']+item['measured'])*.55
        if time.time()+estimate>deadline:
            status['stop_reason']='budget';break
        name=f'{a.name}-{item["tag"]}'
        active=round(300*item['rho'])
        cmd=[sys.executable,str(ROOT/'scripts/run_lab.py'),'--out','runs/'+name,
             '--deadline',str(deadline-30),
             '--ues',str(active+12),'--active',str(active),'--capacity','100',
             '--seed',str(item['seed']),'--alpha',str(item['alpha']),'--policy',item['policy'],
             '--warmup',str(item['warmup']),'--cycles',str(item['warmup']+item['measured']),
             '--interval','.01',*item['extra']]
        print('START',name,flush=True)
        started=time.time()
        result=subprocess.run(cmd)
        row={**item,'name':name,'seconds':time.time()-started,'exit_code':result.returncode}
        status['runs'].append(row);save()
        if result.returncode:
            status['stop_reason']='failed_run';break
        subprocess.run([sys.executable,str(ROOT/'scripts/analyze.py'),str(ROOT/'runs'/name)],
                       stdout=(dest/f'{name}-summary.json').open('w'),check=True)
        print('DONE',name,round(row['seconds'],1),flush=True)
    else:status['complete']=True
    status['finished']=time.time();save()
    print('MATRIX_STOP',status.get('stop_reason','completed'),flush=True)

if __name__=='__main__':main()
