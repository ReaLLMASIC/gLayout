import copy
import sys
import unittest
from pathlib import Path

from scripts import run_e1_scope_continuation as continuation


def fixture():
    jobs = [{'task_id': 'task_%03d' % i, 'method': 'G0', 'trial_id': '1', 'status': 'NOT_RUN'} for i in range(360)]
    for i, ident in continuation.ACKS.items():
        jobs[i].update(zip(('task_id', 'method', 'trial_id'), ident))
    expected = copy.deepcopy(jobs)
    for job in jobs[:34]:
        job.update(status='RECORDED', post_freeze_status='COMPLETE', requires_pause=False)
    jobs[14].update(post_freeze_status='INCOMPLETE_UNKNOWN', requires_pause=True)
    return jobs, expected


def report_fixture(jobs):
    reports = [{**{k:j[k] for k in ('task_id', 'method', 'trial_id', 'post_freeze_status')},
        'sealed': True, 'freeze_id': 'frozen', 'cohort_id': 'scope_v2_16k',
        'status': 'SEARCH_FINISHED', 'analysis_search_status': 'COMPLETED'} for j in jobs[:34]]
    reports[28].update(status='INCOMPLETE_UNKNOWN', analysis_search_status='INFRASTRUCTURE_PAUSED')
    return reports


class ContinuationTests(unittest.TestCase):
    def test_old_fourteen_retains_pause_flag_under_fixed_two_unknown_ack(self):
        jobs, expected = fixture()
        before = copy.deepcopy(jobs)
        continuation.validate_base_jobs(jobs, expected)
        self.assertFalse(continuation.needs_pause(jobs))
        self.assertEqual(jobs, before)
        self.assertTrue(jobs[14]['requires_pause'])
        self.assertEqual(jobs[14]['post_freeze_status'], 'INCOMPLETE_UNKNOWN')

    def test_any_new_unknown_pauses_including_after_original_acknowledgement(self):
        jobs, _ = fixture()
        jobs[34].update(status='RECORDED', post_freeze_status='INCOMPLETE_UNKNOWN', requires_pause=True)
        self.assertTrue(continuation.needs_pause(jobs))
        jobs[34].update(status='UNRESOLVED_RETURN', requires_pause=False)
        self.assertTrue(continuation.needs_pause(jobs))

    def test_new_search_unknown_still_pauses_if_later_diagnostics_complete(self):
        jobs, _ = fixture()
        jobs[34].update(status='RECORDED', post_freeze_status='COMPLETE', requires_pause=False)
        continuation.retain_new_unknown(jobs[34], {'status': 'INCOMPLETE_UNKNOWN',
            'analysis_search_status': 'INFRASTRUCTURE_PAUSED', 'post_freeze_status': 'COMPLETE'})
        self.assertTrue(continuation.needs_pause(jobs))

    def test_exact_two_old_actual_report_unknowns_and_no_extra_ack(self):
        jobs, _ = fixture()
        reports = report_fixture(jobs)
        manifest = {'freeze_id': 'frozen', 'cohort_id': 'scope_v2_16k'}
        continuation.validate_old_reports(jobs, reports, manifest)
        reports[29]['analysis_search_status'] = 'INFRASTRUCTURE_PAUSED'
        with self.assertRaises(ValueError):
            continuation.validate_old_reports(jobs, reports, manifest)
        reports = report_fixture(jobs)
        reports[28].update(status='SEARCH_FINISHED', analysis_search_status='COMPLETED')
        with self.assertRaises(ValueError):
            continuation.validate_old_reports(jobs, reports, manifest)

    def test_a_previously_dispatched_pending_identity_is_rejected(self):
        for field, value in [('status', 'RUNNING'), ('status', 'RECORDED'), ('pid', 42), ('dispatch_record', '/prior/client.json')]:
            jobs, expected = fixture()
            jobs[34][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                continuation.validate_base_jobs(jobs, expected)

    def test_duplicate_or_changed_original_order_is_rejected(self):
        jobs, expected = fixture()
        jobs[35].update({k:jobs[34][k] for k in ('task_id', 'method', 'trial_id')})
        with self.assertRaises(ValueError):
            continuation.validate_base_jobs(jobs, expected)
        jobs, expected = fixture()
        jobs[34], jobs[35] = jobs[35], jobs[34]
        with self.assertRaises(ValueError):
            continuation.validate_base_jobs(jobs, expected)

    def test_relabeling_old_unknown_or_adding_an_old_ack_is_rejected(self):
        jobs, expected = fixture()
        jobs[14].update(requires_pause=False, post_freeze_status='COMPLETE')
        with self.assertRaises(ValueError):
            continuation.validate_base_jobs(jobs, expected)
        jobs, expected = fixture()
        jobs[15].update(requires_pause=True, post_freeze_status='INCOMPLETE_UNKNOWN')
        with self.assertRaises(ValueError):
            continuation.validate_base_jobs(jobs, expected)

    def test_unchanged_backend_and_action_fields_are_used(self):
        jobs, _ = fixture()
        job = jobs[34]
        record = Path('/new/034/client.json')
        backend = '/original/frozen/manifest.json'
        self.assertEqual(continuation.job_command(job, backend, record), [sys.executable,
            str(continuation.ROOT/'scripts/e1_scope_runner.py'), '--manifest', backend,
            '--task', job['task_id'], '--method', job['method'], '--trial', job['trial_id'],
            '--formal', '--dispatch-record', str(record)])


if __name__ == '__main__':
    unittest.main()
