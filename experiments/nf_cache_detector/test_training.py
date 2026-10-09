"""Tests for provenance and reproducibility of the Actions training entry point."""
import json
import tempfile
import unittest
from pathlib import Path

from bootstrap import simulate, SCENARIOS, VISIBILITY
from detector import extract, FEATURES
from run_training import repository_path, validate_dataset_paths, summary

CONFIG = json.loads((Path(__file__).parent/'observer_config.json').read_text())


class TrainingWorkflowTests(unittest.TestCase):
    def test_state_machine_is_reproducible_and_visibility_does_not_change_labels(self):
        for scenario in SCENARIOS:
            events, truth = simulate(41, scenario, 'full', 120)
            self.assertEqual((events, truth), simulate(41, scenario, 'full', 120))
            self.assertEqual(any(truth.values()), 'poison' in scenario)
            for visibility in VISIBILITY:
                observed, labels = simulate(41, scenario, visibility, 120)
                self.assertEqual(labels, truth)
                rows = list(extract(observed, CONFIG))
                self.assertEqual(len(rows), 121)
                self.assertEqual(set(rows[0]['features']), set(FEATURES))
                self.assertTrue(all('label' not in e and 'poison' not in json.dumps(e) for e in observed))
                if visibility != 'full':
                    role = visibility.removeprefix('no_')
                    self.assertTrue(all(row['features'][role+'_available'] == 0 for row in rows))

    def test_full_simulation_has_no_oracle_provenance_flag(self):
        events, _ = simulate(12, 'persistent_poison', 'full')
        notes = [e for e in events if e['kind'] == 'notification']
        self.assertTrue(notes)
        self.assertTrue(all(e['data']['sender_verified'] is None for e in notes))

    def test_repository_manifest_path_cannot_escape_checkout(self):
        for value in [None, '', '../external.json', '/outside/manifest.json']:
            with self.assertRaises(ValueError):
                repository_path(value)

    def test_dataset_file_path_cannot_escape_manifest_folder(self):
        with tempfile.TemporaryDirectory(prefix='nf-cache-path-test-') as temp:
            root = Path(temp)
            (root/'external.jsonl').write_text('{}\n')
            (root/'dataset').mkdir()
            manifest = root/'dataset'/'manifest.json'
            manifest.write_text(json.dumps(dict(runs=[dict(features='../external.jsonl', labels='../external.jsonl')])))
            with self.assertRaises(ValueError):
                validate_dataset_paths(manifest)

    def test_summary_marks_synthetic_evidence(self):
        report = dict(thresholds=dict(specialist={}))
        text = summary(report, dict(by_model={}), 'synthetic-bootstrap')
        self.assertIn('not evidence of real attack detection', text)
        self.assertIn('NONE', text)


if __name__ == '__main__':
    unittest.main()
