"""Software fixtures only: no container, SPICE, model or formal result."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import qualify_telescopic_supplement_v2 as v2


def saved(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))


def success_record():
    return {'checked':{'S2':True,'execution_integrity':'valid'}, 'Store_development_check':{'S2':True},
        'full_RC_device_port_audit':{'status':'RC_DEVICE_GRAPH_MATCH'}, 'actual_SPICE_calls':12,
        'actual_SPICE_returncode0':12, 'actual_SPICE_error_count':0}


class TelescopicV2Tests(unittest.TestCase):
    def fixture(self, directory):
        run=Path(directory)/'raw';e=run/'evidence';out=Path(directory)/'audit';out.mkdir()
        names=['VDD','GND','IBIAS','VBN','VBP','VP','VN','VOUT']
        order=['VOUT','IBIAS','VBN','VBP','VDD','GND','VP','VN']
        contract={'id':'software_fixture_not_measurement','required_corners':['tt','ss','ff']}
        pex={'netlist':'actual_pex.spice','top_cell':'tel_rc','ports':order}
        saved(e/'validation.json',{'contract':contract,'artifacts':{'pex':pex}})
        text='.subckt tel_rc '+' '.join(order)+'\nRwire VOUT inner 1\nX1 inner VP GND GND sky130_fd_pr__nfet_01v8 w=1 l=1\n.ends tel_rc\n'
        (e/'actual_pex.spice').write_text(text)
        reference='.subckt independent '+' '.join(names)+'\nX1 VOUT VP GND GND sky130_fd_pr__nfet_01v8 w=1 l=1\n.ends independent\n'
        ref=Path(directory)/'independent.spice';ref.write_text(reference)
        (run/'trusted').mkdir();(run/'trusted/reference.spice').write_text(reference)
        for corner in contract['required_corners']:
            for analysis in ['op','ac','transient','dc']:
                binding=dict(v2.NODES)
                if analysis in ['transient','dc']:binding['VN']='out'
                p=e/'post_rc_measurements'/corner/(analysis+'.spice');p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('.include /evidence/actual_pex.spice\nXDUT '+' '.join(binding[n] for n in order)+' tel_rc\n')
        return run,out,{'ports':names,'top_cell':'tel'}, {'contract':contract,'reference_file':str(ref)},pex

    @unittest.skipUnless(importlib.util.find_spec('networkx'), 'networkx is mandatory in the actual private EDA runtime')
    def test_reference_permutation_with_true_deck_mapping_and_graph_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            run,out,task,point,pex=self.fixture(directory)
            before=(run/'evidence/actual_pex.spice').read_bytes()
            audit=v2.full_rc_audit(run,task,point,out)
            self.assertEqual(audit['status'],'RC_DEVICE_GRAPH_MATCH')
            self.assertEqual(len(audit['actual_decks_checked']),12)
            self.assertTrue(audit['original_PEX_bytes_unchanged'])
            self.assertEqual((run/'evidence/actual_pex.spice').read_bytes(),before)

    def test_actual_terminal_swap_is_not_a_permitted_header_permutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run,out,task,point,pex=self.fixture(directory)
            p=run/'evidence/post_rc_measurements/tt/ac.spice';p.write_text(p.read_text().replace('out bias','bias out'))
            audit=v2.full_rc_audit(run,task,point,out)
            self.assertEqual(audit['status'],'QUARANTINED_UNKNOWN')
            self.assertIn('XDUT',audit['error'])

    def test_different_or_missing_original_rc_include_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            run,out,task,point,pex=self.fixture(directory)
            p=run/'evidence/post_rc_measurements/ff/dc.spice';p.write_text(p.read_text().replace('actual_pex','simplified'))
            self.assertEqual(v2.full_rc_audit(run,task,point,out)['status'],'QUARANTINED_UNKNOWN')

    def test_duplicate_named_port_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run,out,task,point,pex=self.fixture(directory)
            path=run/'evidence/validation.json';data=json.loads(path.read_text());data['artifacts']['pex']['ports'][-1]='VOUT';saved(path,data)
            self.assertIn('named ports',v2.full_rc_audit(run,task,point,out)['error'])

    def test_carry_is_exactly_first_only_prior_call_and_same25order(self):
        rows=[{'configuration_id':'z%02d'%i} for i in range(25)]
        prior={'phase':'full','status':'UNKNOWN_STOPPED','points':{'z00':{'actual_point_calls':1}}}
        first,remaining=v2.fixed_continuation({'configurations':rows},prior)
        self.assertEqual(first,rows[0]);self.assertEqual(remaining,rows[1:])
        prior['points']['z01']={'actual_point_calls':1}
        with self.assertRaisesRegex(ValueError,'first and only'):v2.fixed_continuation({'configurations':rows},prior)

    def test_carry_requires_current_store_and_complete_real_processes(self):
        record=success_record();v2.verify_carry(record)
        for key in ['Store_development_check','actual_SPICE_calls']:
            broken=copy.deepcopy(record);broken[key]=None
            with self.assertRaises(ValueError):v2.verify_carry(broken)

    def test_failure_finally_preserves_cost_and_actual_twelve_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory);raw=output/'physical/software_fixture';
            def failed(*args,**kwargs):
                saved(raw/'manifest.json',{'candidate':{'wall_seconds':2,'returncode':0},'trusted':{'wall_seconds':3,'returncode':1}})
                for name in ['candidate','trusted']:saved(raw/(name+'_stage/resource_usage.json'),{'child_user_cpu_seconds':1.,'child_system_cpu_seconds':.25})
                saved(raw/'evidence/post_rc_measurements/actual_processes.json',[{'returncode':0,'error':None} for i in range(12)])
                raise RuntimeError('software fixture transport return failed after real ledger creation')
            point={'configuration_id':'z01','parameters':{},'trusted_dir':'unused','trusted_files':[], 'reference_id':'fixture','pdk_revision':'fixture'}
            task={'source_pack':str(output),'source_files':[],'entrypoint':'fixture.py','task_id':'fixture','parent_lineage':'fixture'}
            with patch('src.candidate_executor.CandidateExecutor.execute',side_effect=failed):record=v2.full_point(task,point,output,9999999999)
            self.assertEqual(record['actual_SPICE_calls'],12)
            self.assertEqual(record['actual_costs_by_stage']['trusted']['waited_child_CPU_seconds'],1.25)
            self.assertEqual(record['checked']['execution_integrity'],'incomplete')
            self.assertTrue((output/'point.json').is_file())

    def test_pause_stops_before_any_fresh_candidate_or_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);pause=folder/'PAUSE_REQUESTED';pause.touch()
            rows=[{'configuration_id':'z%02d'%i} for i in range(25)]
            carry={**success_record(),'origin_run_id':'software_fixture','raw_directory':'/fixture/raw',
                'actual_costs_by_stage':{},'readback_wall_seconds':.1,'readback_parent_CPU_seconds':.05}
            m={'carry_run_directory':'/fixture/raw','carry_origin_run_id':'software_fixture'}
            with patch.object(v2,'ROOT',v2.SERVER),patch.object(v2,'OUTPUT',folder/'output'),patch.object(v2,'PAUSE',pause),patch.object(v2,'verify_preparation',return_value=(m,{'configurations':rows},rows[0],rows[1:])),patch.object(v2,'inspect_existing',return_value=carry),patch.object(v2,'resource_gate') as gate,patch.object(v2,'full_point') as full:
                result=v2.run()
            gate.assert_not_called();full.assert_not_called()
            self.assertEqual(result['status'],'PAUSE_REQUESTED');self.assertEqual(result['new_physical_calls'],0)
            self.assertEqual(result['carried_configurations'],1);self.assertEqual(result['not_run'],24)


if __name__=='__main__':unittest.main()
