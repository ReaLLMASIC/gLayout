"""New NF scheduler regressions; no model, Docker, SPICE or labels are generated."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_nf_span_proposals as nf


class NFPhysicalSchedulerTests(unittest.TestCase):
    def test_generation_failure_keeps_current_store_classification_and_does_not_invent_rc_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'actual_run';run.mkdir();result={'run_directory':str(run)}
            with patch.object(nf.physical,'point_call',return_value=result):
                self.assertEqual(nf.point_call({}, {}, {}, root,root,'fixture_deadline'),result)
            report=json.loads((root/'full_RC_device_graph_audit.json').read_text())
            self.assertEqual(report['audit']['status'],'NOT_APPLICABLE_BEFORE_S1')
            self.assertTrue(report['audit']['not_a_negative_label'])

    def test_s1_without_required_full_rc_pauses_with_raw_audit_error(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'actual_run';(run/'evidence').mkdir(parents=True)
            value={'assessment':{'S1':True},'artifacts':{'pex':{'ports':['IN','OUT'],'netlist':'missing.spice','top_cell':'fixture'}}}
            (run/'evidence/validation.json').write_text(json.dumps(value))
            with patch.object(nf.physical,'point_call',return_value={'run_directory':str(run)}):
                with self.assertRaises(FileNotFoundError):nf.point_call({}, {'parameters':{'circuit':{'ports':['IN','OUT']}}}, {},root,root,'fixture_deadline')
            report=json.loads((root/'full_RC_device_graph_audit.json').read_text())
            self.assertEqual(report['audit']['status'],'UNKNOWN_RC_GRAPH_QUARANTINE')
            self.assertIn('missing.spice',report['audit']['error'])
            self.assertFalse(report['simulation_netlist_simplified'])

    def test_completion_arrives_during_physical_pass_late_candidate_runs_and_reject_is_never_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();output=root/'output';output.mkdir();events=[];executed=[]
            state={'status':'RUNNING','cells':[
                {'initial_state_id':'software_fixture','trial_id':1,'status':'PHYSICAL_PENDING'},
                {'initial_state_id':'software_fixture','trial_id':2,'status':'NOT_RUN'},
                {'initial_state_id':'software_fixture','trial_id':3,'status':'NOT_RUN'}]}
            plan={'output_root':str(raw)}
            def scan(*args):
                events.append('scan')
                if (raw/'completion.json').exists():
                    if state['cells'][1]['status']=='NOT_RUN':state['cells'][1]['status']='PHYSICAL_PENDING'
                    state['cells'][2]['status']='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'
            def physical(*args,**kwargs):
                events.append('physical')
                active=[r for r in state['cells'] if r['status']=='PHYSICAL_PENDING']
                self.assertEqual(len(active),1)
                executed.append(active[0]['trial_id']);active[0]['status']='ADMITTED_COMPLETE_DOMAIN'
                # The new completion becomes visible while this pass is actually active.
                (raw/'completion.json').write_text(json.dumps({'status':'SOFTWARE_FIXTURE_COMPLETED'}))
            def derive(*args):events.append('derive')
            with patch.object(nf.span,'scan_returned',side_effect=scan),patch.object(nf.physical,'physical_pass',side_effect=physical),patch.object(nf,'derive_nf',side_effect=derive),patch.object(nf.span,'raw_matrix',return_value={}):
                nf.cycle({},plan,{},[],{},state,output,None,root,lambda:None)
                self.assertEqual(events,['scan','physical','derive','scan'])
                self.assertEqual(state['status'],'RUNNING');self.assertEqual(state['cells'][1]['status'],'PHYSICAL_PENDING')
                self.assertEqual(state['cells'][2]['status'],'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS')
                nf.cycle({},plan,{},[],{},state,output,None,root,lambda:None)
            self.assertEqual(executed,[1,2]);self.assertEqual(state['status'],'COMPLETE')
            self.assertFalse(any('ORIGINAL_NOT_RUN' in r['status'] for r in state['cells']))

    def test_producer_completion_with_unresolved_dispatched_slot_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'completion.json').write_text('{}')
            state={'status':'RUNNING','cells':[{'initial_state_id':'fixture','trial_id':1,'status':'NOT_RUN'}]}
            with patch.object(nf.span,'scan_returned'),patch.object(nf.span,'raw_matrix',return_value={('fixture',1):{'status':'DISPATCHED'}}):
                with self.assertRaisesRegex(ValueError,'unresolved'):nf.finish_cycle({}, {'output_root':str(root)},{},[],{},state,root,None,root)
            self.assertEqual(state['cells'][0]['status'],'NOT_RUN')

    def test_unknown_from_physics_never_scans_or_derives_a_final_dataset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'status':'RUNNING','cells':[]}
            def unknown(*args,**kwargs):state['status']='PAUSED_UNKNOWN'
            with patch.object(nf.span,'scan_returned') as scan,patch.object(nf.physical,'physical_pass',side_effect=unknown),patch.object(nf,'derive_nf') as derive:
                nf.cycle({}, {'output_root':str(root)},{},[],{},state,root,None,root,lambda:None)
                self.assertEqual(scan.call_count,1);derive.assert_not_called()


if __name__=='__main__':unittest.main()
