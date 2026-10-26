"""Software archive fixtures, never physical measurements."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.archive_e3_evidence import archive_point, archive_search, restore_run


class E3ArchiveTests(unittest.TestCase):
    def fixture(self, root, phase='development_E3_fixture', name='executor_fixture'):
        point = root/'point';run = point/'physical'/name
        for name in ('source', 'trusted', 'accepted', 'evidence', 'candidate_stage', 'trusted_stage'):
            (run/name).mkdir(parents=True)
        for name, value in {'source/layout.py': b'complete source\n',
                'trusted/reference.spice': b'* software fixture\n', 'accepted/candidate.gds': b'fixture GDS bytes',
                'evidence/raw.dat': b'0.0 1.0\n'*4096, 'candidate_stage/console.log': b'fixture console\n',
                'candidate_stage/resource_usage.json': b'{"child_user_cpu_seconds":1}\n',
                'trusted_stage/resource_usage.json': b'{"child_system_cpu_seconds":2}\n'}.items():
            (run/name).write_bytes(value)
        manifest = {'phase': phase, 'status': 'COMPLETE',
            'candidate': {'container_state': {'Running': False}},
            'trusted': {'container_state': {'Running': False}}}
        (run/'manifest.json').write_text(json.dumps(manifest))
        (point/'point.json').write_text(json.dumps({'run_directory': str(run)}))
        return point, run

    def test_verified_prune_retains_source_GDS_CPU_and_exact_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);point, run = self.fixture(root)
            before = {str(p.relative_to(run)): p.read_bytes() for p in run.rglob('*') if p.is_file()}
            (run/'evidence').chmod(0o555)
            with patch('scripts.archive_e3_evidence.ROOT', root):
                result = archive_point(point)
                self.assertEqual(result['status'], 'COMPRESSED_E3_RAW_RETAINED')
                self.assertEqual(result['new_physical_calls'], 0)
                self.assertFalse((run/'evidence/raw.dat').exists())
                for name in ('source/layout.py', 'trusted/reference.spice', 'accepted/candidate.gds',
                        'candidate_stage/resource_usage.json', 'trusted_stage/resource_usage.json'):
                    self.assertEqual((run/name).read_bytes(), before[name])
                restore_run(run)
                self.assertTrue(all((run/name).read_bytes() == value for name, value in before.items()))
                self.assertEqual(archive_point(point)['status'], 'COMPRESSED_E3_RAW_RETAINED')

    def test_running_and_foreign_phase_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);point, run = self.fixture(root, 'formal_E1')
            with patch('scripts.archive_e3_evidence.ROOT', root):
                with self.assertRaises(ValueError):
                    archive_point(point)
                manifest = json.loads((run/'manifest.json').read_text())
                manifest.update(phase='formal_E3', status='RUNNING')
                (run/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    archive_point(point)
            self.assertTrue((run/'evidence/raw.dat').exists())

    def test_measure_only_and_modified_retained_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);point, run = self.fixture(root)
            with patch('scripts.archive_e3_evidence.ROOT', root):
                result = archive_point(point, measure_only=True)
                self.assertTrue((run/'evidence/raw.dat').is_file())
                self.assertEqual(result['status'], 'VERIFIED_E3_ARCHIVE_RAW_NOT_REMOVED')
                archive_point(point)
                (run/'candidate_stage/resource_usage.json').write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    restore_run(run)

    def test_sealed_search_can_store_before_global_test_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);episode = root/'episode'
            point, run = self.fixture(episode/'private/points')
            (episode/'public').mkdir();(episode/'public/search.json').write_text('{"status":"SEARCH_FINISHED"}')
            state = {'phase': 'formal_E3', 'sealed': False, 'in_flight': None, 'post_freeze_started': False}
            state_path = episode/'private/state.json';state_path.write_text(json.dumps(state))
            with patch('scripts.archive_e3_evidence.ROOT', root):
                with self.assertRaises(ValueError):archive_search(episode)
                state['sealed'] = True;state_path.write_text(json.dumps(state))
                result = archive_search(episode)
                self.assertFalse(result['hidden_evaluation_dispatched'])
                self.assertEqual(result['events'][0]['new_physical_calls'], 0)
                self.assertTrue((run/'accepted/candidate.gds').is_file())
                self.assertFalse((run/'evidence/raw.dat').exists())
                self.assertFalse((episode/'public/episode.json').exists())

    def test_staged_F3_archives_all_three_actual_runs_without_repeating_physics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);episode = root/'episode';point = episode/'private/points/0001_anchor'
            stage_runs = {}
            for stage in ('physical_actual', 'nominal_actual', 'full_actual'):
                _, run = self.fixture(point/stage, 'formal_E3', name='executor_'+stage)
                stage_runs[stage] = {'run_directory': str(run)}
            (point/'point.json').write_text(json.dumps({'deferred': False, **stage_runs['full_actual']}))
            (point/'fidelity_point.json').write_text(json.dumps(stage_runs))
            (episode/'private/state.json').write_text(json.dumps({'phase': 'formal_E3', 'sealed': True,
                'in_flight': None, 'post_freeze_started': False}))
            (episode/'public').mkdir();(episode/'public/search.json').write_text('{"status":"SEARCH_FINISHED"}')
            with patch('scripts.archive_e3_evidence.ROOT', root):
                result = archive_search(episode)
                self.assertEqual(len(result['events']), 3)
                for row in stage_runs.values():
                    run = Path(row['run_directory']);self.assertFalse((run/'evidence/raw.dat').exists())
                    self.assertTrue((run/'accepted/candidate.gds').is_file())
                    self.assertTrue((run/'source/layout.py').is_file())
                    self.assertTrue((run/'trusted/reference.spice').is_file())
                    self.assertTrue((run/'candidate_stage/resource_usage.json').is_file())
                    restore_run(run);self.assertEqual((run/'evidence/raw.dat').read_bytes(), b'0.0 1.0\n'*4096)
                self.assertTrue(all(event['new_physical_calls'] == 0 for event in result['events']))
                self.assertFalse(result['hidden_evaluation_dispatched'])


if __name__ == '__main__':
    unittest.main()
