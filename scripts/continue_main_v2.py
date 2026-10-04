"""Finish audited preparation, freeze warmup, then run the bounded main matrix."""
import json, subprocess, sys, ctypes
from pathlib import Path
from check_warmup import diagnostic
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def phase(name):
    subprocess.run([sys.executable,str(ROOT/'scripts/execute_main_v2.py'),'--phase',name,'--launch'],check=True)
    state=json.loads((STATE/'ledger.json').read_text())
    subprocess.run([sys.executable,str(ROOT/'scripts/report_main_v2.py')],check=True)
    return state

def main():
    try:
        if sys.platform=='win32':
            if not ctypes.windll.kernel32.SetThreadExecutionState(0x80000001):
                raise RuntimeError('Cannot prevent idle system sleep during measurement')
        state=json.loads((STATE/'ledger.json').read_text())
        if sum(r['eligible_pair'] and r['item']['series_id']=='pilot-closeout-v2' for r in state['results'])!=2:
            raise RuntimeError('Pilot closeout must finish first')
        state=phase('prep')
        if not state['phase_complete']:raise RuntimeError('Preparation incomplete; main phase blocked')
        folders=[ROOT/'runs'/r['name'] for result in state['results']
                 if result['eligible_pair'] and result['item']['series_id']=='main-v2-preparation' for r in result['records']]
        reports=[diagnostic(folder) for folder in folders]
        (STATE/'warmup-diagnostics.json').write_text(json.dumps(reports,indent=2))
        accepted=None
        for warmup in [300,1200]:
            if len(reports)==4 and all(abs(v)<=5 for r in reports for v in r[f'early_minus_late_active_{warmup}'].values()):
                accepted=warmup;break
        gate=dict(accepted=accepted is not None,warmup=accepted,preparation_runs=[f.name for f in folders],
                  criterion='All nodes early/late mean occupancy contrast <=5 sessions in four rho=.7 preparation runs',
                  limitation='Descriptive transient screen, not a statistical stationarity proof; lower loads checked in main block diagnostics')
        (STATE/'warmup-decision.json').write_text(json.dumps(gate,indent=2))
        print('WARMUP_DECISION',json.dumps(gate),flush=True)
        if accepted is None:raise RuntimeError('Warmup diagnostic needs review; main phase not started')
        state=phase('main')
        subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_article.py'),
                        '--prefix','main-v2-','--series','main-v2','--out',str(STATE/'main-evaluation')],check=True)
    finally:
        subprocess.run(['docker','stop','model5g-runtime','model5g-worker2','model5g-worker3','model5g-worker4',
                        'model5g-db','model5g-db2','model5g-db3','model5g-db4'],check=False)
        if sys.platform=='win32':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

if __name__=='__main__':main()
