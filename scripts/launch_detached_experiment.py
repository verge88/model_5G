"""Request detached Windows job breakaway and record actual job membership."""
import ctypes,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def main():
    if sys.platform!='win32':raise RuntimeError('Windows launcher only')
    if (STATE/'controller.lock').exists():raise RuntimeError('Controller lock exists; inspect before starting')
    if (STATE/'pause-request.json').exists():raise RuntimeError('User pause still active')
    stamp=time.time_ns();log=STATE/f'detached-{stamp}'
    flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_BREAKAWAY_FROM_JOB
    with Path(str(log)+'.stdout.log').open('w') as out,Path(str(log)+'.stderr.log').open('w') as err:
        process=subprocess.Popen([sys.executable,'-u',str(ROOT/'scripts/continue_main_v2.py')],cwd=ROOT,
                                  stdout=out,stderr=err,stdin=subprocess.DEVNULL,creationflags=flags,close_fds=True)
    in_job=ctypes.c_int()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.IsProcessInJob.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]
    kernel.IsProcessInJob.restype=ctypes.c_int
    if not kernel.IsProcessInJob(int(process._handle),None,ctypes.byref(in_job)):
        raise ctypes.WinError(ctypes.get_last_error())
    record=dict(pid=process.pid,started=time.time(),breakaway_requested=True,
                in_windows_job=bool(in_job.value),fully_outside_job_verified=not bool(in_job.value),
                stdout=str(log)+'.stdout.log',stderr=str(log)+'.stderr.log')
    (STATE/'detached-launch.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()
