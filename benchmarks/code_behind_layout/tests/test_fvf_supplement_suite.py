"""Finite dispatcher CPU fixtures; no SSH, model or EDA execution."""
from argparse import Namespace
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from scripts import run_fvf_supplement_suite as s


def manifest():
    return {'cohort_id':s.policy.COHORT,'status':s.policy.FROZEN,'formal_dispatch':True,
        'budget':copy.deepcopy(s.policy.BUDGET),'search_plan':s.policy.matrix(),
        'manifest_path':'/private_execution_endpoint/fixture/manifest.json','implementation_sha256':{'fixture_only':'unused'},
        'freeze_id':'explicit_software_fixture','source_revision':'a'*40}


def saved(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


class FVFSuiteTests(unittest.TestCase):
    def test_exact20_matrix_and_only_two_workers(self):
        m=manifest();rows=s.plan(m,2)
        self.assertEqual(len(rows),20);self.assertEqual({r['task_id'] for r in rows},{s.policy.TASK})
        self.assertEqual([(r['method'],r['trial_id']) for r in rows[:4]],[('A','1'),('R','1'),('B','1'),('C','1')])
        with self.assertRaises(ValueError):s.plan(m,3)
        m['search_plan'][0]['selection_seed']=999
        with self.assertRaises(ValueError):s.plan(m,2)

    def test_check_only_has_zero_remote_process_or_reservations(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json';saved(p,manifest());args=Namespace(manifest=p,workers=2,output=Path(d)/'not_created')
            with patch.object(s.policy.main,'verify'),patch.object(s,'resources') as resources,patch.object(s.subprocess,'Popen') as popen:
                r=s.check_only(args)
            self.assertEqual(r['physical_or_model_calls'],0);self.assertEqual(r['remote_calls'],0)
            self.assertFalse(args.output.exists());resources.assert_not_called();popen.assert_not_called()

    def test_DRAFT_cannot_dispatch_or_reserve(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json';m=manifest();m.update(status=s.policy.DRAFT,formal_dispatch=False);saved(p,m)
            args=Namespace(manifest=p,workers=2,output=Path(d)/'not_created')
            with patch.object(s.subprocess,'Popen') as popen:
                with self.assertRaisesRegex(ValueError,'DRAFT'):s.run(args)
            popen.assert_not_called();self.assertFalse(args.output.exists())

    def test_durable_unique_reservation_precedes_process_start(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);m=manifest();job=s.plan(m,2)[0];persist=Mock()
            folder=s.reserve(job,0,out,m,{},persist,{'fixture_only':True})
            self.assertEqual(job['status'],'RESERVED');persist.assert_called_once()
            self.assertEqual(s.read(folder/'reservation.json')['argv'],job['argv'])
            self.assertIn('--formal',job['argv']);self.assertNotIn('--post-freeze',job['argv'])
            self.assertIsNone(s.reserve(job,0,out,m,{},persist,{}))
            self.assertTrue(job['status'].startswith('UNRESOLVED'))

    def fixture_job(self,path):
        m=manifest();job=s.plan(m,2)[0];job['dispatch_record']=str(path/'dispatch.json')
        client={'task_id':job['task_id'],'method':job['method'],'trial_id':job['trial_id'],
            'cohort_id':s.policy.COHORT,'formal':True,'episode_directory':'/fixture/private_episode',
            'local_output_directory':str(path/'client')}
        saved(Path(job['dispatch_record']),client)
        report={'task_id':job['task_id'],'method':job['method'],'trial_id':job['trial_id'],
            'cohort_id':s.policy.COHORT,'status':'INCOMPLETE_UNKNOWN'}
        return m,job,client,report

    def test_stdout_or_absent_report_is_not_completion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m,job,client,report=self.fixture_job(p)
            with patch.object(s,'backend_proof') as proof:
                with self.assertRaisesRegex(ValueError,'No real local'):s.collect(job,m)
            proof.assert_not_called();self.assertEqual(job['status'],'NOT_RUN')

    def test_actual_sealed_unknown_retained_without_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m,job,client,report=self.fixture_job(p);saved(Path(client['local_output_directory'])/'search.json',report)
            with patch.object(s,'backend_proof',return_value={'sealed':True,'search_status':'INCOMPLETE_UNKNOWN'}):s.collect(job,m)
            self.assertEqual(job['status'],'RECORDED');self.assertEqual(job['search_status'],'INCOMPLETE_UNKNOWN')
            self.assertNotIn('S2',job)

    def test_unsealed_backend_or_wrong_client_cannot_record(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);m,job,client,report=self.fixture_job(p);saved(Path(client['local_output_directory'])/'search.json',report)
            with patch.object(s,'backend_proof',return_value={'sealed':False}):
                with self.assertRaisesRegex(ValueError,'unsealed'):s.collect(job,m)
            client['formal']=False;saved(Path(job['dispatch_record']),client)
            with self.assertRaisesRegex(ValueError,'Client identity'):s.collect(job,m)

    def test_plan_identity_binds_dispatcher_and_actual_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.json';m=manifest();saved(p,m);a=s.identity(p,m)
            m['source_revision']='b'*40;saved(p,m);b=s.identity(p,m)
            self.assertNotEqual(a,b);self.assertIn('coordinator_sha256',a)


if __name__=='__main__':unittest.main()
