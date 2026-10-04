"""Bridge from the live legacy coordinator at an audited pair boundary.

The old coordinator waits for its report subprocess. This subprocess waits for
the replacement controller, so the old pipeline cannot stop any containers until
the replacement finishes. Exit 75 then unwinds only the obsolete coordinator.
"""
import json,subprocess,sys,time,os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def maybe_handoff():
    from execute_main_v2 import budget_limit,handoff_ready
    state=json.loads((STATE/'ledger.json').read_text())
    if budget_limit() is not None or state.get('budget_mode')=='unlimited':return
    if os.name=='nt':
        parent=os.getppid();command=''
        # Windows virtualenv launchers insert one extra process with the same
        # report command line. Follow only that known wrapper, not arbitrary ancestors.
        for _ in range(2):
            raw=subprocess.check_output(['powershell.exe','-NoProfile','-Command',
                f"Get-CimInstance Win32_Process -Filter 'ProcessId = {parent}' | Select-Object Name,CommandLine,ParentProcessId | ConvertTo-Json -Compress"],text=True)
            info=json.loads(raw);command=info['CommandLine'] or ''
            if info.get('Name','').lower() not in ('python.exe','pythonw.exe'):return
            if 'report_main_v2.py' not in command:break
            parent=info['ParentProcessId']
    else:
        command=Path(f'/proc/{os.getppid()}/cmdline').read_bytes().replace(b'\0',b' ').decode()
    if 'execute_main_v2.py' not in command or '--launch' not in command:return
    if (STATE/'pause-request.json').exists() or state.get('status')!='running':return
    if not handoff_ready(state):return
    claim=STATE/'unlimited-handoff.json'
    if claim.exists():return
    # The report was started synchronously by the old coordinator after its last
    # active pair was audited; it cannot admit another pair while this call waits.
    claim.write_text(json.dumps(dict(started=time.time(),status='transferring',legacy_parent_pid=os.getppid(),
                                    source_phase=state['phase'],old_budget=state['approved_seconds']),indent=2))
    print('UNLIMITED_HANDOFF: current pairs complete; transferring without stopping containers',flush=True)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/execute_main_v2.py'),
                           '--phase',state['phase'],'--launch','--handoff'])
    if result.returncode==0:
        subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_article.py'),
                        '--prefix','main-v2-','--series','main-v2','--out',str(STATE/'main-evaluation')],check=True)
    data=json.loads(claim.read_text());data.update(finished=time.time(),status='replacement_finished',
                                                  exit_code=result.returncode,legacy_shutdown_exit_code=75)
    claim.write_text(json.dumps(data,indent=2))
    print('UNLIMITED_HANDOFF: replacement finished; intentional legacy coordinator shutdown (75)',flush=True)
    raise SystemExit(75)
