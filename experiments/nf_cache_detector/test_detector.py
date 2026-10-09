"""Synthetic software tests only: these are not experimental attack results."""
import copy,json,tempfile,unittest
from pathlib import Path
import joblib
from detector import Engine,FEATURES,extract,endpoint
from model import load_dataset,threshold_for,calibrate,train,score_rows

HERE=Path(__file__).resolve().parent
CONFIG=json.loads((HERE/'observer_config.json').read_text())
ENTITY=dict(consumer='ausf-lab-1',nf_type='UDM',service='nudm-ueau')
GOOD='http://udm.example:7777';BAD='http://unexpected.example:7777'
SOURCES=dict(registry_snapshot='nrf-audit',cache_snapshot='ausf-cache-audit',
             route='sbi-route-tap',notification='notify-ingress-tap',subscription_snapshot='nrf-subscription-audit')

def event(t,kind,data,source=None):
    return dict(observed_at=t,source=source or SOURCES[kind],kind=kind,entity=ENTITY.copy(),data=data)

def snapshot(t,kind,url=GOOD):
    return event(t,kind,dict(complete=True,endpoints=[url]))

def initial():
    return [snapshot(0,'registry_snapshot'),snapshot(0,'cache_snapshot'),event(0,'route',dict(endpoint=GOOD))]

def engine(config=CONFIG):
    e=Engine(copy.deepcopy(config))
    for item in initial():e.ingest(item)
    return e

class TelemetryTests(unittest.TestCase):
    def test_endpoint_normalization_and_no_subscriber_paths(self):
        self.assertEqual(endpoint('HTTP://UDM.EXAMPLE/'),endpoint('http://udm.example:80'))
        for value in ['http://user:pass@udm','http://udm/supi-123','http://udm?token=abc','ftp://udm']:
            with self.assertRaises(ValueError):endpoint(value)

    def test_collector_cannot_impersonate_role_or_self_grant_trust(self):
        e=engine()
        for source in ['sbi-route-tap','attacker']:
            item=snapshot(1,'registry_snapshot',BAD);item.update(source=source,trusted=True)
            with self.assertRaises(ValueError):e.ingest(item)
        self.assertFalse(e.snapshot(1)[0]['rules_alarm'])

    def test_benign_convergence_during_grace(self):
        e=engine();e.snapshot(0)
        e.ingest(snapshot(1,'registry_snapshot',BAD))
        self.assertFalse(e.snapshot(1)[0]['rules_alarm'])
        e.ingest(snapshot(3,'cache_snapshot',BAD));e.ingest(event(3,'route',dict(endpoint=BAD)))
        result=e.snapshot(8)[0]
        self.assertFalse(result['rules_alarm']);self.assertEqual(result['features']['route_registry_mismatch'],0)

    def test_persistent_cache_and_route_change_without_registry_change(self):
        e=engine();e.snapshot(0)
        e.ingest(event(1,'notification',dict(endpoints=[BAD],sender_verified=None)))
        e.ingest(snapshot(2,'cache_snapshot',BAD));e.ingest(event(2,'route',dict(endpoint=BAD)))
        before=e.snapshot(2)[0];after=e.snapshot(7)[0]
        self.assertFalse(before['rules_alarm']);self.assertTrue(after['rules_alarm'])
        self.assertEqual(after['features']['route_after_notify_change'],1)
        self.assertIsNone(after['features']['invalid_sender30'])

    def test_unknown_sender_not_same_as_invalid_sender(self):
        for attestation,expected in [(None,False),(True,False),(False,True)]:
            e=engine();e.ingest(event(1,'notification',dict(endpoints=[GOOD],sender_verified=attestation)))
            self.assertEqual(e.snapshot(1)[0]['protocol_violation'],expected)

    def test_subscription_present_absent_and_unknown(self):
        for bindings,expected in [(None,None),([],1),([dict(callback_context='cb',valid_until=20)],0),([dict(callback_context='cb',valid_until=.5)],1)]:
            e=engine()
            if bindings is not None:e.ingest(event(0,'subscription_snapshot',dict(complete=True,bindings=bindings)))
            e.ingest(event(1,'notification',dict(endpoints=[GOOD],callback_context='cb')))
            self.assertEqual(e.snapshot(1)[0]['features']['unbound_subscription30'],expected)
        e=engine();e.ingest(event(0,'subscription_snapshot',dict(complete=True,bindings=[])))
        e.ingest(event(1,'notification',dict(endpoints=[GOOD])))
        self.assertIsNone(e.snapshot(1)[0]['features']['unbound_subscription30'])

    def test_stale_or_failed_observer_is_unknown(self):
        e=engine();e.ingest(event(1,'health',dict(available=False),source='nrf-audit'))
        self.assertIsNone(e.snapshot(1)[0]['features']['route_registry_mismatch'])
        row=e.snapshot(16)[0]
        self.assertIsNone(row['features']['route_registry_mismatch']);self.assertFalse(row['sufficient_evidence'])

    def test_same_domain_is_not_independent(self):
        cfg=copy.deepcopy(CONFIG)
        for source in cfg['sources'].values():source['domain']='shared'
        row=engine(cfg).snapshot(0)[0]
        self.assertEqual(row['features']['independent_domains'],1);self.assertFalse(row['sufficient_evidence'])

    def test_conflicting_observers_do_not_choose_convenient_truth(self):
        cfg=copy.deepcopy(CONFIG);cfg['sources']['second-nrf']=dict(role='registry',domain='second',trusted=True)
        e=engine(cfg);item=snapshot(0,'registry_snapshot',BAD);item['source']='second-nrf';e.ingest(item)
        row=e.snapshot(0)[0]
        self.assertEqual(row['features']['source_conflicts'],1);self.assertFalse(row['sufficient_evidence'])
        self.assertIsNone(row['features']['route_registry_mismatch'])

    def test_future_events_cannot_change_emitted_prefix(self):
        prefix=initial()+[event(3,'route',dict(endpoint=GOOD))]
        future=prefix+[snapshot(4,'cache_snapshot',BAD),event(7,'route',dict(endpoint=BAD))]
        self.assertEqual(list(extract(prefix,CONFIG)),[r for r in extract(future,CONFIG) if r['observed_at']<=3])
        rows=list(extract(initial(),CONFIG));self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['availability_mask'],'11100')
        self.assertEqual(set(rows[0]['features']),set(FEATURES))
        self.assertNotIn('udm.example',json.dumps(rows[0]['features']))

    def test_nonfinite_or_retroactive_time_is_rejected(self):
        e=engine();e.snapshot(3)
        with self.assertRaises(ValueError):e.ingest(event(2,'route',dict(endpoint=GOOD)))
        with self.assertRaises(ValueError):list(extract([event(float('inf'),'route',dict(endpoint=GOOD))],CONFIG))

    def test_incomplete_snapshot_rejected(self):
        with self.assertRaises(ValueError):engine().ingest(event(1,'cache_snapshot',dict(complete=False,endpoints=[])))

class LearningTests(unittest.TestCase):
    def test_strict_threshold_and_minimum_calibration(self):
        self.assertEqual(threshold_for([0,1,2,3],.25),2)
        self.assertEqual(threshold_for([0,1,2,3],.001),3)
        rows=[dict(availability_mask='11100',sufficient_evidence=True,run_id='r1')]*1000
        self.assertEqual(calibrate(rows,[.1]*1000,3,1000,.001),{})
        shared=[dict(r,run_id=str(i),seed_group='one-capture') for i,r in enumerate(rows)]
        self.assertEqual(calibrate(shared,[.1]*1000,3,1000,.001),{})

    def fixture(self,folder,leak=False):
        base=engine().snapshot(0)[0];runs=[]
        for split,n in [('train',4),('calibration',3),('test',2)]:
            for run in range(n):
                name=f'{split}-{run}';rows=[];labels=[]
                label=int(split!='calibration' and run%2==1)
                for t in range(40):
                    row=copy.deepcopy(base);row['observed_at']=t
                    row['features']['route_registry_mismatch']=label
                    row['features']['route_mismatch_age']=min(t,60) if label else 0
                    row['rules_alarm']=bool(label and t>=5)
                    rows.append(row);labels.append(dict(observed_at=t,entity=ENTITY,label=label))
                fp=f'{name}.jsonl';lp=f'{name}-labels.jsonl'
                (folder/fp).write_text(''.join(json.dumps(r)+'\n' for r in rows))
                (folder/lp).write_text(''.join(json.dumps(r)+'\n' for r in labels))
                runs.append(dict(run_id=name,seed='shared' if leak else name,split=split,features=fp,labels=lp))
        path=folder/'manifest.json';path.write_text(json.dumps(dict(runs=runs)));return path

    def test_group_leakage_rejected(self):
        with tempfile.TemporaryDirectory(prefix='nf-cache-test-') as temp:
            with self.assertRaisesRegex(ValueError,'Seed group leaks'):load_dataset(self.fixture(Path(temp),True))

    def test_training_freeze_scoring_and_abstention(self):
        with tempfile.TemporaryDirectory(prefix='nf-cache-test-') as temp:
            folder=Path(temp);manifest=self.fixture(folder);out=folder/'model'
            # Reduced row minimum only for this software test; CLI scientific default stays 1000.
            report=train(manifest,out,HERE/'observer_config.json',minimum_rows=100)
            self.assertIn('11100',report['thresholds']['specialist'])
            bundle=joblib.load(out/'model.joblib');parts,_=load_dataset(manifest)
            self.assertIsNotNone(score_rows(parts['test'],bundle)[0]['ml_alarm'])
            row=copy.deepcopy(parts['test'][0]);row['availability_mask']='01100'
            self.assertEqual(score_rows([row],bundle)[0]['status'],'insufficient_evidence')
            row['config_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'configuration'):score_rows([row],bundle)
            with self.assertRaisesRegex(ValueError,'overwrite'):train(manifest,out,HERE/'observer_config.json')

if __name__=='__main__':unittest.main()
