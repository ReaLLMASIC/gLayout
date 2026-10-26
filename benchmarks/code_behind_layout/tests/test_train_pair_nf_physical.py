"""Software dispatch fixtures, never physical measurements."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.train_pair_nf_physical_qualification as qualification
from scripts.prepare_train_pair_nf_domains import declare


class NFPhysicalQualificationTests(unittest.TestCase):
    def test_ideal_proof_requires_the_entire_unchanged_grid(self):
        registry = json.loads((qualification.ROOT / 'tests/fixtures/train_pair_nf_parent_anchors.json').read_text())['registries']['C02']
        domain = declare('C02', registry)
        rows = []
        for point in domain['configurations']:
            corner = {'complete': True, 'operating_point_valid': True,
                      'metrics': {s['name']: s.get('min', s.get('max')) for s in point['contract']['specifications']}}
            rows.append({**point, 'status': 'RETURNED_IDEAL_ANALYSES', 'all_corner_ideal_specs_pass': True,
                         'corners': {name: copy.deepcopy(corner) for name in ['tt', 'ss', 'ff']}})
        result = {'status': 'COMPLETED_DECLARED_IDEAL_ATTEMPTS', 'selected_circuit': 'C02',
                  'points': rows, 'model_calls': 0, 'physical_layout_calls': 0}
        self.assertEqual(len(qualification.bind_ideal(domain, result)), 9)
        changed = copy.deepcopy(result); changed['points'][0]['parameters']['sizing']['M1']['w'] = 999
        with self.assertRaises(ValueError):
            qualification.bind_ideal(domain, changed)
        incomplete = copy.deepcopy(result); incomplete['points'].pop()
        with self.assertRaises(ValueError):
            qualification.bind_ideal(domain, incomplete)

    def test_unknown_stops_new_dispatches_without_retry_or_silent_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepared = root / 'prepared'; prepared.mkdir()
            trusted = prepared / 'trusted'; trusted.mkdir(); (trusted / 'evaluate.py').write_text('fixture')
            points = [{'configuration_id': str(index), 'parameters': {'configuration_id': str(index)},
                       'contract': {'reference_id': 'fixture'}} for index in range(9)]
            plan = {'circuit_id': 'C02', 'configurations': points, 'original_ideal_result': {}, 'gate_files': [],
                    'runtime': 'fixture', 'magic_runtime': 'fixture', 'container_image': 'fixture',
                    'trusted_bundle': str(trusted), 'dispatch_horizon_seconds': 3600,
                    'source_pack': 'fixture', 'source_files': ['generator.py'], 'entrypoint': 'generator.py',
                    'parent_lineage': 'fixture', 'pdk_revision': 'fixture'}
            (prepared / 'plan.json').write_text(json.dumps(plan))
            with patch.object(qualification, 'bind_ideal'), \
                 patch.object(qualification, 'resource_gate', return_value={'software_fixture': True}), \
                 patch.object(qualification, 'inspect_result', side_effect=ValueError('unknown test boundary')), \
                 patch('src.candidate_executor.CandidateExecutor') as executor:
                executor.return_value.execute.return_value = {'run_directory': 'software_fixture'}
                state = qualification.run(prepared, root / 'output')
                self.assertEqual(executor.return_value.execute.call_count, 1)
            self.assertEqual(state['status'], 'PAUSED_UNKNOWN_NO_RETRY')
            self.assertEqual(len(state['not_run_dispositions']), 8)
            self.assertTrue(all(row['status'] == 'NOT_RUN' for row in state['not_run_dispositions']))
            self.assertEqual(state['qualified_points'], 0)

    def test_expired_resource_gate_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(qualification.time, 'monotonic', return_value=5):
            self.assertIsNone(qualification.resource_gate(Path(tmp), 4))


if __name__ == '__main__':
    unittest.main()
