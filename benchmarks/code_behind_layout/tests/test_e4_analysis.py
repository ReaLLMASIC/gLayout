"""Statistical software controls only; no generated row is a research result."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.e4_analysis import SLOTS,VARIANTS,analyze
from scripts.analyze_e4 import load_episodes


def plan():
    return {'variants':list(VARIANTS),'evaluation_seed_slots':list(SLOTS),'inference_trials':3,'verification_method':'C',
        'tasks':[{'task_id':'t%d'%i,'source_group':'s%d'%(i//3),'merged_source_group':'m%d'%min(i//3,6),
            **({'topology_family':'OTA','ood':True} if i<3 else {})} for i in range(24)]}


def episode(task,variant,slot,trial,passed=8,unknown=0):
    return {**task,'policy_variant':variant,'training_seed':None if variant=='T0' else slot,'evaluation_seed_slot':slot,
        'trial_id':str(trial),'method':'C','status':'SEARCH_FINISHED','hidden_domain_size':16,'hidden_S2_verified':passed,
        'hidden_incomplete':unknown,'formal_trial':True,'hidden_results_exposed_to_policy':False,'selection':{'revision':1}}


class E4AnalysisTests(unittest.TestCase):
    def test_all1080_NOT_RUN_slots_remain_unknown_and_do_not_produce_CI(self):
        report=analyze(plan(),[])
        self.assertEqual(report['declared_episodes'],1080);self.assertEqual(report['NOT_RUN_episodes'],1080)
        method=report['methods']['T0'];self.assertEqual(method['declared_hidden_configuration_trials'],3456)
        self.assertEqual(method['coverage_identification_bounds'],[0,1]);self.assertIsNone(method['hidden_S2_coverage'])
        self.assertEqual(method['actual_model_count'],1);self.assertEqual(method['actual_training_seeds'],[])
        self.assertIsNone(method['descriptive_actual_training_seed_mean_variance'])
        self.assertIsNone(method['original_hidden_regression']['hidden_regression_rate'])
        self.assertTrue(all(not row['hierarchical_bootstrap'] for row in report['primary_contrasts']))

    def test_partial_success_and_hidden_not_released_preserve_denominators(self):
        manifest=plan();row=episode(manifest['tasks'][0],'T4',41,1,4,8)
        sealed=episode(manifest['tasks'][1],'T3',41,1)
        for key in ['hidden_domain_size','hidden_S2_verified','hidden_incomplete']:sealed.pop(key)
        report=analyze(manifest,[row,sealed]);method=report['methods']['T4']
        self.assertEqual(method['verified_hidden_S2'],4)
        self.assertAlmostEqual(method['coverage_identification_bounds'][1],(4+8+215*16)/3456)
        self.assertIsNone(method['hidden_S2_coverage']);self.assertFalse(report['primary_contrasts'][0]['primary_paired_complete'])
        self.assertFalse(report['primary_contrasts'][0]['bounds_are_confidence_intervals'])
        with self.assertRaisesRegex(ValueError,'Duplicate'):analyze(manifest,[row,row])

    def test_complete_matrix_uses_common_seed_pairing_and_source8_merged7(self):
        manifest=plan();rows=[episode(task,v,slot,trial,12 if v in ('T2','T4') else 8)
            for task in manifest['tasks'] for v in VARIANTS for slot in SLOTS for trial in range(1,4)]
        report=analyze(manifest,rows,replicates=40)
        self.assertTrue(report['full_matrix_hidden_complete']);self.assertEqual(report['recorded_episodes'],1080)
        for contrast in report['primary_contrasts']:
            self.assertEqual(contrast['fully_paired_tasks'],24)
            self.assertEqual({v['source_groups'] for v in contrast['hierarchical_bootstrap']},{7,8})
            for boot in contrast['hierarchical_bootstrap']:
                self.assertEqual(boot['joint_source_and_training_seed_percentile_95_CI'],[.25,.25])
                self.assertEqual(boot['actual_training_seeds'],[41,73,109])
        self.assertIn('unknown',report['strata']['topology']);self.assertIn('unknown',report['strata']['OOD'])

    def test_seed_and_source_variation_are_separate_conditional_sensitivities(self):
        manifest=plan();rows=[]
        for task in manifest['tasks']:
            for variant in VARIANTS:
                for slot_index,slot in enumerate(SLOTS):
                    for trial in range(1,4):
                        passed=8
                        if variant=='T4':passed=8+slot_index+(int(task['task_id'][1:])//3)%2
                        rows.append(episode(task,variant,slot,trial,passed))
        report=analyze(manifest,rows,replicates=100);contrast=report['primary_contrasts'][0]
        self.assertGreater(contrast['descriptive_between_training_seed_mean_variance'],0)
        for bootstrap in contrast['hierarchical_bootstrap']:
            self.assertGreater(bootstrap['conditional_training_seed_only_bootstrap_variance'],0)
            self.assertGreater(bootstrap['conditional_source_only_bootstrap_variance'],0)
        bad=copy.deepcopy(rows[0]);bad['training_seed']=41
        with self.assertRaisesRegex(ValueError,'T0 slots'):analyze(manifest,[bad])

    def test_regression_missing_join_is_null_not_zero_and_baseline_known_counts_are_preserved(self):
        manifest=plan();rows=[episode(task,'T4',slot,trial) for task in manifest['tasks'] for slot in SLOTS for trial in range(1,4)]
        for row in rows:
            row['regression_join']={'task_id':row['task_id'],'method':'C','trial_id':row['trial_id'],'status':'COMPLETE',
                'groups':{'hidden':{'declared_configurations':16,'original_verified_S2':8,'verified_regressions':2,
                    'selected_unknown_on_original_passes':0,'original_unknown':0}}}
        method=analyze(manifest,rows)['methods']['T4'];self.assertEqual(method['original_hidden_regression']['hidden_regression_rate'],.25)
        rows[0].pop('regression_join')
        result=analyze(manifest,rows)['methods']['T4']['original_hidden_regression']
        self.assertIsNone(result['hidden_regression_rate']);self.assertEqual(result['unavailable_joins'],1)
        self.assertEqual(result['unknown_original_configurations'],16)

    def test_index_binds_original_join_to_exact_backend_episode_and_sealed_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);row=episode(plan()['tasks'][0],'T1',41,1)
            (root/'episode.json').write_text(json.dumps(row));join={'episode_directory':'/backend/unique','sealed_source_revision':1}
            (root/'join.json').write_text(json.dumps(join));index={'episode_json':str(root/'episode.json'),'regression_json':str(root/'join.json'),'episode_directory':'/backend/unique'}
            (root/'index.jsonl').write_text(json.dumps(index)+'\n')
            actual=load_episodes(root/'index.jsonl');self.assertEqual(actual[0]['regression_join'],join)
            join['episode_directory']='/backend/other';(root/'join.json').write_text(json.dumps(join))
            with self.assertRaisesRegex(ValueError,'exact backend'):load_episodes(root/'index.jsonl')

    def test_validation_plateau_is_reported_without_changing_selection(self):
        models={'status':'FROZEN_E4_METHODS','formal_training_runs':12,'variants':{v:{'seeds':{str(s):{
            'selected_checkpoint':'/software-fixture/earliest','checkpoint_evaluations':[{'mean_task_S2_fraction':1},{'mean_task_S2_fraction':1}]}
            for s in SLOTS}} for v in VARIANTS[1:]}}
        report=analyze(plan(),[],models_manifest=models)['validation_checkpoint_selection']
        self.assertEqual(len(report['models']),12);self.assertTrue(all(v['selection_plateau'] for v in report['models']))
        self.assertFalse(report['selection_rule_changed'])


if __name__=='__main__':unittest.main()
