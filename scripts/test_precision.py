import unittest
from assess_precision import assess

class PrecisionTests(unittest.TestCase):
    def rows(self):
        return [dict(policy=p,rho=r,seed=s,delta_pp=3) for p in ['swrr','random'] for r in [.2,.5,.7] for s in range(101,106)]

    def test_incomplete_matrix_cannot_trigger_confirmation(self):
        result=assess(self.rows()[:-1])
        self.assertFalse(result['first_stage_complete'])
        self.assertEqual(result['cells'][-1]['decision'],'insufficient_first_stage')

    def test_selection_depends_on_precision_not_effect_sign(self):
        rows=self.rows()
        for row in rows:
            row['delta_pp']=[-8,-4,0,4,8][row['seed']-101]
        result=assess(rows)
        self.assertTrue(result['first_stage_complete'])
        self.assertTrue(all(c['decision']=='independent_confirmation' and c['additional_pairs']==5 for c in result['cells']))

    def test_duplicate_seed_rejected(self):
        with self.assertRaises(ValueError):assess(self.rows()+[self.rows()[0]])

if __name__=='__main__':unittest.main()
