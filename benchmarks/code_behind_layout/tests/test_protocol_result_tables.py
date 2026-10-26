"""Formula/schema fixtures only; these are not formal physical measurements."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_protocol_results import e2, export_e3_metadata, load_episodes
from src.protocol_result_tables import (e2_pool_table, e2_costs, e2_online_comparison,
    e3_supplement, e3_search_events, e3_budget_curves)


def e2_fixture():
    manifest = {'freeze_id': 'f', 'candidate_pool_size': 64}
    pool = {'pool_id': 'p', 'source_family': 'software_fixture', 'sizing_id': 's0'}
    rule = {'status': 'FROZEN_E2_ANALYSIS_PLAN', 'sealed_at_utc': '2026-01-01T00:00:00Z',
        'pause_evidence': 'actual_zero_acquisitions.json', 'execution_freeze_id': 'f',
        'candidate_denominator': 64, 'near_frontier': {'fraction': .2}, 'top_k': {'fraction': .2},
        'numeric_ties': {'prediction_absolute_tolerance': 0, 'actual_absolute_tolerance': 0, 'relative_tolerance': 0}}
    accepted = [{'stream_index': i, 'gds': 'gds'+str(i), 'geometry': {
        'physical_mask_bbox_area_um2': float(i+1), 'union_rectilinear_proxy_um': float(i+2)}} for i in range(64)]
    state = {'pool_id': 'p', 'method': 'full_oracle', 'phase': 'formal_E2', 'scope': 'fixed_candidate_full_oracle',
        'oracle_labels_read': False, 'accepted': accepted, 'status': 'TERMINAL',
        'attempts': [{'stream_index': i, 'generation_succeeded': True, 'accepted': True} for i in range(64)],
        'physical_observations': {}, 'nominal_observations': {}, 'full_evaluations': [
            {'stream_index': i, 'complete': True, 'S1': True, 'S2': True, 'worst_ugb_Hz': float(i+1),
                'full_electrical': {'physical_result': {'observation': {'corners': {'tt': {'metrics': {
                    'ugb': {'value': float(i+1), 'unit': 'Hz'}}}}}}}} for i in range(64)]}
    return manifest, pool, state, rule


def e3_fixture():
    tasks = [{'task_id': 't'+str(i), 'source_group': 's'+str(i//3),
        'merged_source_group': 'm'+str(min(i//3, 6))} for i in range(24)]
    manifest = {'freeze_id': 'e3', 'tasks': tasks, 'methods': ['A', 'R', 'B', 'C'], 'trials': 5,
        'analysis': {'cluster_bootstrap_replicates': 20, 'bootstrap_seed': 41}, 'budget': {'wall_seconds': 100}}
    episodes = [{**task, 'method': method, 'trial_id': str(trial), 'status': 'SEARCH_FINISHED',
        'hidden_domain_size': 16, 'hidden_S2_verified': 12 if method == 'C' else 8, 'hidden_incomplete': 0}
        for task in tasks for method in manifest['methods'] for trial in range(1, 6)]
    metadata = {'status': 'FROZEN_E3_PUBLIC_TASK_METADATA', 'freeze_id': 'e3', 'tasks': [
        {**task, 'injected_defect': False, 'initial_category': 'CLEAN_BUT_POOR_LEGAL_LAYOUT'} for task in tasks]}
    return manifest, episodes, metadata


class E2TablesTests(unittest.TestCase):
    def test_near_frontier_is_13_geometry_only_and_failed_candidates_consume_top_slots(self):
        manifest, pool, state, rule = e2_fixture()
        for row in state['full_evaluations'][:13]:
            row.update(S2=False, worst_ugb_Hz=None, full_electrical=None)
        report = e2_pool_table(manifest, pool, state, rule)
        self.assertEqual(report['near_frontier_indices'], list(range(13)))
        self.assertEqual(report['near_frontier']['physical_mask_bbox_area_um2']['matched_measured_pairs'], 0)
        self.assertEqual(report['top_k_recall']['physical_mask_bbox_area_um2']['recall'], 0)
        self.assertEqual(report['known_infeasible_full_results'], 13)
        self.assertEqual(report['declared_candidates'], 64)
        self.assertIsNone(report['same_N_prelayout']['rank_statistics'])

    def test_exact_ties_and_geometry_are_not_called_UGB_reversal_error(self):
        manifest, pool, state, rule = e2_fixture()
        report = e2_pool_table(manifest, pool, state, rule)
        feature = report['broad_pool']['physical_mask_bbox_area_um2']['statistics']
        self.assertAlmostEqual(feature['spearman_exact_ties'], -1)
        self.assertNotIn('effective_pair_reversal_rate', feature)
        nominal = report['broad_pool']['nominal_tt_ugb_Hz']['statistics']
        self.assertEqual(nominal['effective_pair_reversal_rate'], 0)
        self.assertEqual(report['candidates'][0]['nominal_acquisition'], 'TT_trace_inside_full_measurement_not_a_cheap_acquisition')
        self.assertEqual(report['broad_pool']['nominal_tt_ugb_Hz']['print_precision_sensitivity']['status'], 'UNAVAILABLE')
        self.assertIsNone(report['top_k_recall']['prediction_ugb_Hz']['recall'])

    def test_unknown_and_NOT_RUN_are_not_zero_UGB_or_infeasible(self):
        manifest, pool, state, rule = e2_fixture()
        state['full_evaluations'][0].update(complete=False, S2=False, worst_ugb_Hz=None)
        state['full_evaluations'].pop()
        report = e2_pool_table(manifest, pool, state, rule)
        self.assertFalse(report['oracle_complete'])
        self.assertEqual(report['unknown_or_NOT_RUN_candidates'], 2)
        self.assertIsNone(report['top_k_recall']['physical_mask_bbox_area_um2']['recall'])
        self.assertEqual(report['broad_pool']['nominal_tt_ugb_Hz']['status'], 'PARTIAL_CONDITIONAL_MEASURED_PAIRS')
        self.assertFalse(report['broad_pool']['nominal_tt_ugb_Hz']['formal_primary_available'])
        self.assertEqual(report['broad_pool']['nominal_tt_ugb_Hz']['inference_scope'],
            'EXPLORATORY_COMPLETE_CASE_SUBSET_NOT_FULL_POOL_PRIMARY')
        self.assertEqual(report['declared_candidates'], 64)

    def test_declaration_is_bound_and_unsealed_rule_is_only_exploratory(self):
        manifest, pool, state, rule = e2_fixture()
        rule['execution_freeze_id'] = 'another'
        with self.assertRaisesRegex(ValueError, 'not bound'):
            e2_pool_table(manifest, pool, state, rule)
        rule['status'] = 'DRAFT'
        result = e2_pool_table(manifest, pool, state, rule)
        self.assertEqual(result['analysis_rule_scope'], 'EXPLORATORY_UNSEALED_ANALYSIS_RULE')
        rule['numeric_ties']['actual_absolute_tolerance'] = 1
        with self.assertRaisesRegex(ValueError, 'exact numeric ties'):
            e2_pool_table(manifest, pool, state, rule)

    def test_repeated_cost_reference_counts_once_and_missing_CPU_stays_unknown(self):
        run = {'run_directory': 'actual1', 'cost': {'trusted': {'wall_seconds': 3., 'waited_child_CPU_seconds': None}}}
        report = e2_costs({'attempts': [run], 'physical': run})
        self.assertEqual(report['distinct_execution_runs'], 1)
        self.assertEqual(report['known_stage_wall_seconds_sum'], 3)
        self.assertIsNone(report['complete_waited_child_CPU_seconds'])
        missing = e2_costs({'physical': {'run_directory': 'missing'}})
        self.assertEqual(missing['missing_execution_cost_records'], 1)
        self.assertIsNone(missing['complete_waited_child_CPU_seconds'])

    def test_online_regret_requires_actual_same_masks_and_complete_oracle(self):
        manifest, pool, oracle, rule = e2_fixture()
        online = copy.deepcopy(oracle)
        online.update(method='fixed_area', scope='independently_executed_online')
        online['full_evaluations'] = online['full_evaluations'][:16]
        checked = []
        result = e2_online_comparison(manifest, pool, oracle, online, lambda a, b: checked.append((a, b)) or True)
        self.assertEqual(len(checked), 64)
        self.assertEqual(result['regret_Hz'], 48)
        self.assertEqual(result['quality_difference_interpretation'], 'observed_cross_extraction_quality_gap')
        self.assertFalse(result['deterministic_counterfactual_regret_established'])
        self.assertFalse(result['weighted_RC_equivalence_established'])
        self.assertEqual(result['online_unknown_or_NOT_RUN'], 48)
        with self.assertRaisesRegex(ValueError, 'masks differ'):
            e2_online_comparison(manifest, pool, oracle, online, lambda a, b: False)
        oracle['full_evaluations'][63].update(complete=False, S2=False, worst_ugb_Hz=None)
        incomplete = e2_online_comparison(manifest, pool, oracle, online, lambda a, b: True)
        self.assertIsNone(incomplete['regret_Hz'])
        self.assertEqual(incomplete['declared_candidates'], 64)
        self.assertEqual(incomplete['oracle_unknown_or_NOT_RUN'], 1)

    def test_cross_extraction_gap_preserves_negative_signed_difference_and_partial_denominator(self):
        manifest, pool, oracle, _ = e2_fixture()
        online = copy.deepcopy(oracle)
        online.update(method='fixed_area', scope='independently_executed_online')
        online['full_evaluations'] = online['full_evaluations'][:1]
        online['full_evaluations'][0]['worst_ugb_Hz'] = 80.
        result = e2_online_comparison(manifest, pool, oracle, online, lambda a, b: True)
        self.assertEqual(result['regret_Hz'], -16.)
        self.assertEqual(result['quality_difference_interpretation'], 'observed_cross_extraction_quality_gap')
        oracle['accepted'] = oracle['accepted'][:3]
        oracle['full_evaluations'] = oracle['full_evaluations'][:2]
        incomplete = e2_online_comparison(manifest, pool, oracle, online, lambda a, b: True)
        self.assertEqual(incomplete['status'], 'INCOMPLETE_OR_DIFFERENT_ACCEPTED_POOL')
        self.assertIsNone(incomplete['regret_Hz'])
        self.assertEqual(incomplete['declared_candidates'], 64)
        self.assertEqual(incomplete['oracle_unknown_or_NOT_RUN'], 62)

    def test_missing_oracle_report_and_uncomputed_replay_have_distinct_interpretations(self):
        manifest, pool, state, rule = e2_fixture()
        manifest.update(status='FROZEN', formal_execution_allowed=True, pools=[{**pool, 'online_selected': True}])
        rule['analysis_id'] = 'fixture_rule'
        state.update(method='fixed_area', scope='independently_executed_online')
        state['full_evaluations'] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); freeze = root/'manifest.json'; rule_file = root/'rule.json'
            execution = root/'execution.json'; point = root/'state.json'; idx = root/'index.jsonl'
            for path, value in ((freeze, manifest), (rule_file, rule), (point, state), (execution,
                    {'manifest': str(freeze), 'formal': True, 'method': 'fixed_area', 'pool_ids': ['p']})):
                path.write_text(json.dumps(value))
            idx.write_text(json.dumps({'state_json': str(point), 'execution_json': str(execution)})+'\n')
            result = e2(freeze, rule_file, idx)
        gap = result['real_online_comparisons'][0]
        self.assertEqual(gap['status'], 'ORACLE_NOT_SUPPLIED')
        self.assertEqual(gap['quality_difference_interpretation'], 'observed_cross_extraction_quality_gap')
        self.assertIsNone(gap['regret_Hz'])
        self.assertEqual(gap['oracle_unknown_or_NOT_RUN'], 64)
        self.assertEqual(result['offline_replay']['status'], 'NOT_COMPUTED_BY_THIS_CONSUMER')
        self.assertEqual(result['offline_replay']['interpretation'], 'pool_bound_replay_of_one_recorded_oracle')


class E3TablesTests(unittest.TestCase):
    def test_actual_source_clusters_not_480_episodes_and_empty_injection_stratum(self):
        manifest, episodes, metadata = e3_fixture()
        report = e3_supplement(manifest, episodes, metadata)
        contrasts = report['primary']['primary_contrasts']
        self.assertEqual({r['source_groups'] for r in contrasts}, {8, 7})
        self.assertTrue(all(r['task_mean_difference'] == .25 for r in contrasts))
        injected = report['strata']['tables']['injection']['injected']
        self.assertEqual(injected['tasks'], [])
        self.assertIsNone(injected['methods']['C']['coverage'])
        self.assertEqual(injected['paired_cluster_contrasts'], [])
        self.assertEqual(report['strata']['tables']['OOD']['unknown']['methods']['C']['declared_episodes'], 120)

    def test_missing_strata_or_baseline_are_unavailable_not_guessed(self):
        manifest, episodes, metadata = e3_fixture()
        report = e3_supplement(manifest, episodes[:1])
        self.assertEqual(report['strata']['status'], 'UNAVAILABLE_FROZEN_PUBLIC_METADATA_NOT_SUPPLIED')
        self.assertEqual(report['regression']['C']['unknown_original_configurations'], 1920)
        self.assertIsNone(report['regression']['C']['hidden_regression_rate'])
        metadata['status'] = 'DRAFT'
        with self.assertRaisesRegex(ValueError, 'actual frozen'):
            e3_supplement(manifest, [], metadata)

    def test_event_export_omits_hidden_and_uses_actual_return_after_host_reinspection(self):
        state = {'created_at_utc': '2026-01-01T00:00:00+00:00', 'deadline_utc': '2026-01-01T00:01:40+00:00',
            'method': 'C', 'trial_id': 1, 'formal_trial': True, 'status': 'SEARCH_FINISHED', 'physical_events': [
                {'stage': 'post_freeze_hidden', 'point_record': 'FORBIDDEN', 'status': 'RETURNED'},
                {'stage': 'search', 'revision': 0, 'configuration_id': 'a', 'status': 'RETURNED',
                    'ended_at_utc': '2026-01-01T00:00:30+00:00', 'point_record': 'visible'},
                {'stage': 'search', 'revision': 1, 'configuration_id': 'b', 'status': 'RETURNED',
                    'ended_at_utc': '2026-01-01T00:01:41+00:00', 'point_record': 'late'}]}
        point = {'task_id': 't0', 'configuration_id': 'a', 'checked': {'execution_integrity': 'valid', 'S0': True, 'S1': True, 'S2': True},
            'objective': 2., 'objective_definition': {'metric': 'area', 'unit': 'um2', 'direction': 'min'}}
        points = {'visible': point, 'late': {**point, 'configuration_id': 'b'}}
        report = {'task_id': 't0', 'method': 'C', 'trial_id': 1, 'formal_trial': True}
        result = e3_search_events(state, points, report, 100)
        self.assertEqual(len(result['events']), 2)
        self.assertNotIn('FORBIDDEN', json.dumps(result))
        self.assertEqual(result['events'][0]['elapsed_seconds'], 30)
        self.assertFalse(result['events'][1]['within_search_budget'])
        manifest = e3_fixture()[0]
        curves = e3_budget_curves(manifest, [result])
        c = curves['methods']['C']['tiers']['S2']['curve']
        self.assertEqual(c[-1]['verified'], 1)
        self.assertEqual(c[-1]['declared_episodes'], 120)
        self.assertEqual(c[-1]['success_identification_bounds'], [1/120, 1])
        with self.assertRaisesRegex(ValueError, 'fixed main'):
            e3_budget_curves(manifest, [result, result])

    def test_readonly_metadata_export_has_no_hidden_parameters_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prep = root/'packets'; qual = root/'qualification'; qual.mkdir()
            folder = prep/'private/t'; folder.mkdir(parents=True)
            task = {'status': 'FROZEN_E3_TASK', 'formal_admission': True, 'task_id': 't',
                'logical_group': 's', 'merge_sensitivity_group': 'm',
                'ancestry': {'origin': 'curated_fixed_layout_stream_development', 'injected_defect': False,
                    'production_natural_bug_claimed': False},
                'configurations': [{'role': 'hidden', 'parameters': {'DO_NOT_EXPORT': 987654}}]}
            (folder/'task.json').write_text(json.dumps(task)); (folder/'task.json').chmod(0o444)
            (qual/'raw_reinspection.json').write_text(json.dumps({'witnesses': [
                {'task_id': 't', 'classification': 'CLEAN_BUT_POOR_LEGAL_LAYOUT', 'qualifies_shortfall': True}]}))
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'status': 'FROZEN_E3', 'freeze_id': 'f', 'preparation': str(prep),
                'qualification': str(qual), 'tasks': [{'task_id': 't', 'source_group': 's', 'merged_source_group': 'm'}]})); manifest.chmod(0o444)
            result = export_e3_metadata(manifest)
            self.assertNotIn('DO_NOT_EXPORT', json.dumps(result))
            self.assertEqual(result['tasks'][0]['initial_category'], 'CLEAN_BUT_POOR_LEGAL_LAYOUT')
            self.assertFalse(result['tasks'][0]['production_natural_bug_claimed'])

    def test_sealed_search_without_post_evaluation_retains_16_unknown_and_bad_join_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/'search.json'; entry = root/'index.jsonl'
            path.write_text(json.dumps({'formal_trial': True, 'task_id': 't', 'method': 'C', 'trial_id': 1,
                'selection': {'revision': 0}})); entry.write_text(json.dumps({'episode_json': str(path), 'trial_id': 1})+'\n')
            result = load_episodes(entry, {})
            self.assertEqual(result[0]['hidden_incomplete'], 16)
            join = root/'regression.json'; join.write_text(json.dumps({'episode_directory': 'other', 'sealed_source_revision': 0}))
            entry.write_text(json.dumps({'episode_json': str(path), 'trial_id': 1, 'regression_json': str(join), 'episode_directory': 'correct'})+'\n')
            with self.assertRaisesRegex(ValueError, 'not bound'):
                load_episodes(entry, {})


if __name__ == '__main__':
    unittest.main()
