"""The exact known accounting repair does not invent labels or physical outcomes."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts import reconcile_completed_span16 as reconciliation
from scripts.reconcile_completed_span16 import reconciled_cell_status


class Span16ReconciliationTests(unittest.TestCase):
    def test_no_report_before_actual_terminal_record(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();physical=root/'runs/physical';physical.mkdir(parents=True);proposal=root/'runs/proposal';proposal.mkdir()
            with patch.object(reconciliation,'ROOT',root):
                with self.assertRaises(FileNotFoundError):reconciliation.final_report(physical,proposal)
            self.assertEqual(list(physical.iterdir()),[]);self.assertEqual(list(proposal.iterdir()),[])

    def test_returned_rejection_is_not_unrun(self):
        raw={'status':'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'}
        for old in ['NOT_RUN','ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED']:
            self.assertEqual(reconciled_cell_status(raw,{'status':old}),raw['status'])

    def test_does_not_reclassify_real_physical_or_unknown_results(self):
        for raw in ['COMPILED_STUDENT_FIT_PROPOSAL_ONLY','UNKNOWN_PRODUCER_PAUSE']:
            self.assertEqual(reconciled_cell_status({'status':raw},{'status':'QUARANTINED_UNKNOWN'}),'QUARANTINED_UNKNOWN')
        with self.assertRaises(ValueError):reconciled_cell_status({'status':'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'},
            {'status':'NOT_RUN','candidate_file':'actual_candidate.json'})


if __name__=='__main__':unittest.main()
