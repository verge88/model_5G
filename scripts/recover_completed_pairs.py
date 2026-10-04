"""Audit orphaned completed pairs after verifying the old coordinator is absent."""
import json,time
from pathlib import Path
from evaluate_article import audit,matched_experimental_conditions
from report_main_v2 import main as report
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def main():
    path=STATE/'ledger.json';state=json.loads(path.read_text());stamp=time.time_ns()
    recovered=[]
    for pending in state.get('in_flight',[]):
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
            raise RuntimeError('Pair not comparable')
        result=dict(item=item,worker=pending['worker'],attempt=1,records=records,eligible_pair=True,
                    seconds=max(pending['reserved_seconds'],sum(r['seconds'] for r in records)),
                    recovered=True,budget_accounting='Reserved allowance retained as conservative elapsed-time upper bound')
        state['results'].append(result);recovered.append(result)
    (STATE/f'ledger-before-recovery-{stamp}.json').write_bytes(path.read_bytes())
    state.update(status='recovered',stop_reason='coordinator_absent_completed_pairs_recovered',in_flight=[],
                 active_seconds=sum(r['seconds'] for r in state['results']),
                 pending=[i for i in state['plan'] if not any(r['item']==i and r['eligible_pair'] for r in state['results'])])
    state['phase_complete']=not state['pending']
    temp=STATE/'ledger.recovery.tmp';temp.write_text(json.dumps(state,indent=2));temp.replace(path)
    (STATE/f'recovered-pairs-{stamp}.json').write_text(json.dumps(recovered,indent=2))
    lock=STATE/'controller.lock'
    if lock.exists():lock.rename(STATE/f'controller-stale-{stamp}.lock-archive')
    report();print(json.dumps(dict(recovered_pairs=len(recovered),pending_pairs=len(state['pending']))))

if __name__=='__main__':main()
