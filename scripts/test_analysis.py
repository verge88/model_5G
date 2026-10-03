"""Regression tests against a real benign trace, plus exact-version timing.

Mutated copies are temporary adversarial fixtures, never research data.
"""
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from evaluate_article import audit
from analyze import propagation
from theory import stationary_share,capacity_share,fixed_residual_share

ROOT=Path(__file__).resolve().parents[1]

class TraceAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)/'fixture-cal-r20'
        source=ROOT/'runs/article-20261001-cal-r20'
        self.folder.mkdir()
        for pattern in ['*.log','manifest.json','workload.jsonl','ue.stdout','*-metrics.txt']:
            for file in source.glob(pattern):shutil.copy2(file,self.folder/file.name)

    def tearDown(self):self.tmp.cleanup()

    def test_real_trace_is_eligible(self):
        result,features=audit(self.folder)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['established'],360)
        self.assertEqual(result['n'],200)
        self.assertTrue(features)

    def test_ground_truth_does_not_enter_features(self):
        before,features=audit(self.folder)
        for path in self.folder.glob('smf?.log'):
            content=path.read_text()
            content=re.sub(r'(LAB_LOAD[^\n]*? active=)\d+',r'\g<1>999',content)
            content=re.sub(r'(LAB_LOAD[^\n]*? reference=)[\d.]+',r'\g<1>999',content)
            path.write_text(content)
        after,mutated=audit(self.folder)
        self.assertEqual(features,mutated)
        self.assertGreater(after['max_abs_scp_ground_truth_difference'],before['max_abs_scp_ground_truth_difference'])

    def test_duplicate_creation_invalidates_trace(self):
        path=self.folder/'scp.log'
        content=path.read_text()
        line=next(x for x in content.splitlines() if 'LAB_SCP' in x and 'status=201' in x and '/sm-contexts/' in x)
        path.write_text(content+'\n'+line+'\n')
        result,_=audit(self.folder)
        self.assertFalse(result['eligible'])
        self.assertIn('duplicate_create',result['anomalies'])

    def test_unknown_version_invalidates_trace(self):
        path=self.folder/'amf.log'
        content=path.read_text()
        content=re.sub(r'(LAB_CANDIDATE[^\n]*? version=)\d+',r'\g<1>999999',content,count=1)
        path.write_text(content)
        result,_=audit(self.folder)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['candidate_version_mismatches'],1)

    def test_metric_mismatch_invalidates_trace(self):
        path=self.folder/'smf1-metrics.txt'
        path.write_text(re.sub(r'(fivegs_smffunction_sm_sessionnbr\{[^\n]*\} )[^\n]+',r'\g<1>999',path.read_text()))
        result,_=audit(self.folder)
        self.assertFalse(result['eligible'])

    def test_missing_candidate_invalidates_freshness_evidence(self):
        path=self.folder/'amf.log';lines=path.read_text().splitlines()
        index=next(i for i,line in enumerate(lines) if 'LAB_CANDIDATE' in line)
        del lines[index];path.write_text('\n'.join(lines))
        result,_=audit(self.folder)
        self.assertFalse(result['eligible'])
        self.assertFalse(result['checks']['all_candidates_present'])

    def test_missing_nrf_record_invalidates_causal_chain(self):
        path=self.folder/'nrf.log';lines=path.read_text().splitlines()
        path.write_text('\n'.join(line for line in lines if 'LAB_NRF' not in line))
        result,_=audit(self.folder)
        self.assertFalse(result['eligible'])
        self.assertGreater(result['broken_causal_chains'],0)

class TimingTests(unittest.TestCase):
    def test_equal_load_values_do_not_merge_distinct_versions(self):
        rows=[]
        for version,t in [(1,1000),(2,10000)]:
            for kind,offset,more in [('LOAD',0,{'reported':'20'}),('SEND',100,{'load':'20'}),
                                      ('NRF',400,{'stored':'20'}),('CANDIDATE',800,{}),('SELECT',900,{})]:
                rows.append(dict(kind=kind,nf='nf1',version=str(version),t=str(t+offset),**more))
        result=propagation(rows)
        self.assertEqual(len(result['chains']),2)
        self.assertAlmostEqual(result['compute_to_nrf']['median_ms'],.4)
        self.assertAlmostEqual(result['age_at_selection']['median_ms'],.9)

class EquilibriumTests(unittest.TestCase):
    def test_root_satisfies_original_weight_normalization(self):
        for rho in [.2,.5,.7]:
            for alpha,gamma in [(0,1),(.5,1),(0,1.5)]:
                s=capacity_share(rho,alpha,gamma)
                malicious=gamma*(1-3*rho*(1-alpha)*s)
                honest_total=2-3*rho*(1-s)
                self.assertAlmostEqual(s,malicious/(malicious+honest_total))
                if gamma==1:self.assertAlmostEqual(s,stationary_share(rho,alpha))

    def test_zero_additive_budget_has_no_theoretical_effect(self):
        self.assertAlmostEqual(fixed_residual_share(0),1/3)
        self.assertLess(fixed_residual_share(1)-1/3,.005)

if __name__=='__main__':unittest.main()
