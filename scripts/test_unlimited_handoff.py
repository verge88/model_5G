import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import execute_main_v2 as controller
import unlimited_handoff as bridge

class HandoffTests(unittest.TestCase):
    def test_budget_unlimited_preserves_finite_default(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(controller,'STATE',Path(directory)):
            self.assertEqual(controller.budget_limit(),43200)
            (Path(directory)/'budget-control.json').write_text('{"unlimited":true}')
            self.assertIsNone(controller.budget_limit())

    def test_no_transfer_with_unfinished_or_failed_pair(self):
        item={'seed':102}
        state={'results':[],'in_flight':[{'item':item}]}
        self.assertFalse(controller.handoff_ready(state))
        state['results']=[{'item':item,'eligible_pair':False}]
        self.assertFalse(controller.handoff_ready(state))
        state['results'][0]['eligible_pair']=True
        self.assertTrue(controller.handoff_ready(state))

    @unittest.skipUnless(bridge.os.name=='nt','Windows virtualenv wrapper regression')
    def test_report_wrapper_transfer_waits_for_replacement_and_exits_75(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'ledger.json').write_text(json.dumps(dict(status='running',phase='main',approved_seconds=43200,
                                                              results=[],in_flight=[],failure=None)))
            parents=[json.dumps(dict(Name='python.exe',CommandLine='python report_main_v2.py',ParentProcessId=20)),
                     json.dumps(dict(Name='python.exe',CommandLine='python execute_main_v2.py --phase main --launch',ParentProcessId=30))]
            with patch.object(bridge,'STATE',folder),patch.object(controller,'budget_limit',return_value=None),\
                 patch.object(bridge.subprocess,'check_output',side_effect=parents),\
                 patch.object(bridge.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                with self.assertRaises(SystemExit) as exited:bridge.maybe_handoff()
                self.assertEqual(exited.exception.code,75)
                self.assertIn('--handoff',run.call_args_list[0].args[0])
                self.assertEqual(run.call_count,2)
                self.assertEqual(json.loads((folder/'unlimited-handoff.json').read_text())['status'],'replacement_finished')

if __name__=='__main__':unittest.main()
