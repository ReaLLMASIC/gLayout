"""Software fixtures for prospective materialization; no EDA measurements."""
import copy
import difflib
import json
from pathlib import Path
import tarfile
import tempfile
import stat
import unittest
from unittest.mock import patch

from scripts.e2_four_source import controls_map,digest,matrix,prepare,raw_run,reserve,save,verify,writable_sampler_target
from scripts.e2_telescopic_stage_smoke import audit_smoke


class FourSourceTests(unittest.TestCase):
    def test_materializer_excludes_legacy_keeps_full_order_and_fixed_online_six(self):
        plan=json.loads(Path('configs/experiments/e2_four_source_prospective_v3.json').read_text())
        old={'pools':[],'candidate_pool_size':64,'maximum_generation_attempts_per_pool':256,
            'heuristics':{'full_budget':16}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for family in ['five_t','compact_miller','fvf','legacy_miller']:
                directory=root/family;directory.mkdir();pack=directory/'source';pack.mkdir()
                (pack/'src').mkdir();(pack/'src/__init__.py').write_text('')
                (pack/'generator.py').write_text('# software fixture\n')
                target='src/fixture_'+family+'.py';(pack/target).write_text('x=0\n')
                stream=[];patches=directory/'patches';patches.mkdir()
                for i in range(256):
                    patch=patches/f'{i:03d}.patch'
                    patch.write_text(''.join(difflib.unified_diff(['x=0\n'],[f'x={i}\n'],fromfile=target,tofile=target)))
                    control=plan['candidate_streams'].get(family,plan['candidate_streams']['five_t'])[i]
                    stream.append({**control,'patch':str(patch)})
                for sid in ['s0','s1','s2']:
                    sized=directory/sid;sized.mkdir();reference=sized/'reference.spice';reference.write_text('* fixture independent gold\n')
                    p={'configuration_id':family+'_'+sid,'parameters':{'width':1},'reference_file':str(reference),
                        'contract':{'fixture':'original contract bytes retained'}}
                    save(sized/'point.json',p);trusted=sized/'trusted';trusted.mkdir();save(trusted/'contract.json',p['contract'])
                    (trusted/'original_bench.py').write_text('# original fixture bench\n')
                    old['pools'].append({'pool_id':family+'_'+sid,'source_family':family,'sizing_id':sid,
                        'point':str(sized/'point.json'),'source_dir':str(pack),'source_paths':['generator.py','src/__init__.py',target],
                        'layout_target':target,'source_snapshot':str(pack/target),'full_trusted':str(trusted),
                        'top_cell':family,'candidate_stream':stream,'development_mask_paths':[],
                        'online_selected':family!='legacy_miller' and sid!='s1'})
            save(root/'old.json',old);save(root/'plan.json',plan);save(root/'controls.json',{'controls':[]})
            before=(root/'five_t/source/src/fixture_five_t.py').read_bytes()
            result=prepare(root/'old.json',root/'plan.json',root/'controls.json',root/'prepared')
            self.assertEqual(result['oracle_full_attempts_max'],768)
            self.assertEqual(result['all_methods_full_attempts_max'],1152)
            self.assertEqual(result['new_EDA_calls'],0)
            actual=json.loads((root/'prepared/execution_manifest.json').read_text())
            self.assertFalse(any(p['source_family']=='legacy_miller' for p in actual['pools']))
            self.assertEqual(len(actual['pools']),12)
            for pool in actual['pools'][:9]:
                prior=next(p for p in old['pools'] if p['pool_id']==pool['pool_id'])
                self.assertEqual(json.loads(Path(pool['point']).read_text())['contract'],json.loads(Path(prior['point']).read_text())['contract'])
            self.assertEqual((root/'five_t/source/src/fixture_five_t.py').read_bytes(),before)
            bad=copy.deepcopy(actual);bad['pools'][-1]['online_selected']=True
            with self.assertRaisesRegex(ValueError,'six online'):matrix(bad)

    def test_missing_actual_control_and_prepared_smoke_cannot_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save(root/'controls.json',{'controls':[{'pool_id':'telescopic_s1'}]})
            with self.assertRaisesRegex(ValueError,'twelve actual'):controls_map(root/'controls.json')
            save(root/'smoke.json',{'status':'PREPARED','passed':True})
            with self.assertRaisesRegex(ValueError,'real complete'):audit_smoke(root/'smoke.json',{})

    def test_verify_blocks_post_freeze_source_drift(self):
        plan=json.loads(Path('configs/experiments/e2_four_source_prospective_v3.json').read_text())
        pools=[{**p,'candidate_stream':plan['candidate_streams'][p['source_family']]} for p in plan['prospective_pools']]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'source.py';target.write_text('original source')
            manifest={'status':'FROZEN','formal_execution_allowed':True,'pools':pools,'candidate_pool_size':64,
                'maximum_generation_attempts_per_pool':256,'heuristics':{'full_budget':16},'implementation_sha256':{},
                'immutable_input_sha256':{str(target):digest(target)}}
            verify(manifest);target.write_text('changed source')
            with self.assertRaisesRegex(ValueError,'source/bench/input drift'):verify(manifest)

    def test_archived_raw_inspection_keeps_original_readonly_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'gold.spice').write_text('independent fixture N\n')
            source.chmod(0o555)
            with tarfile.open(root/'terminal_raw.tar.gz','w:gz') as saved:saved.add(source,arcname='source')
            save(root/'raw_archive.json',{'byte_exact_all_members_verified':True})
            source.chmod(0o755);(source/'gold.spice').unlink();source.rmdir()
            with raw_run(root) as actual:self.assertEqual((actual/'source/gold.spice').read_text(),'independent fixture N\n')
            self.assertFalse(source.exists());self.assertTrue((root/'terminal_raw.tar.gz').exists())

    def test_formal_identity_cannot_be_retried_under_another_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.e2_four_source.ROOT',Path(tmp)):
            first,record=reserve({'freeze_id':'software_fixture'},{'pool_id':'telescopic_s1'},'full_oracle',Path(tmp)/'first')
            self.assertEqual(json.loads(first.read_text())['status'],'RESERVED_NO_AUTOMATIC_RETRY')
            with self.assertRaises(FileExistsError):
                reserve({'freeze_id':'software_fixture'},{'pool_id':'telescopic_s1'},'full_oracle',Path(tmp)/'other')

    def test_frozen_readonly_source_can_be_patched_only_in_disposable_sampler(self):
        from scripts.e2_execution import Pool
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'protected_source';target=source/'nested/generator.py'
            target.parent.mkdir(parents=True);target.write_text('x=0\n');target.chmod(0o444)
            target.parent.chmod(0o555);source.chmod(0o555)
            save(root/'point.json',{'parameters':{}})
            pool={'pool_id':'software_fixture','point':str(root/'point.json'),'source_dir':str(source),'layout_target':'nested/generator.py'}
            instance=Pool({'heuristics':{'full_budget':16}},pool,root/'actual_Pool_constructor','full_oracle',False)
            writable_sampler_target(instance)
            (instance.source/'nested/generator.py').write_text('x=1\n')
            self.assertEqual(target.read_text(),'x=0\n')
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o444)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode),0o555)
            target.parent.chmod(0o755);source.chmod(0o755)


if __name__=='__main__':unittest.main()
