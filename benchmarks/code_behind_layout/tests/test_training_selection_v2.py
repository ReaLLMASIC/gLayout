"""Software selection fixtures only; no physical measurements or training."""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from src.training import build_matched_samples
from src.training_selection_v2 import build_matched_samples_v2,make_rule
from scripts.derive_training_selection_v2 import frozen_base_selection


class SelectionV2Tests(unittest.TestCase):
    def fixture(self):
        objective={'id':'area','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'}
        rule={'status':'frozen','version':'fixture_v1','coverage_absolute_tolerance':0,
            'objectives':{'area':{**objective,'quality_absolute_tolerance':1e-8,
                'quality_relative_tolerance':1e-6,'quality_minimum_relative_effect':.01}}}
        def outcome(area,passing=True):
            point={'configuration_id':'dev','S1':True,'S2':passing,'baseline_S2':True,
                'objective':area if passing else None,'objective_definition':objective}
            return {'anchor':{**point,'configuration_id':'anchor'},'family':[point]}
        def candidate(name,trial,area):
            return {'initial_state_id':'state','parent_lineage':'compiler','origin':'natural',
                'base_source':{'layout.py':'full source fixture'},'visible_contract':{},'visible_feedback':[],
                'candidate_id':name,'candidate_patch':'fixture patch '+name,'proposal_generation':{'trial_id':trial},
                'verified':{**outcome(area),'baseline':outcome(100),'tool_log_ids':['fixture evidence '+name]}}
        sampling={'mode':'train_collection_action_gpt','trials':list(range(1,9))}
        return rule,sampling,candidate

    def test_equivalent_improvements_gain_one_state_and_never_tie_DPO(self):
        rule,sampling,row=self.fixture();before=copy.deepcopy(rule);rows=[row('late',8,80),row('early',2,80.4)]
        old,old_report=build_matched_samples(rows,rule)
        new,new_report=build_matched_samples_v2(rows,make_rule(rule,sampling))
        self.assertEqual(old['T1'],[]);self.assertEqual(old['T3'],[])
        self.assertEqual(len(new['T1']),1);self.assertEqual(len(new['T2']),1)
        self.assertEqual(new['T1'][0]['candidate_id'],'early');self.assertEqual(new['T2'][0]['candidate_id'],'early')
        self.assertEqual(new['T3'],[]);self.assertEqual(new['T4'],[])
        self.assertEqual(new_report['initial_states'],1);self.assertEqual(new_report['SFT_choices'][0]['methods']['T1']['actual_trial_value'],2)
        self.assertEqual(rule,before);self.assertFalse(new_report['tolerance_or_minimum_effect_changed'])

    def test_point_stays_anchor_only_while_family_preserves_its_scope_and_DPO(self):
        rule,sampling,row=self.fixture();a=row('anchor_late',8,70);b=row('anchor_early',1,70);family=row('family',2,80)
        for item in (a,b):item['verified']['family'][0].update(S2=False,objective=None)
        rows=[a,b,family];old,_=build_matched_samples(rows,rule);new,_=build_matched_samples_v2(rows,make_rule(rule,sampling))
        self.assertEqual(new['T1'][0]['candidate_id'],'anchor_early');self.assertEqual(new['T2'][0]['candidate_id'],'family')
        for method in ('T3','T4'):
            fields=lambda values:[(r['pair_id'],r['chosen'],r['rejected'],r['chosen_candidate_id'],r['rejected_candidate_id']) for r in values]
            self.assertEqual(fields(old[method]),fields(new[method]))
        self.assertNotEqual(new['T3'][0]['chosen_candidate_id'],new['T4'][0]['chosen_candidate_id'])

    def test_equivalent_best_without_meaningful_baseline_improvement_stays_excluded(self):
        rule,sampling,row=self.fixture();rows=[row('a',1,99.5),row('b',2,99.6)]
        new,report=build_matched_samples_v2(rows,make_rule(rule,sampling))
        self.assertEqual(new['T1'],[]);self.assertEqual(new['T2'],[])
        self.assertEqual(report['ambiguous_sft_states'],1)

    def test_actual_trial_identity_is_required_and_not_guessed_from_names(self):
        rule,sampling,row=self.fixture();value=row('trial_1_name_is_not_evidence',1,80);value['proposal_generation']={}
        with self.assertRaisesRegex(ValueError,'actual frozen'):build_matched_samples_v2([value],make_rule(rule,sampling))

    def test_complete_frozen_legacy_functions_keep_actual_comparison_semantics(self):
        root=Path(__file__).resolve().parents[1];source=frozen_base_selection((root/'src/training.py').read_text())
        namespace={};exec(compile(source,'frozen_selection_fixture.py','exec'),namespace)
        frozen=SimpleNamespace(**namespace);rule,sampling,row=self.fixture()
        candidates=[row('late',8,80),row('early',1,80.4),row('worse',3,95)]
        actual=build_matched_samples_v2(candidates,make_rule(rule,sampling))
        captured=build_matched_samples_v2(candidates,make_rule(rule,sampling),frozen)
        self.assertEqual(actual,captured)


if __name__=='__main__':unittest.main()
