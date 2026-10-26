"""CPU/filesystem fixtures for the new FVF point; zero real tool dispatch."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import fvf_supplement_point as fvf


def saved(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


class FVFPointTests(unittest.TestCase):
    def fixture(self,directory):
        p=Path(directory);initial=p/'initial';candidate=p/'candidate'
        original={'generator.py':'# original wrapper\n','component_build.py':'# full caller\n',fvf.EDITABLE:'x=1\n','lib.py':'# readonly library\n'}
        for name,text in original.items():
            for folder in [initial,candidate]:
                path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        reference=p/'reference.spice';reference.write_text('* software fixture only\n')
        rows=[{'configuration_id':'p%02d'%i,'role':'anchor' if i==0 else ('development' if i<9 else 'hidden'),
            'parameters':{'fixture_parameter':i},'reference_file':str(reference),
            'contract':{'task_id':'fixture_qualified','specifications':[{'fixture_only':True}]}} for i in range(25)]
        qualified=p/'qualified';saved(qualified/'private/task.json',{'configurations':rows})
        points=copy.deepcopy(rows)
        for point in points:point['contract'].update(task_id=fvf.TASK,objective=copy.deepcopy(fvf.AREA))
        task={'task_id':fvf.TASK,'target':'fvf','editable_paths':[fvf.EDITABLE],'entrypoint':'generator.py','representation':'G2',
            'formal_dispatch_allowed':False,'source_files':sorted(original),'source_pack_base':str(initial),
            'source_overrides':{},'frozen_source_overrides':{},'qualified_domain_origin':str(qualified),'configurations':points,'top_cell':'fvf7'}
        taskfile=p/'task.json';saved(taskfile,task)
        trusted=p/'original_trusted';trusted.mkdir()
        saved(trusted/'meta.json',{'bench_kind':'vendor_ota','circuit':'fvf','top_cell':'fvf7'})
        (trusted/'contract.json').write_text('{}\n');(trusted/'reference.spice').write_text('old reference fixture\n')
        for path in trusted.iterdir():path.chmod(0o444)
        control={'source_files':sorted(original),'source_sha256':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in original.items()},
            'trusted':str(trusted),'trusted_files':sorted(p.name for p in trusted.iterdir())}
        return taskfile,task,control,candidate

    def test_complete_module_can_change_but_frozen_wrapper_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            taskfile,task,control,candidate=self.fixture(directory)
            (candidate/fvf.EDITABLE).write_text('x=2\n')
            actual=fvf.verify_source(task,control,candidate)
            self.assertEqual(actual[fvf.EDITABLE],b'x=2\n')
            (candidate/'component_build.py').write_text('# changed caller\n')
            with self.assertRaisesRegex(ValueError,'Frozen source'):fvf.verify_source(task,control,candidate)

    def test_declared_symlink_is_not_read_as_candidate_source(self):
        with tempfile.TemporaryDirectory() as directory:
            taskfile,task,control,candidate=self.fixture(directory)
            path=candidate/fvf.EDITABLE;path.unlink();path.symlink_to(Path(directory)/'reference.spice')
            with self.assertRaisesRegex(ValueError,'ordinary files'):fvf.verify_source(task,control,candidate)

    def test_point_cannot_change_reference_sizing_roles_bench_or_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            taskfile,task,control,candidate=self.fixture(directory)
            self.assertEqual(fvf.selected_point(task,'p00')['configuration_id'],'p00')
            changed=copy.deepcopy(task);changed['configurations'][17]['contract']['specifications']=[]
            with self.assertRaisesRegex(ValueError,'Independent N'):fvf.selected_point(changed,'p00')

    def test_readonly_template_is_copied_with_new_exact_point_N_without_EDA(self):
        with tempfile.TemporaryDirectory() as directory:
            taskfile,task,control,candidate=self.fixture(directory);out=Path(directory)/'output'
            before=(Path(control['trusted'])/'reference.spice').read_bytes()
            with patch.object(fvf,'binding',return_value=control),patch('src.candidate_executor.CandidateExecutor.execute') as execute:
                _,point,source,trusted,files,_=fvf.prepare_inputs(taskfile,'p01',out,candidate)
            execute.assert_not_called()
            self.assertEqual((trusted/'reference.spice').read_bytes(),Path(point['reference_file']).read_bytes())
            self.assertEqual(json.loads((trusted/'contract.json').read_text()),point['contract'])
            self.assertEqual((Path(control['trusted'])/'reference.spice').read_bytes(),before)
            self.assertEqual(files,control['trusted_files'])
            self.assertNotIn('E1_binding',task)

    def test_failed_stage_cost_keeps_real_CPU_and_missing_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);saved(run/'manifest.json',{'candidate':{'wall_seconds':5,'returncode':1}})
            costs=fvf.stage_costs(run)
            self.assertEqual(costs['candidate']['wall_seconds'],5);self.assertIsNone(costs['candidate']['waited_child_CPU_seconds'])
            saved(run/'candidate_stage/resource_usage.json',{'child_user_cpu_seconds':2.,'child_system_cpu_seconds':.2})
            self.assertEqual(fvf.stage_costs(run)['candidate']['waited_child_CPU_seconds'],2.2)

    def test_backend_budget_exhaustion_remains_budget_not_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);out=p/'output';out.mkdir();run=out/'physical/fixture';saved(run/'manifest.json',{'status':'BUDGET_EXHAUSTED'})
            task={'task_id':fvf.TASK,'source_files':[],'entrypoint':'generator.py','parent_lineage':'fixture'}
            point={'parameters':{},'reference_id':'fixture'}
            prepared=(task,point,p,p,[],{})
            with patch.object(fvf,'ROOT',fvf.SERVER),patch.object(fvf,'prepare_inputs',return_value=prepared),patch('scripts.qualify_telescopic_supplement.resource_gate'),patch('src.candidate_executor.CandidateExecutor.execute',return_value={'run_directory':str(run)}),patch('src.domain_runner.inspect_point') as inspect,patch('scripts.e1_matched_runner.visible_feedback',return_value={}):
                row=fvf.evaluate(p/'task.json','fixture',out)
            inspect.assert_not_called()
            self.assertEqual(row['checked']['execution_integrity'],'budget_exhausted')
            self.assertEqual(row['checked']['failure_class'],'budget');self.assertIsNone(row['objective'])


if __name__=='__main__':unittest.main()
