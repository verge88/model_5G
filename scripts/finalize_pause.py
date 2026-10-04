"""Recover completed pairs after a departed controller; never starts experiments."""
import json,time
from pathlib import Path
from evaluate_article import audit,matched_experimental_conditions
from report_main_v2 import main as report
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def main():
    request=json.loads((STATE/'pause-request.json').read_text())
    path=STATE/'ledger.json';state=json.loads(path.read_text())
    recovered=[]
    for pending in request['snapshot']['in_flight']:
        item=pending['item']
        if any(r['item']==item and r['eligible_pair'] for r in state['results']):continue
        records=[]
        for alpha in [0,.5]:
            prefix=f"{item['series_id']}-{item['policy']}-r{round(item['rho']*100)}-s{item['seed']}-a{int(alpha*100)}-attempt"
            folders=sorted((ROOT/'runs').glob(prefix+'*'))
            if len(folders)!=1:raise RuntimeError('Ambiguous recovery '+prefix)
            folder=folders[0];m=json.loads((folder/'manifest.json').read_text())
            if not m['complete']:raise RuntimeError('Incomplete run '+folder.name)
            assessment,_=audit(folder)
            if not assessment['eligible']:raise RuntimeError('Audit failed '+folder.name)
            records.append(dict(name=folder.name,exit_code=0,seconds=m['finished']-m['started'],audit=assessment))
        a,b=[r['audit'] for r in records]
        if not matched_experimental_conditions(a,b) or a['workload_hash']!=b['workload_hash']:
            raise RuntimeError('Recovered pair not comparable')
        # Original coordinator stopwatch is gone; charge the whole reserved allowance.
        # This deliberately overestimates recorded execution and preserves the limit.
        charged=max(pending['reserved_seconds'],sum(r['seconds'] for r in records))
        result=dict(item=item,worker=pending['worker'],attempt=1,records=records,eligible_pair=True,seconds=charged,
                    recovered=True,budget_accounting='Full reserved pair allowance charged because coordinator elapsed time unavailable')
        state['results'].append(result);recovered.append(result)
    state.update(status='paused',stop_reason='user_requested_after_current_pairs',in_flight=[],paused_at=time.time(),
                 active_seconds=sum(r['seconds'] for r in state['results']),
                 pending=[i for i in state['plan'] if not any(r['item']==i and r['eligible_pair'] for r in state['results'])])
    state['phase_complete']=not state['pending']
    backup=STATE/'ledger-before-pause-recovery.json'
    if not backup.exists():backup.write_bytes(path.read_bytes())
    temporary=STATE/'ledger.recovery.tmp';temporary.write_text(json.dumps(state,indent=2));temporary.replace(path)
    remaining=None if state.get('approved_seconds') is None else state['approved_seconds']-state['active_seconds']
    (STATE/'pause-recovery.json').write_text(json.dumps(dict(recovered=recovered,remaining_seconds=remaining),indent=2))
    # Caller verified no coordinating processes or experiments are running.
    (STATE/'controller.lock').unlink(missing_ok=True)
    report()
    print(json.dumps(dict(status=state['status'],recovered_pairs=len(recovered),active_seconds=state['active_seconds'],pending_pairs=len(state['pending']))))

if __name__=='__main__':main()
