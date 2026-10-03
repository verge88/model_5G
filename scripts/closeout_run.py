"""One configuration-matched counterfactual, within the remaining total budget."""
from pathlib import Path
import json,subprocess,sys,time
R=Path(__file__).resolve().parents[1]
previous=json.loads((R/'results/article-parallel-20261002/matrix.json').read_text())['active_seconds']
allowance=14400-previous-30
if allowance<350:raise RuntimeError('Insufficient remaining approved budget')
name='article-20261001-random-r50-s101-a0-matched'
out=R/'results/article-closeout-20261003';out.mkdir(exist_ok=False)
status={'started':time.time(),'complete':False,'previous_active_seconds':previous,'runs':[],
        'reason':'Match the earlier sequential honest counterfactual to the parallel attack configuration; selection independent of outcome.'}
path=out/'matrix.json';path.write_text(json.dumps(status,indent=2))
cmd=['docker','exec','-e','LAB_EXECUTION_WORKER=model5g-worker2','model5g-worker2','python',
     '/work/scripts/run_lab.py','--out','runs/'+name,'--deadline',str(time.time()+allowance-10),
     '--ues','162','--active','150','--capacity','100','--seed','101','--alpha','0','--policy','random',
     '--warmup','200','--cycles','600','--interval','.01']
start=time.monotonic()
with (out/'runner.log').open('w') as log:result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
elapsed=time.monotonic()-start
status.update(finished=time.time(),complete=result.returncode==0,active_seconds=previous+elapsed,
              stop_reason='complete' if result.returncode==0 else 'failed_run',
              runs=[dict(name=name,seconds=elapsed,exit_code=result.returncode)])
path.write_text(json.dumps(status,indent=2))
subprocess.run([sys.executable,str(R/'scripts/evaluate_article.py')],check=True)
print(json.dumps(status,indent=2))
