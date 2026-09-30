"""Read raw Open5GS logs; never substitute synthetic data for missing traces."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

EVENT = re.compile(r'LAB_(LOAD|SEND|NRF|SELECT|CANDIDATE|SCP) (.*?)(?: \([^\n]*\))?$')

def events(path):
    for line in path.read_text(errors='replace').splitlines():
        m = EVENT.search(line)
        if m:
            fields = dict(re.findall(r'(\w+)=([^\s]+)',m[2]))
            if 't' in fields:
                yield dict(kind=m[1],source=path.name,**fields)

def context_key(uri, target=''):
    if uri.startswith('http'): return uri.rstrip('/')
    return target.rstrip('/') + '/' + uri.lstrip('/')

def analyze(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    rows = sorted([x for f in folder.glob('*.log') for x in events(f)],key=lambda x:int(x['t']))
    active, callbacks, created, releases = {}, {}, {}, {}
    anomalies = []
    for e in rows:
        if e['kind'] != 'SCP': continue
        status = int(e['status'])
        if status == 201 and '/sm-contexts/' in e['location']:
            key = context_key(e['location'])
            smf = urlsplit(key).hostname
            if key in active: anomalies.append({'type':'duplicate_create',**e})
            else:
                active[key] = smf
                created[smf] = created.get(smf,0)+1
                if e.get('callback','-') != '-':
                    callbacks[urlsplit(e['callback']).path] = key
        if 200 <= status < 300:
            key = None
            if e.get('released') == '1':
                key = callbacks.get(urlsplit(e['uri']).path)
            elif e['uri'].endswith('/release'):
                key = context_key(e['uri'][:-8],e.get('target',''))
            if key in active:
                smf = active.pop(key)
                releases[smf] = releases.get(smf,0)+1
    load = [e for e in rows if e['kind']=='LOAD']
    selection = [e for e in rows if e['kind']=='SELECT']
    result = {'mode':manifest['mode'],'run_complete':manifest['complete'],
              'scp_created':created,'scp_released':releases,
              'scp_active':{host:list(active.values()).count(host) for host in created},
              'selections':len(selection),'load_samples':len(load),'anomalies':anomalies,
              'ueransim_established':len(re.findall('PDU Session establishment is successful',
                                     (folder/'ue.stdout').read_text(errors='replace')))}
    (folder/'events.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
    (folder/'summary.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('folder',type=Path)
    print(json.dumps(analyze(p.parse_args().folder),indent=2))
