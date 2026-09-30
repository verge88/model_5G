"""Isolated Linux-container runner. Never use against an existing subscriber DB."""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import re
import signal
import shutil
import subprocess
import time
import urllib.request
import yaml

ROOT = Path('/work')
PLMN = {'mcc': '999', 'mnc': '70'}

def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False))

def configs(out, prefix):
    cfgdir = out/'configs'
    cfgdir.mkdir()
    for nf in ['nrf','scp','amf','smf','upf','ausf','udm','udr','pcf','nssf','bsf']:
        data = yaml.safe_load((Path(prefix)/'etc/open5gs'/f'{nf}.yaml').read_text())
        data['logger'] = {'file': {'path': str(out/f'{nf}.log')}, 'level': 'info'}
        data['global'] = {'max': {'ue': 1024, 'peer': 128}}
        if 'db_uri' in data: data['db_uri'] = 'mongodb://127.0.0.1/model5g'
        if nf != 'upf':
            sbi = data[nf]['sbi']
            if nf == 'nrf':
                data[nf]['time'] = {'nf_instance': {'heartbeat': 1}}
            elif nf == 'scp':
                sbi['client'] = {'nrf': [{'uri': 'http://127.0.0.10:7777'}]}
            else:
                client = sbi.setdefault('client', {})
                client['nrf'] = [{'uri': 'http://127.0.0.10:7777'}]
                client['scp'] = [{'uri': 'http://127.0.0.200:7777'}]
                client['delegated'] = {'nrf': {'nfm': 'no', 'disc': 'no'}}
        if nf == 'smf':
            data[nf].pop('freeDiameter', None)
            data[nf]['info'] = [{'s_nssai':[{'sst':1,'dnn':['internet']}],
                                  'tai':[{'plmn_id':PLMN,'tac':1}]}]
            data[nf]['session'] = [{'subnet':'10.45.0.0/16','gateway':'10.45.0.1'}]
            for i in range(1,4):
                d = copy.deepcopy(data)
                address = f'127.0.0.{3+i}' if i == 1 else f'127.0.0.{30+i}'
                for section in ['sbi','pfcp','gtpc','gtpu','metrics']:
                    d['smf'][section]['server'][0]['address'] = address
                d['smf']['session'] = [{'subnet':f'10.45.{i}.0/24','gateway':f'10.45.{i}.1'}]
                d['logger']['file']['path'] = str(out/f'smf{i}.log')
                write_yaml(cfgdir/f'smf{i}.yaml', d)
        else:
            if nf == 'upf':
                data[nf]['session'] = [{'subnet':'10.45.0.0/16','gateway':'10.45.0.1'}]
            write_yaml(cfgdir/f'{nf}.yaml', data)
    gnb = yaml.safe_load((ROOT/'upstream/UERANSIM/config/open5gs-gnb.yaml').read_text())
    write_yaml(cfgdir/'gnb.yaml', gnb)
    ue = yaml.safe_load((ROOT/'upstream/UERANSIM/config/open5gs-ue.yaml').read_text())
    ue['sessions'] = []
    ue['default-nssai'] = [{'sst':1}]
    ue['configured-nssai'] = [{'sst':1}]
    write_yaml(cfgdir/'ue.yaml', ue)
    return cfgdir

def subscribers(n):
    from pymongo import MongoClient
    db = MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=5000).model5g
    # Dedicated disposable container/database only, no connection parameter.
    db.subscribers.create_index('imsi', unique=True)
    for i in range(1,n+1):
        imsi = f'99970{i:010d}'
        doc = {'imsi':imsi, 'schema_version':1, 'msisdn':[], 'imeisv':[],
               'security':{'k':'465B5CE8B199B49FAA5F0A2EE238A6BC',
                           'opc':'E8ED289DEBA952E4283B54E88E6183CA', 'amf':'8000'},
               'ambr':{'downlink':{'value':1,'unit':3},'uplink':{'value':1,'unit':3}},
               'slice':[{'sst':1,'default_indicator':True,'session':[{
                   'name':'internet','type':1,
                   'qos':{'index':9,'arp':{'priority_level':8,
                       'pre_emption_capability':1,'pre_emption_vulnerability':2}},
                   'ambr':{'downlink':{'value':1,'unit':3},'uplink':{'value':1,'unit':3}}}]}],
               'access_restriction_data':32,'subscriber_status':0,
               'network_access_mode':0,'subscribed_rau_tau_timer':12}
        db.subscribers.replace_one({'imsi':imsi}, doc, upsert=True)

def run(args):
    destination = ROOT/args.out
    if destination.exists(): raise FileExistsError(destination)
    out = Path('/tmp/model5g-runs')/Path(args.out).name
    out.mkdir(parents=True, exist_ok=False)
    prefix = '/opt/model5g-baseline' if args.baseline else '/opt/model5g-patched'
    cfg = configs(out,prefix)
    manifest = vars(args).copy()
    manifest.update(mode='real-open5gs-ueransim', open5gs_commit='157f611a530e292e40ec50f9d23f0ef5d4fcd6a6',
                    started=time.time(), complete=False)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    processes, logs = [], []
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = f'{prefix}/lib/x86_64-linux-gnu:{prefix}/lib'
    env['LAB_TRACE'] = '1'
    if not args.baseline: env.update(LAB_SELECTOR=args.policy,LAB_SEED=str(args.seed))
    def start(name, cmd, extra=None):
        log = (out/f'{name}.stdout').open('w'); logs.append(log)
        p = subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,
                             env=env | (extra or {}),start_new_session=True)
        processes.append((name,p)); return p
    def check():
        dead = [(name,p.returncode) for name,p in processes if p.poll() is not None]
        if dead: raise RuntimeError(f'Processes stopped: {dead}')
    def cli(i,command):
        log_offset = (out/'ue.stdout').stat().st_size
        result = subprocess.run(['/build/model5g-ueransim/build/nr-cli',f'imsi-99970{i:010d}',
                        '--exec',command],capture_output=True,text=True,timeout=15)
        events.write(json.dumps({'t':time.monotonic_ns()/1000,'ue':i,'command':command,
                     'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')
        events.flush()
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        if command.startswith('ps-establish') or command == 'ps-release-all':
            wanted = ('PDU Session establishment is successful' if command.startswith('ps-establish')
                      else 'Performing local release of PDU session')
            deadline = time.monotonic()+10
            with (out/'ue.stdout').open() as stream:
                stream.seek(log_offset)
                while time.monotonic()<deadline:
                    text = stream.read()
                    if any(f'99970{i:010d}|' in line and wanted in line for line in text.splitlines()):
                        break
                    time.sleep(.01)
                else:
                    raise RuntimeError(f'UE {i}: no confirmation for {command}')
        return result.stdout
    try:
        subscribers(args.ues)
        Path('/dev/net').mkdir(exist_ok=True)
        if not Path('/dev/net/tun').exists(): os.mknod('/dev/net/tun',0o20666,os.makedev(10,200))
        subprocess.run(['ip','tuntap','add','name','ogstun','mode','tun'],check=True)
        subprocess.run(['ip','addr','add','10.45.0.1/16','dev','ogstun'],check=True)
        subprocess.run(['ip','link','set','ogstun','up'],check=True)
        start('pcap',['tcpdump','-i','lo','-U','-s','0','-w',str(out/'sbi.pcap'),'tcp port 7777'])
        prom = {'global':{'scrape_interval':'1s'},'scrape_configs':[{'job_name':'smf',
                'static_configs':[{'targets':['127.0.0.4:9090','127.0.0.32:9090','127.0.0.33:9090']}]}]}
        write_yaml(cfg/'prometheus.yaml',prom)
        start('prometheus',['prometheus','--config.file='+str(cfg/'prometheus.yaml'),
              '--storage.tsdb.path='+str(out/'prometheus'),'--web.listen-address=127.0.0.1:9099'])
        for name in ['nrf','scp','upf','ausf','udr','udm','pcf','nssf','bsf','amf']:
            start(name,[f'{prefix}/bin/open5gs-{name}d','-c',str(cfg/f'{name}.yaml')])
            time.sleep(.25)
        for i in map(int,args.order.split(',')):
            start(f'smf{i}',[f'{prefix}/bin/open5gs-smfd','-c',str(cfg/f'smf{i}.yaml')],
                  {} if args.baseline else {'LAB_CAPACITY_ABS':str(args.capacity),
                      'LAB_ALPHA':str(args.alpha if i == 3 else 0)})
            time.sleep(.6)
        time.sleep(3); check()
        start('gnb',['/build/model5g-ueransim/build/nr-gnb','-c',str(cfg/'gnb.yaml')])
        time.sleep(2); check()
        start('ue',['/build/model5g-ueransim/build/nr-ue','-c',str(cfg/'ue.yaml'),'-n',str(args.ues), '--no-routing-config'])
        time.sleep(max(8,args.ues*.08)); check()
        with (out/'workload.jsonl').open('w') as events:
            active = list(range(1,args.active+1))
            idle = list(range(args.active+1,args.ues+1))
            for i in active:
                cli(i,'ps-establish IPv4 --sst 1 --dnn internet')
                time.sleep(args.interval)
            time.sleep(3); check()
            rng = random.Random(args.seed)
            for cycle in range(args.cycles):
                old = rng.choice(active); new = rng.choice(idle)
                cli(old,'ps-release-all')
                time.sleep(args.interval)
                cli(new,'ps-establish IPv4 --sst 1 --dnn internet')
                active.remove(old); idle.remove(new); active.append(new); idle.append(old)
                time.sleep(args.interval)
                if cycle % 20 == 0: check()
            for i in active: cli(i,'ps-list')
        time.sleep(3)
        for i, address in enumerate(['127.0.0.4','127.0.0.32','127.0.0.33'],1):
            (out/f'smf{i}-metrics.txt').write_bytes(urllib.request.urlopen(f'http://{address}:9090/metrics').read())
        ue_log = (out/'ue.stdout').read_text(errors='replace')
        established = len(re.findall('PDU Session establishment is successful',ue_log))
        expected = args.active + args.cycles
        manifest['expected_established'] = expected
        manifest['actual_established'] = established
        if established != expected:
            raise RuntimeError(f'Established {established} sessions, expected {expected}')
        if not args.baseline:
            selected = (out/'amf.log').read_text(errors='replace').count('LAB_SELECT ')
            manifest['amf_selections'] = selected
            if selected != expected:
                raise RuntimeError(f'AMF performed {selected} experimental selections, expected {expected}')
        manifest['complete'] = True
    finally:
        for _,p in reversed(processes):
            if p.poll() is None: os.killpg(p.pid,signal.SIGTERM)
        for _,p in processes:
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(p.pid,signal.SIGKILL)
        for log in logs: log.close()
        subprocess.run(['ip','link','delete','ogstun'],capture_output=True)
        manifest['finished'] = time.time()
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
        shutil.copytree(out,destination)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    p.add_argument('--baseline',action='store_true')
    p.add_argument('--order',default='1,2,3')
    p.add_argument('--policy',choices=['swrr','random'],default='swrr')
    p.add_argument('--seed',type=int,default=1)
    p.add_argument('--alpha',type=float,default=0)
    p.add_argument('--capacity',type=int,default=100)
    p.add_argument('--ues',type=int,default=12)
    p.add_argument('--active',type=int,default=3)
    p.add_argument('--cycles',type=int,default=10)
    p.add_argument('--interval',type=float,default=.3)
    args = p.parse_args()
    if not (0 < args.active < args.ues and 0 <= args.alpha <= 1 and args.capacity > 0):
        p.error('require 0 < active < ues, 0 <= alpha <= 1, capacity > 0')
    run(args)
