"""Synthetic mechanics test, never used as experimental evidence."""
import json,tempfile,unittest
from pathlib import Path
import ml_evaluate as ev
from ml_stage import plan
from ml_features import FEATURES

class PipelineTest(unittest.TestCase):
    def test_split_freeze_and_scoring(self):
        items=plan();sets={p:{i['seed'] for i in items if i['stage']==p} for p in ['train','cal','test']}
        self.assertFalse(sets['train'] & sets['test']);self.assertFalse(sets['cal'] & sets['test'])
        self.assertFalse(sets['cal'] & sets['train'])
        prior=ev.STATE
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as temp:
            ev.STATE=Path(temp);records=[]
            try:
                for index,item in enumerate(items):
                    name='synthetic-'+str(index);label=int(item['alpha']>0)
                    records.append(dict(name=name,item=item,eligible=True))
                    values=[dict(window=k,x=[label*5+k*.01]*len(FEATURES),age_aware=label,cusum=label*10) for k in range(10)]
                    (ev.STATE/(name+'.ml.json')).write_text(json.dumps(dict(window_scores=values)))
                ev.freeze([r for r in records if r['item']['stage']!='test'])
                before=(ev.STATE/'freeze.json').read_bytes()
                ev.evaluate(records);ev.freeze(records)
                self.assertEqual(before,(ev.STATE/'freeze.json').read_bytes())
                result=json.loads((ev.STATE/'evaluation.json').read_text())
                self.assertTrue(result['complete']);self.assertEqual(len(result['by_run']),24*5)
            finally:ev.STATE=prior

if __name__=='__main__':unittest.main()
