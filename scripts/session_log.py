"""Wait for an exact UE's NAS confirmation despite fragmented log writes."""
import time

def wait_confirmation(path,offset,ue,wanted,timeout=10):
    deadline=time.monotonic()+timeout
    with path.open() as stream:
        stream.seek(offset)
        text=''
        while time.monotonic()<deadline:
            text+=stream.read()
            if any(f'99970{ue:010d}|' in line and wanted in line for line in text.splitlines()):
                return True
            time.sleep(.01)
    return False
