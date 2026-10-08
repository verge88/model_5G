"""Launch the fixed robustness stage with persistent output logs."""
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
state=ROOT/'results/robustness-v1'
state.mkdir(exist_ok=True)
for folder in [state,ROOT/'results/detector-v1',ROOT/'results/main-v2-execution']:
    if (folder/'controller.lock').exists():raise RuntimeError('Existing controller lock: '+str(folder))
if (state/'pause-request.json').exists():raise RuntimeError('Pause request active')
stamp=str(time.time_ns())
with (state/(stamp+'.stdout.log')).open('w') as out,(state/(stamp+'.stderr.log')).open('w') as err:
    process=subprocess.Popen([sys.executable,'-u',str(ROOT/'scripts/robustness_stage.py')],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=out,stderr=err,close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_BREAKAWAY_FROM_JOB)
record=dict(pid=process.pid,started=time.time(),stdout=stamp+'.stdout.log',stderr=stamp+'.stderr.log')
(state/'launch.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))
