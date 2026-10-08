"""Launch the fixed age-aware prospective validation matrix."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
state=ROOT/'results/timeaware-v1';state.mkdir(exist_ok=True)
for name in ['timeaware-v1','delay-burst-v1','quantization-v1','robustness-v1','detector-v1','main-v2-execution']:
    if (ROOT/'results'/name/'controller.lock').exists():raise RuntimeError('Existing controller lock: '+name)
if (state/'pause-request.json').exists():raise RuntimeError('Pause request active')
hashes={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()
        for name in ['age_aware_detector.py','timeaware_stage.py','run_lab.py']}
freeze=state/'measurement-code.json'
if freeze.exists() and json.loads(freeze.read_text())!=hashes:raise RuntimeError('Measurement code changed; document before resuming')
freeze.write_text(json.dumps(hashes,indent=2))
stamp=str(time.time_ns())
with (state/(stamp+'.stdout.log')).open('w') as out,(state/(stamp+'.stderr.log')).open('w') as err:
    process=subprocess.Popen([sys.executable,'-u',str(ROOT/'scripts/timeaware_stage.py')],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=out,stderr=err,close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_BREAKAWAY_FROM_JOB)
record=dict(pid=process.pid,started=time.time(),stdout=stamp+'.stdout.log',stderr=stamp+'.stderr.log')
(state/'launch.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
