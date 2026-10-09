"""Causal, provenance-aware NF cache consistency feature extraction.

Input is normalized telemetry from authenticated collectors, NOT raw SBI requests.
Raw NF identities, addresses, subscriber data and attack labels never enter X.
"""
import argparse,hashlib,json,math
from collections import defaultdict,deque
from pathlib import Path
from urllib.parse import urlsplit

KINDS={'registry_snapshot':'registry','cache_snapshot':'cache','route':'route',
       'notification':'notify','subscription_snapshot':'subscription'}
ROLES=['registry','cache','route','notify','subscription']
FEATURES=[*(r+'_available' for r in ROLES),'independent_domains','unavailable_roles',
          'route_registry_mismatch','cache_registry_mismatch','route_cache_mismatch',
          'route_mismatch_age','cache_mismatch_age','route_changes30','cache_changes30',
          'registry_changes30','notifications30','unmatched_notifications30',
          'invalid_sender30','unbound_subscription30','registry_age','cache_age','route_age',
          'notify_age','source_conflicts','route_after_notify_change']

def endpoint(value):
    u=urlsplit(value)
    if u.scheme not in ['http','https'] or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Endpoint must be an HTTP(S) origin without credentials, query or fragment')
    if u.path not in ['', '/']:raise ValueError('Use service origin; do not include subscriber/request paths')
    return (u.scheme,u.hostname.lower(),u.port or (443 if u.scheme=='https' else 80))

def config_digest(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def key(event):
    e=event['entity']
    return tuple(str(e[n]) for n in ['consumer','nf_type','service'])

class Engine:
    def __init__(self,config):
        self.config=config;self.sources=config['sources'];self.ttl=float(config.get('ttl_seconds',15))
        self.grace=float(config.get('grace_seconds',5));self.states={};self.last_time=-math.inf
        self.config_sha256=config_digest(config)
        if not math.isfinite(self.ttl) or self.ttl<=0 or not math.isfinite(self.grace) or self.grace<0:
            raise ValueError('Invalid TTL/grace')
        for source,s in self.sources.items():
            if s['role'] not in ROLES or not s.get('domain'):raise ValueError('Invalid source inventory')

    def ingest(self,event):
        t=float(event['observed_at'])
        if not math.isfinite(t) or t<self.last_time:raise ValueError('Collector observation times must be finite and nondecreasing')
        source=event['source'];cfg=self.sources.get(source)
        if not cfg or cfg.get('trusted') is not True:raise ValueError('Unknown/untrusted collector')
        kind=event['kind'];role=cfg['role']
        if kind!='health' and KINDS.get(kind)!=role:raise ValueError('Collector cannot assert this event kind')
        k=key(event)
        if k[1:]!=('UDM','nudm-ueau'):raise ValueError('This model supports UDM nudm-ueau only')
        s=self.states.setdefault(k,dict(latest={},health={},history=deque(),since={},last_route=None))
        d=event['data']
        if kind=='health':
            if not isinstance(d.get('available'),bool):raise ValueError('Health requires boolean available')
            s['health'][source]=(t,d['available']);self.last_time=t;return
        value=dict(t=t,role=role,source=source)
        if kind in ['registry_snapshot','cache_snapshot']:
            if d.get('complete') is not True:raise ValueError('Only complete snapshots are accepted; omissions are not negative evidence')
            value['endpoints']=frozenset(endpoint(x) for x in d['endpoints'])
        elif kind=='route':value['endpoints']=frozenset([endpoint(d['endpoint'])])
        elif kind=='subscription_snapshot':
            if d.get('complete') is not True:raise ValueError('Subscription snapshot must be complete')
            bindings={}
            for b in d['bindings']:
                until=float(b['valid_until'])
                if not math.isfinite(until):raise ValueError('Invalid binding expiry')
                bindings[str(b['callback_context'])]=until
            value['bindings']=bindings
        elif kind=='notification':
            # sender_verified is an attestation by the authenticated collector, not a payload field.
            verified=d.get('sender_verified')
            if verified is not None and not isinstance(verified,bool):raise ValueError('sender_verified must be boolean/null')
            value.update(endpoints=frozenset(endpoint(x) for x in d.get('endpoints',[])),
                verified=verified,context=str(d.get('callback_context','')))
            registry=self._view(s,'registry',t);subscription=self._view(s,'subscription',t)
            mismatch=(not value['endpoints'].issubset(registry['endpoints'])) if registry else None
            unbound=(subscription['bindings'].get(value['context'],-math.inf)<=t) if subscription and value['context'] else None
            s['history'].append(dict(t=t,kind='notification',unmatched=mismatch,
                invalid=(not verified) if verified is not None else None,unbound=unbound))
        previous=s['latest'].get(source)
        if kind in ['registry_snapshot','cache_snapshot','route']:
            changed=previous is not None and previous['endpoints']!=value['endpoints']
            if changed:s['history'].append(dict(t=t,kind=role+'_change'))
        s['latest'][source]=value;s['health'][source]=(t,True)
        self.last_time=t

    def _views(self,s,role,t):
        result=[]
        for source,v in s['latest'].items():
            health=s['health'].get(source)
            if v['role']==role and 0<=t-v['t']<=self.ttl and health and health[1] and t-health[0]<=self.ttl:
                result.append(v)
        return result

    def _view(self,s,role,t):
        views=self._views(s,role,t)
        if not views:return None
        field='bindings' if role=='subscription' else 'endpoints'
        if role!='notify' and any(v[field]!=views[0][field] for v in views[1:]):return None
        return max(views,key=lambda v:v['t'])

    def snapshot(self,t):
        if not math.isfinite(t) or t<self.last_time:raise ValueError('Cannot score before the latest received event')
        self.last_time=t
        output=[]
        for k,s in self.states.items():
            while s['history'] and s['history'][0]['t']<t-30:s['history'].popleft()
            views={r:self._view(s,r,t) for r in ROLES};history=list(s['history']);x={}
            for r in ROLES:x[r+'_available']=int(views[r] is not None)
            domains={self.sources[v['source']]['domain'] for r in ROLES for v in self._views(s,r,t)}
            x['independent_domains']=len(domains);x['unavailable_roles']=sum(views[r] is None for r in ROLES)
            conflicts=sum(bool(self._views(s,r,t)) and views[r] is None for r in ROLES)
            x['source_conflicts']=conflicts
            for name,a,b in [('route_registry_mismatch','route','registry'),('cache_registry_mismatch','cache','registry'),('route_cache_mismatch','route','cache')]:
                x[name]=int(not views[a]['endpoints'].issubset(views[b]['endpoints'])) if views[a] and views[b] else None
            for tag in ['route','cache']:
                mismatch=x[tag+'_registry_mismatch']
                if mismatch==1:s['since'].setdefault(tag,t)
                else:s['since'].pop(tag,None)
                x[tag+'_mismatch_age']=min(60,t-s['since'][tag]) if tag in s['since'] else (0 if mismatch==0 else None)
            for r in ['route','cache','registry']:x[r+'_changes30']=sum(v['kind']==r+'_change' for v in history) if views[r] else None
            notes=[v for v in history if v['kind']=='notification']
            x['notifications30']=len(notes) if views['notify'] else None
            for name,field in [('unmatched_notifications30','unmatched'),('invalid_sender30','invalid'),('unbound_subscription30','unbound')]:
                valid=[v[field] for v in notes if v[field] is not None]
                x[name]=sum(valid) if valid and views['notify'] else None
            for r in ['registry','cache','route','notify']:x[r+'_age']=min(60,t-views[r]['t']) if views[r] else None
            last_note=max([v['t'] for v in notes] or [-math.inf])
            x['route_after_notify_change']=int(any(v['kind']=='route_change' and 0<=v['t']-last_note<=30 for v in history)) if views['route'] and views['notify'] else None
            hard=bool((x['invalid_sender30'] or 0)>0 or (x['unbound_subscription30'] or 0)>0)
            strict=hard or any((x[r+'_mismatch_age'] or 0)>=self.grace and x[r+'_registry_mismatch']==1 for r in ['route','cache'])
            enough=len(domains)>=2 and not conflicts and (views['route'] is not None or views['cache'] is not None)
            output.append(dict(observed_at=t,entity=dict(zip(['consumer','nf_type','service'],k)),features=x,
                config_sha256=self.config_sha256,
                rules_alarm=strict,protocol_violation=hard,sufficient_evidence=bool(enough),
                availability_mask=''.join(str(x[r+'_available']) for r in ROLES)))
        return output

def extract(events,config):
    engine=Engine(config);tick=None;step=float(config.get('step_seconds',1));previous=-math.inf
    if not math.isfinite(step) or step<=0:raise ValueError('step_seconds must be finite and positive')
    for event in events:
        t=float(event['observed_at'])
        if not math.isfinite(t) or t<previous:raise ValueError('Unsorted/nonfinite observation stream')
        if tick is None:tick=math.ceil(t/step)*step
        while tick<t:
            yield from engine.snapshot(tick);tick+=step
        engine.ingest(event);previous=t
    if tick is not None and tick<=previous:yield from engine.snapshot(tick)

def matrix(rows):
    return [[math.nan if r['features'][f] is None else float(r['features'][f]) for f in FEATURES] for r in rows]

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--events',required=True);p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();config=json.loads(Path(a.config).read_text(encoding='utf-8'))
    with Path(a.events).open(encoding='utf-8') as stream,Path(a.output).open('w',encoding='utf-8') as out:
        for row in extract((json.loads(line) for line in stream if line.strip()),config):out.write(json.dumps(row,allow_nan=False)+'\n')
