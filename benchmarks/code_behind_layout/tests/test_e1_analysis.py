import copy
import unittest

from src.e1_analysis import analyze_episodes
from scripts.analyze_e1 import analyze


def episode(task,method,success,group='a',status='COMPLETED'):
    return {'task_id':task,'method':method,'trial_id':1,'stratum':'composition','source_group':group,
        'merged_source_group':group,'status':status,'search_budget_seconds':20,'observed_search_wall_seconds':12,
        'first_verified_times_seconds':{'S0':2 if success else None,'S1':4 if success else None,'S2':5 if success else None},
        'final_anchor':{'complete':True,'S0':success,'S1':success,'S2':success},
        'hidden':{'declared':16,'known':16,'S2_passed':16 if success else 0}}


class E1AnalysisTests(unittest.TestCase):
    def test_failure_costs_time_to_success_remain_bounded_and_unknown_is_not_failure(self):
        rows=[episode('one','G0',True),episode('two','G0',False),
              episode('three','G0',False,status='INFRASTRUCTURE_PAUSED')]
        rows[-1]['hidden']['known']=0
        result=analyze_episodes(rows,expected_trials=1)['methods']['G0']
        self.assertEqual(result['tiers']['S2']['success_rate'],.5)
        self.assertEqual(result['tiers']['S2']['restricted_mean_time_seconds'],12.5)
        self.assertEqual(result['unresolved_or_not_run'],1)
        self.assertEqual(result['tiers']['S2']['full_declared_denominator'],3)
        self.assertEqual(result['tiers']['S2']['full_matrix_success_rate_identification_bounds'],[1/3,2/3])

    def test_bootstrap_counts_source_groups_and_preserves_reuse_composition(self):
        rows=[]
        for task,group in [('one','a'),('two','a'),('three','b')]:
            for method in ('G0','G1','G2'):rows.append(episode(task,method,method!='G0',group))
        result=analyze_episodes(rows,expected_trials=1,replicates=50)
        self.assertEqual(result['strata']['composition']['effects'][0]['source_groups'],2)
        self.assertEqual(result['strata']['composition']['effects'][0]['task_mean_difference'],1)
        self.assertFalse(result['strata']['reuse']['primary_analysis_complete_for_input'])
        self.assertEqual(result['strata']['reuse']['effects'],[])

    def test_missing_method_or_trial_blocks_paired_primary_analysis(self):
        result=analyze_episodes([episode('one','G0',True)],expected_trials=1)
        self.assertFalse(result['strata']['composition']['primary_analysis_complete_for_input'])
        self.assertEqual(result['strata']['composition']['effects'],[])

    def test_late_events_and_duplicated_trials_cannot_inflate_success(self):
        row=episode('one','G0',True);late=copy.deepcopy(row);late['first_verified_times_seconds']['S2']=21
        with self.assertRaises(ValueError):analyze_episodes([late],expected_trials=1)
        with self.assertRaises(ValueError):analyze_episodes([row,row],expected_trials=1)

    def test_undispatched_trials_retain_frozen_denominator_without_fake_failure_rates(self):
        manifest={'status':'FROZEN_E1','task_ids':['one'],'tasks':[{'task_id':'one','stratum':'composition',
            'source_group':'a','merged_source_group':'a'}],'methods':['G0','G1','G2'],'trials':5,
            'budget':{'wall_seconds':20},'freeze_id':'fixture'}
        result=analyze(manifest,[])
        self.assertEqual(result['planned_episodes'],15)
        self.assertEqual(result['observed_status_counts'],{'NOT_RUN':15})
        self.assertIsNone(result['methods']['G0']['tiers']['S2']['success_rate'])
        self.assertEqual(result['methods']['G0']['tiers']['S2']['full_matrix_success_rate_identification_bounds'],[0,1])
        self.assertEqual(result['strata']['composition']['effects'],[])


if __name__=='__main__':unittest.main()
