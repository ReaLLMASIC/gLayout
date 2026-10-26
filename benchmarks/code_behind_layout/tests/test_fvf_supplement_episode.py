"""Software fixtures only; no EDA/model/hidden measurements."""
import copy
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts import fvf_supplement_episode as f
from scripts import fvf_supplement_point as physical
from scripts import prepare_fvf_search_supplement as prep
from src.e3_episode_state import EpisodeState


def saved(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def gateway(directory,method='R'):
    p=Path(directory);g=f.Gateway.__new__(f.Gateway);g.out=p;g.private=p/'private';g.private.mkdir()
    points=[{'configuration_id':'anchor','role':'anchor','parameters':{'w':1}},
        {'configuration_id':'dev1','role':'development','parameters':{'w':2}}]
    g.state=EpisodeState(method,points,41,'min',{'uncertainty':1,'low_margin':1})
    g.state.value.update(status='RUNNING',formal_trial=False,full_evaluations=0,physical_events=[],resource_waits=[],
        in_flight=None,deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat(),decisions=0,patch_attempts=0)
    g.packet={'budget':{'deadline_utc':g.state.value['deadline_utc']},
        'visible_sources':{'layout.py':'x=1\n'},'allowed_paths':['layout.py'],'visible_configurations':['anchor','dev1']}
    g.manifest={'budget':copy.deepcopy(f.BUDGET)};g.origin_manifest=p/'manifest.json'
    g.source=Mock(return_value=p/'source');g.write=Mock();return g


class FVFSupplementEpisodeTests(unittest.TestCase):
    def test_fixed20_is_one_task_four_methods_five_fresh_trials(self):
        rows=f.matrix();self.assertEqual(len(rows),20)
        self.assertEqual(len({(r['task_id'],r['method'],r['trial_id']) for r in rows}),20)
        self.assertEqual({r['task_id'] for r in rows},{f.TASK})
        self.assertTrue(all(r['selection_seed']==f.SEEDS[int(r['trial_id'])-1] for r in rows))

    def test_actual_nested_sizing_projects_only_WL_for_existing_selector(self):
        original=[{'configuration_id':'anchor','role':'anchor','parameters':{'local_current_bias_params':[3.76,3.]}},
            {'configuration_id':'dev1','role':'development','parameters':{'local_current_bias_params':[3.8,3.1]}}]
        before=copy.deepcopy(original);projected=f.selector_points(original)
        state=EpisodeState('C',projected,41,'min',{'failure_probability':0,'changed_call_coverage':0,'uncertainty':1,'low_margin':1})
        self.assertEqual(set(state.value['bounds']),{'local_current_bias_width_um','local_current_bias_length_um'})
        self.assertEqual(original,before);self.assertEqual(state.next_configuration(),'anchor')
        with self.assertRaisesRegex(ValueError,'visible'):
            f.selector_points([{**original[0],'role':'hidden'}])

    def test_draft_formal_rejected_before_point_or_source_generation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';saved(p,{'cohort_id':f.COHORT,'status':f.DRAFT})
            with patch('src.candidate_executor.CandidateExecutor.execute') as execute,patch.object(f.main,'capsule') as generate:
                with self.assertRaisesRegex(ValueError,'DRAFT'):
                    physical.evaluate_supplement(p,'anchor',Path(d)/'point',formal=True)
            execute.assert_not_called();generate.assert_not_called()

    def test_request_uses_only_vendor_fvf_point_not_main_E1_gate(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d);g.packet.update(visible_sources={'layout.py':'x=1\n'},allowed_paths=['layout.py'],visible_configurations=['anchor','dev1'])
            row={'configuration_id':'anchor','objective':2.,'physical_feedback':{},'physical_call_reservations':1,
                'resource_samples':[{'fixture':True}],'checked':{'S0':True,'S1':True,'S2':True,'execution_integrity':'valid'}}
            with patch.object(physical,'evaluate_supplement',return_value=row) as point,patch.object(f.main,'evaluate') as e1,patch('scripts.e3_generation_qualify.gate') as outer:
                answer=g.action({'action':'request_evaluation','path':'','patch':'','configuration_ids':['anchor'],'fidelity':'pex_spice','summary':''})
            e1.assert_not_called();outer.assert_not_called();point.assert_called_once()
            self.assertEqual(g.state.value['full_evaluations'],1);self.assertTrue(answer['checked']['S2'])
            self.assertNotIn('analysis_validation',answer['checked']);self.assertEqual(g.state.next_configuration(),'dev1')

    def test_unknown_and_queue_budget_are_not_negative_observations(self):
        for integrity,status,calls in [('incomplete','INCOMPLETE_UNKNOWN',1),('budget_exhausted','BUDGET_EXHAUSTED',0)]:
            with self.subTest(integrity=integrity),tempfile.TemporaryDirectory() as d:
                g=gateway(d);row={'checked':{'S2':False,'execution_integrity':integrity},'resource_samples':[],'physical_call_reservations':calls}
                with patch.object(physical,'evaluate_supplement',return_value=row):g.physical('anchor',0,'search')
                self.assertEqual(g.state.value['status'],status);self.assertEqual(g.state.value['full_evaluations'],calls)
                self.assertEqual(g.state.current()['results'],{});self.assertIsNone(g.state.value['in_flight'])

    def test_hidden_never_enters_search_and_budget_does_not_call(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d)
            with patch.object(physical,'evaluate_supplement') as point:
                with self.assertRaisesRegex(ValueError,'Hidden'):g.physical('hidden',0,'search')
                g.state.value['full_evaluations']=8
                with self.assertRaisesRegex(ValueError,'budget'):g.physical('anchor',0,'search')
            point.assert_not_called()

    def test_edit_requires_original_actual_anchor_and_keeps_main_action_rule(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d)
            with patch.object(f.main,'apply_source_patch') as apply:
                with self.assertRaisesRegex(ValueError,'original anchor'):
                    g.action({'action':'propose_patch','path':'','patch':'--- a/layout.py\n+++ b/layout.py\n@@ -1 +1 @@\n-x=1\n+x=2\n','configuration_ids':[],'fidelity':'','summary':''})
            apply.assert_not_called()

    def test_missing_shared_release_blocks_postfreeze_before_call(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d);g.manifest={'status':f.FROZEN,'main_manifest':str(Path(d)/'main.json')}
            saved(Path(d)/'main.json',{'fixture':True})
            with patch.object(f.main,'require_release',side_effect=RuntimeError('release absent')),patch.object(g,'physical') as point:
                with self.assertRaisesRegex(RuntimeError,'release absent'):g.post_freeze()
            point.assert_not_called()

    def test_development_cannot_implicitly_postfreeze(self):
        with self.assertRaisesRegex(ValueError,'Development'):f.require_release({'status':f.DRAFT},Path('/fixture'))

    def test_release_requires_all20_distinct_sources_after_real12models(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m={'cohort_id':f.COHORT,'supplement_release_file':str(root/'release.json')}
            p=root/'index.json';saved(p,{'cohort_id':f.COHORT,'searches':[]})
            with patch.object(f,'verify_manifest',return_value=m),patch.object(f,'shared_release',return_value={'actual_trained_models':12}):
                with self.assertRaisesRegex(ValueError,'Exact20'):f.release(root/'manifest.json',p)
            self.assertFalse((root/'release.json').exists())

    def test_shared_release_requires1730_and12_not_boolean_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'main.json';saved(p,{})
            with patch.object(f.main,'require_release',return_value={'actual_trained_models':11,'sealed_searches':[{}]*1730}):
                with self.assertRaisesRegex(ValueError,'12 actual'):f.shared_release({'main_manifest':str(p)})

    def test_selected_source_change_after_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);episode=p/'episode';src=episode/'private/revisions/000/source';src.mkdir(parents=True)
            (src/'layout.py').write_text('original\n');saved(episode/'private/task.json',{'source_files':['layout.py']})
            saved(episode/'private/state.json',{'sealed':True,'selection':{'revision':0}})
            saved(p/'main.json',{'hidden_release_file':str(p/'mainrelease.json')});saved(p/'mainrelease.json',{})
            saved(p/'manifest.json',{});m={'status':f.FROZEN,'freeze_id':f.COHORT,'manifest_path':str(p/'manifest.json'),
                'main_manifest':str(p/'main.json'),'supplement_release_file':str(p/'release.json')}
            release={'status':'FROZEN_E3_FVF_SUPPLEMENT_EVALUATION_RELEASE','freeze_id':f.COHORT,
                'manifest_sha256':f.sha(p/'manifest.json'),'main_release_sha256':f.sha(p/'mainrelease.json'),
                'sealed_searches':[{'episode_directory':str(episode),'selected_source_sha256':{'layout.py':f.sha(src/'layout.py')}}]}
            release['sealed_searches'] += [{'episode_directory':str(p/('other%02d'%i)),
                'selected_source_sha256':{'layout.py':'unused_software_fixture'}} for i in range(19)]
            saved(p/'release.json',release);(p/'release.json').chmod(0o444)
            with patch.object(f,'shared_release'):
                f.require_release(m,episode);(src/'layout.py').write_text('changed\n')
                with self.assertRaisesRegex(ValueError,'changed after'):f.require_release(m,episode)

    def test_failed_point_cost_keeps_no_run_and_missing_CPU(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d);p=Path(d)/'point.json';saved(p,{'physical_call_reservations':0,'point_wall_seconds':3.,'point_parent_CPU_seconds':.1,
                'actual_costs_by_stage':{'candidate':{'wall_seconds':2.,'waited_child_CPU_seconds':None}}})
            g.state.value['physical_events']=[{'stage':'search','status':'RETURNED','point_record':str(p)}]
            cost=g.costs()['search'];self.assertEqual(cost['physical_calls'],0);self.assertEqual(cost['missing_CPU_records'],1)
            self.assertEqual(cost['point_wall_seconds'],3.)

    def test_only_new_copy_paths_rebase_not_text_or_primary(self):
        old=Path('/fixture/draft');new=Path('/fixture/frozen')
        value={'own':'/fixture/draft/private/task.json','main':'/fixture/main/manifest.json','text':'see /fixture/draft/private/task.json'}
        r=prep.rebase(value,old,new)
        self.assertEqual(r['own'],'/fixture/frozen/private/task.json');self.assertEqual(r['main'],value['main']);self.assertEqual(r['text'],value['text'])

    def test_formal_point_fixes_existing_phase_role_and_cohort(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);out=p/'point';out.mkdir();run=out/'physical/fixture';saved(run/'manifest.json',{'status':'BUDGET_EXHAUSTED'})
            task={'task_id':f.TASK,'source_files':[],'entrypoint':'generator.py','parent_lineage':'fixture'}
            point={'parameters':{},'reference_id':'fixture'};prepared=(task,point,p,p,[],{})
            m={'status':f.FROZEN,'cohort_id':f.COHORT,'freeze_id':f.COHORT}
            with patch.object(physical,'ROOT',physical.SERVER),patch.object(physical,'prepare_inputs',return_value=prepared),patch('scripts.qualify_telescopic_supplement.resource_gate'),patch('src.candidate_executor.CandidateExecutor.execute',return_value={'run_directory':str(run)}) as execute,patch('scripts.e1_matched_runner.visible_feedback',return_value={}):
                row=physical._evaluate(p/'task.json','anchor',out,supplement=m)
            kwargs=execute.call_args.kwargs
            self.assertEqual(kwargs['phase'],'formal_E3');self.assertEqual(kwargs['context']['source_role'],'formal_E3_candidate')
            self.assertEqual(kwargs['context']['cohort_id'],f.COHORT);self.assertTrue(row['formal_trial'])

    def test_direct_formal_hidden_point_api_requires_release_before_tools(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);saved(p/'task.json',{'configurations':[{'configuration_id':'hidden','role':'hidden'}]})
            m={'status':f.FROZEN,'task':str(p/'task.json')}
            with patch.object(f,'verify_manifest',return_value=m),patch.object(f,'require_hidden_source',side_effect=ValueError('release absent')),patch.object(physical,'_evaluate') as point:
                with self.assertRaisesRegex(ValueError,'release absent'):
                    physical.evaluate_supplement(p/'manifest.json','hidden',p/'output',formal=True)
            point.assert_not_called();inv=json.loads((p/'output/point_api_invocation.json').read_text())
            self.assertFalse(inv['returned_point']);self.assertIsNone(inv['actual_physical_calls'])

    def test_freeze_copy_keeps_complete_editable_file_writable_in_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);base=p/'base';target=base/f.EDITABLE;target.parent.mkdir(parents=True)
            target.write_text('x=1\n');(base/'generator.py').write_text('# readonly\n')
            for item in base.rglob('*'):item.chmod(0o555 if item.is_dir() else 0o444)
            base.chmod(0o555)
            task={'task_id':f.TASK,'source_pack_base':str(base),'source_files':[f.EDITABLE,'generator.py'],
                'source_overrides':{f.EDITABLE:str(target)},'frozen_source_overrides':{},'editable_paths':[f.EDITABLE],'entrypoint':'generator.py'}
            saved(p/'task.json',task);f.main.capsule(p/'task.json',p/'work')
            patchtext='--- a/'+f.EDITABLE+'\n+++ b/'+f.EDITABLE+'\n@@ -1 +1 @@\n-x=1\n+x=2\n'
            f.main.apply_source_patch(p/'work',patchtext,[f.EDITABLE])
            self.assertEqual((p/'work'/f.EDITABLE).read_text(),'x=2\n');self.assertEqual(target.read_text(),'x=1\n')
            self.assertEqual(target.stat().st_mode&0o777,0o444);self.assertEqual(base.stat().st_mode&0o777,0o555)

    def test_source_index_mismatch_cannot_start_freeze_audit_or_write_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);saved(p/'index.json',{'revision':'a'*40,'files_sha256':{}})
            m={'implementation_sha256':{'scripts/fvf_supplement_episode.py':'wrong'}}
            with patch.object(f,'verify_manifest',return_value=m),patch.object(prep,'reopen_controls') as audit:
                with self.assertRaisesRegex(ValueError,'committed source'):
                    prep.freeze(p/'draft.json',p/'index.json',p/'output')
            audit.assert_not_called();self.assertFalse((p/'output').exists())

    def test_freeze_rebase_preserves_exact_trusted_JSON_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'contract.json';raw=b'{"fixture_only":1, "format":"not canonical"}\n\n';p.write_bytes(raw)
            p.chmod(0o444);prep.rebase_json_copy(p,Path('/old/prep'),Path('/new/freeze'))
            self.assertEqual(p.read_bytes(),raw);self.assertEqual(p.stat().st_mode&0o777,0o444)
            p.chmod(0o644);p.write_text('{"source":"/old/prep/base"}')
            prep.rebase_json_copy(p,Path('/old/prep'),Path('/new/freeze'))
            self.assertEqual(json.loads(p.read_text())['source'],'/new/freeze/base')

    def test_original_baseline_absent_release_reserves_no_point(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'baseline'
            with patch.object(f,'verify_manifest',return_value={}),patch.object(f,'released_manifest',side_effect=ValueError('both releases absent')),patch.object(physical,'evaluate_supplement') as evaluate:
                with self.assertRaisesRegex(ValueError,'releases absent'):
                    f.original_baseline(Path(d)/'manifest.json',output)
            evaluate.assert_not_called();self.assertFalse(output.exists())

    def test_reserved_point_missing_stage_cost_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            g=gateway(d);p=Path(d)/'point.json';base={'point_wall_seconds':3.,'point_parent_CPU_seconds':.1,'actual_costs_by_stage':{}}
            saved(p,{**base,'physical_call_reservations':1})
            g.state.value['physical_events']=[{'stage':'search','status':'RETURNED','point_record':str(p)}]
            cost=g.costs()['search']
            self.assertIsNone(cost['waited_child_CPU_seconds']);self.assertEqual(cost['missing_CPU_records'],1)
            self.assertEqual(cost['unresolved_calls'],1);self.assertFalse(cost['CPU_total_complete'])
            saved(p,{**base,'physical_call_reservations':0});cost=g.costs()['search']
            self.assertEqual(cost['waited_child_CPU_seconds'],0);self.assertEqual(cost['missing_CPU_records'],0)
            saved(p,{**base,'physical_call_reservations':1,'checked':{'execution_integrity':'incomplete'},
                'actual_costs_by_stage':{'trusted':{'wall_seconds':2.,'waited_child_CPU_seconds':4.}}})
            cost=g.costs()['search'];self.assertEqual(cost['waited_child_CPU_seconds'],4.)
            self.assertTrue(cost['CPU_total_complete'])
            run=Path(d)/'run';saved(run/'manifest.json',{'status':'RUNNING'})
            row=json.loads(p.read_text());row['run_directory']=str(run);saved(p,row)
            cost=g.costs()['search'];self.assertIsNone(cost['waited_child_CPU_seconds'])
            self.assertEqual(cost['known_waited_child_CPU_seconds'],4.);self.assertEqual(cost['unresolved_calls'],1)
            saved(run/'manifest.json',{'status':'EVALUATED','trusted':{'container_state':{'Running':False}}})
            self.assertEqual(g.costs()['search']['waited_child_CPU_seconds'],4.)

    def test_relative_freeze_CLI_rebases_absolute_paths_to_new_readonly_copy(self):
        # Reproduces the actual failed first freeze: CLI relative path, JSON
        # absolute paths. Every artifact here is an explicit temporary fixture.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();draft=root/'runtime/task_preparation/fixture_draft'
            output=root/'runtime/protocol_freezes/fixture_new_copy'
            saved(draft/'public/packet.json',{'fixture_only':True})
            saved(draft/'public/capacity.json',{'cohort_id':f.COHORT,'all_fit':True,
                'packet_sha256':f.sha(draft/'public/packet.json')})
            saved(draft/'private/task.json',{'source_pack_base':str(draft/'base'),
                'source_overrides':{'layout.py':str(draft/'base/layout.py')},
                'configurations':[{'reference_file':str(draft/'private/ref.spice')}],
                'status':'SOFTWARE_FIXTURE_ONLY'})
            (draft/'private/ref.spice').write_text('* software fixture only\n')
            (draft/'base').mkdir();(draft/'base/layout.py').write_text('# fixture only\n')
            m={'status':f.DRAFT,'preparation':str(draft),'task':str(draft/'private/task.json'),
                'packet':str(draft/'public/packet.json'),'manifest_path':str(draft/'manifest.json'),
                'implementation_sha256':{},'file_sha256':{}}
            saved(draft/'manifest.json',m);saved(root/'index.json',{'revision':'a'*40,'files_sha256':{}})
            original=(draft/'private/task.json').read_bytes();cwd=Path.cwd()
            try:
                os.chdir(root)
                with patch.object(prep,'ROOT',root),patch.object(f,'verify_manifest',return_value=m),patch.object(prep,'reopen_controls'):
                    prep.freeze(Path('runtime/task_preparation/fixture_draft/manifest.json'),root/'index.json',output)
            finally:os.chdir(cwd)
            final=json.loads((output/'manifest.json').read_text());task=json.loads((output/'private/task.json').read_text())
            self.assertEqual(final['preparation'],str(output));self.assertEqual(final['task'],str(output/'private/task.json'))
            self.assertEqual(final['manifest_path'],str(output/'manifest.json'))
            self.assertEqual(task['source_pack_base'],str(output/'base'))
            self.assertEqual(task['source_overrides']['layout.py'],str(output/'base/layout.py'))
            self.assertEqual(task['configurations'][0]['reference_file'],str(output/'private/ref.spice'))
            self.assertEqual((draft/'private/task.json').read_bytes(),original)
            self.assertEqual((output/'private/ref.spice').read_bytes(),(draft/'private/ref.spice').read_bytes())
            self.assertTrue(all(not(p.stat().st_mode&0o222) for p in output.rglob('*') if p.is_file()))
            self.assertTrue((draft/'private/task.json').stat().st_mode&0o222)


if __name__=='__main__':unittest.main()
