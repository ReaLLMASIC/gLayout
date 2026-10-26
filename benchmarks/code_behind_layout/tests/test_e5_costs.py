"""Accounting/software fixtures only; these costs are not study measurements."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_e5_costs import e1_snapshot, policy_records, summarize_policy, training_attempts
from src.e5_costs import observed, physical_stages, quality_matched_reuse


def comparison():
    def row(index, cost):
        return {'arrival_ordinal': index, 'configuration_binding': {'N': 'software_fixture_N', 'z': index},
            'complete': True, 'S2': True, 'cost': cost}
    return {'protocol': 'deployment_stream', 'cost_measure': 'CPU_seconds', 'quality_contract': {'require_S2': True},
        'shared_upfront': {'data_generation_filtering': 1, 'training': 1, 'patch_search': 2},
        'shared_arrivals': [row(0, 1), row(1, 1)], 'instance_arrivals': [row(0, 4), row(1, 4)]}


class E5CostTests(unittest.TestCase):
    def test_unknown_is_not_zero_and_negative_cost_is_rejected(self):
        value = observed([1, None, 2])
        self.assertEqual(value['observed_sum'], 3);self.assertIsNone(value['complete_total'])
        self.assertEqual(value['unknown_records'], 1)
        with self.assertRaises(ValueError):observed([-1])

    def test_capsule_primitive_overlap_and_unresolved_CPU_are_explicit(self):
        rows = {'search': {'physical_calls': 1, 'waited_child_CPU_seconds': 2, 'missing_CPU_records': 0,
            'unresolved_calls': 1, 'capsule_preparation_CPU_seconds': 5, 'primitive_geometry_CPU_seconds': 3,
            'primitive_geometry_is_subset_of_capsule_preparation': True}}
        value = physical_stages(rows)['search']
        self.assertIsNone(value['complete_child_CPU_seconds']);self.assertEqual(value['capsule_preparation_CPU_seconds'], 5)
        rows['search']['primitive_geometry_is_subset_of_capsule_preparation'] = False
        with self.assertRaises(ValueError):physical_stages(rows)

    def test_positive_observed_crossing_is_quality_matched_without_extrapolation(self):
        value = quality_matched_reuse(comparison())
        self.assertEqual(value['status'], 'OBSERVED_CROSSING');self.assertEqual(value['observed_prefix_crossing_arrivals'], 2)
        self.assertIsNone(value['future_break_even_estimate']);self.assertIsNone(value['dollar_cost'])
        self.assertEqual(value['prefixes'][-1]['shared_cumulative_cost'], 6)

    def test_failed_work_is_charged_but_zero_success_is_undefined(self):
        value = comparison()
        for row in value['shared_arrivals']+value['instance_arrivals']:row['S2'] = False
        result = quality_matched_reuse(value)
        self.assertEqual(result['status'], 'NO_VERIFIED_SUCCESSES')
        self.assertIsNone(result['prefixes'][-1]['shared_cost_per_verified_success'])
        self.assertIsNone(result['observed_prefix_crossing_arrivals'])
        self.assertEqual(result['prefixes'][-1]['instance_cumulative_cost'], 8)

    def test_incomplete_quality_cost_and_hidden_protocol_cannot_establish_break_even(self):
        value = comparison();value['shared_arrivals'][0]['complete'] = False
        self.assertEqual(quality_matched_reuse(value)['status'], 'QUALITY_NOT_MATCHED_OR_UNKNOWN')
        value = comparison();value['shared_upfront']['training'] = None
        self.assertEqual(quality_matched_reuse(value)['status'], 'COST_INCOMPLETE')
        value = comparison();value['protocol'] = 'frozen_patch_hidden_transfer'
        with self.assertRaises(ValueError):quality_matched_reuse(value)

    def test_policy_PID_and_usage_come_from_actual_raw_records_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);work = root/'decisions/session/decision_000';work.mkdir(parents=True)
            (work/'invocation.json').write_text(json.dumps({'pid': 123, 'status': 'COMPLETED', 'wall_seconds': 2}))
            (work/'token_budget.json').write_text(json.dumps({'prompt_tokens': 10}))
            (work/'events.jsonl').write_text(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}})+'\n')
            rows = policy_records(root);value = summarize_policy(rows)
            self.assertEqual(value['actual_model_cli_invocations'], 1)
            self.assertEqual(value['provider_usage_fields_as_reported']['input_tokens']['complete_total'], 12)
            self.assertIsNone(value['logged_completion_tokens_including_EOS']['complete_total'])
            self.assertIsNone(value['billable_dollars'])
            (work/'invocation.json').write_text(json.dumps({'status': 'CONTEXT_REJECTED'}))
            self.assertEqual(policy_records(root), [])

    def test_T0_cannot_be_counted_as_a_training_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            filename = Path(temporary)/'attempt.json';filename.write_text('{"method":"T0"}')
            with self.assertRaisesRegex(ValueError, 'one base'):training_attempts([filename])

    def test_one_recorded_failure_keeps_all360_denominators_and359_not_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);policy = root/'policy';policy.mkdir()
            tasks = [{'task_id': 'task%02d' % i, 'stratum': 'reuse' if i < 12 else 'composition',
                'source_group': 'group%d' % (i//3), 'merged_source_group': 'merged%d' % min(i//3, 6)} for i in range(24)]
            manifest = {'status': 'FROZEN_E1', 'freeze_id': 'software_fixture', 'tasks': tasks,
                'task_ids': [t['task_id'] for t in tasks], 'methods': ['G0', 'G1', 'G2'], 'trials': 5, 'budget': {'wall_seconds': 1200}}
            jobs = [{'task_id': task['task_id'], 'method': method, 'trial_id': str(trial), 'status': 'NOT_RUN'}
                for task in tasks for method in manifest['methods'] for trial in range(1, 6)]
            episode = {**tasks[0], 'method': 'G0', 'trial_id': '1', 'phase': 'formal_E1', 'status': 'MODEL_FAILED',
                'analysis_search_status': 'MODEL_FAILURE', 'costs_by_stage': {},
                'search_budget_seconds': 1200, 'observed_search_wall_seconds': 2,
                'first_verified_times_seconds': {'S0': None, 'S1': None, 'S2': None},
                'final_anchor': {'complete': False, 'S0': False, 'S1': False, 'S2': False},
                'hidden': {'declared': 16, 'known': 0, 'S2_passed': 0}}
            (root/'manifest.json').write_text(json.dumps(manifest));(policy/'episode.json').write_text(json.dumps(episode))
            (policy/'policy_error.json').write_text(json.dumps({'error': 'ValueError: Source read is outside the task packet'}))
            jobs[0].update(status='RECORDED', episode_json=str(policy/'episode.json'), local_output_directory=str(policy))
            (root/'state.json').write_text(json.dumps({'manifest': str(root/'manifest.json'), 'freeze_id': 'software_fixture',
                'jobs': jobs, 'updated_at_utc': '2026-10-19T00:00:00+00:00', 'maximum_simultaneous_episodes': 4}))
            result = e1_snapshot(root/'state.json')
            self.assertEqual(result['declared_episodes'], 360)
            self.assertEqual(result['dispatch_status_counts'], {'RECORDED': 1, 'NOT_RUN': 359})
            self.assertEqual(result['recorded_failure_modes'], {'source_read_outside_packet': 1})
            self.assertEqual(result['statistical_progress']['methods']['G0']['tiers']['S2']['full_declared_denominator'], 120)
            self.assertEqual(result['unrecorded_episode_resource_totals_remain_unknown'], 359)


if __name__ == '__main__':unittest.main()
