"""Real HTTP/2 integration test against dedicated disposable NRF processes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
import h2.config
import h2.connection
import h2.events
import yaml

def request(method, path, body=None):
    data = b'' if body is None else json.dumps(body).encode()
    with socket.create_connection(('127.0.0.10',7777),timeout=5) as sock:
        conn = h2.connection.H2Connection(config=h2.config.H2Configuration(header_encoding='utf-8'))
        conn.initiate_connection(); sock.sendall(conn.data_to_send())
        headers = [(':method',method),(':scheme','http'),(':authority','127.0.0.10:7777'),(':path',path),
                   ('user-agent','SMF'),('content-type','application/json-patch+json' if method=='PATCH' else 'application/json')]
        conn.send_headers(1,headers,end_stream=not data)
        if data: conn.send_data(1,data,end_stream=True)
        sock.sendall(conn.data_to_send())
        result, payload = {}, b''
        while True:
            chunk = sock.recv(65535)
            if not chunk: raise RuntimeError('connection closed before response')
            for event in conn.receive_data(chunk):
                if isinstance(event,h2.events.ResponseReceived): result.update(dict(event.headers))
                if isinstance(event,h2.events.DataReceived):
                    payload += event.data
                    conn.acknowledge_received_data(event.flow_controlled_length,event.stream_id)
                if isinstance(event,h2.events.StreamEnded):
                    return int(result[':status']),json.loads(payload) if payload else None
            sock.sendall(conn.data_to_send())

def run():
    out = Path('/work/results/nrf-integration'); out.mkdir(parents=True,exist_ok=True)
    results = {}
    for variant in ['baseline','patched']:
        prefix = f'/opt/model5g-{variant}'
        cfg = {'logger':{'file':{'path':str(out/f'{variant}.log')}},
               'nrf':{'sbi':{'server':[{'address':'127.0.0.10','port':7777}]}}}
        path = out/f'{variant}.yaml'; path.write_text(yaml.safe_dump(cfg))
        env = os.environ | {'LD_LIBRARY_PATH':f'{prefix}/lib/x86_64-linux-gnu:{prefix}/lib'}
        with (out/f'{variant}.stdout').open('w') as log:
            proc = subprocess.Popen([f'{prefix}/bin/open5gs-nrfd','-c',str(path)],env=env,stdout=log,stderr=log)
            try:
                time.sleep(1)
                identity=str(uuid.uuid4()); endpoint=f'/nnrf-nfm/v1/nf-instances/{identity}'
                status, _ = request('PUT',endpoint,{'nfInstanceId':identity,'nfType':'SMF',
                         'nfStatus':'REGISTERED','ipv4Addresses':['127.0.0.33'],'load':10,'capacity':100,'priority':0})
                assert status == 201, status
                status,_=request('PATCH',endpoint,[{'op':'replace','path':'/load','value':37}])
                assert status == 204,status
                status,profile=request('GET',endpoint)
                assert status == 200,status
                assert profile['load']==(37 if variant=='patched' else 10),profile
                checks=[]
                if variant=='patched':
                    for value in [-1,101,12.5,'37',None,True]:
                        code,_=request('PATCH',endpoint,[{'op':'replace','path':'/load','value':value}])
                        assert code == 400,(value,code)
                        _,after=request('GET',endpoint); assert after['load']==37,after
                        checks.append({'value':value,'status':code,'unchanged':True})
                results[variant]={'registered_load':10,'patched_load':profile['load'],'invalid_inputs':checks,'passed':True}
            finally:
                proc.terminate();proc.wait(timeout=10)
    (out/'result.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))

if __name__=='__main__': run()
