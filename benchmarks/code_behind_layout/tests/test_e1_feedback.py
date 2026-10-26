from pathlib import Path
import tempfile
import unittest
from scripts.e1_matched_runner import visible_feedback


class DiagnosticFeedbackTests(unittest.TestCase):
    def test_actual_generation_error_is_visible_with_explicit_sample_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'candidate_stage').mkdir()
            (root/'candidate_stage/console.log').write_text('warning\n'*30+'Traceback (most recent call last):\n'+
                '  File "/source/generator.py", line 3\n'+('  more frame\n'*20)+'NameError: name missing_port is not defined\n')
            value=visible_feedback({'run_directory':str(root),'status':'CANDIDATE_FAILED'})['diagnostic_samples']['generation']
            self.assertIn('NameError: name missing_port',value['trace_tail'])
            self.assertLessEqual(len(value['trace_tail'].splitlines()),12)
            self.assertGreater(value['diagnostic_lines_omitted'],0)
            self.assertEqual(value['status'],'CANDIDATE_FAILED')

    def test_drc_coordinates_from_actual_report_and_omissions_remain_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'evidence/drc';folder.mkdir(parents=True)
            body='\n'.join('rule%d\n0.000um 1.000um 2.000um 3.000um\n4.000um 5.000um 6.000um 7.000um\n8.000um 9.000um 10.000um 11.000um'%i for i in range(5))
            (folder/'direct_drc.rpt').write_text('candidate count: 15\n----------------------------------------\n'+body+'\n')
            value=visible_feedback({'run_directory':str(root),'status':'EVALUATION_FAILED',
                'physical_result':{'observation':{'checks':{'drc':False}}}})['diagnostic_samples']['drc']
            self.assertEqual(value['error_count'],15);self.assertEqual(value['coordinate_boxes_total'],15)
            self.assertEqual(value['rule_groups_omitted'],1);self.assertEqual(value['coordinate_boxes_omitted'],7)
            self.assertEqual(value['samples'][0]['coordinate_boxes'][0],'0.000um 1.000um 2.000um 3.000um')

    def test_successful_point_does_not_gain_failure_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=visible_feedback({'run_directory':tmp,'status':'EVALUATED',
                'physical_result':{'observation':{'checks':{'drc':True,'lvs':True,'intent':True},'corners':{'tt':{'value':1}}}}})
            self.assertNotIn('diagnostic_samples',value);self.assertEqual(value['corners'],{'tt':{'value':1}})
