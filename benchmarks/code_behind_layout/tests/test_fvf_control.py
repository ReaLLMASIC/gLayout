"""No EDA: exact actual-bench port ordering and missing-RC quarantine."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts.qualify_fvf_supplement import verify_deck,full_rc_audit


class FVFControlTests(unittest.TestCase):
    def test_actual_pex_order_bound_to_xdut(self):
        ports=['AVDD','AVSS','NB_10U','NBC_10U','VOUT','INM','INP']
        deck='.include /evidence/post_rc_measurements/fvf7_pex.spice\nXDUT vdd 0 bias2 bias1 out vn vp fvf7_rc\n'
        verify_deck(deck,ports,'fvf7_rc')
        with self.assertRaisesRegex(ValueError,'XDUT order'):
            verify_deck(deck.replace('bias2 bias1','bias1 bias2'),ports,'fvf7_rc')

    def test_deck_cannot_consume_simplified_other_file(self):
        with self.assertRaisesRegex(ValueError,'unsimplified'):
            verify_deck('.include /evidence/other.spice\nXDUT vp fvf7_rc\n',['INP'],'fvf7_rc')

    def test_missing_full_rc_is_quarantined_not_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'evidence').mkdir()
            contract={'id':'engineering_fixture_only'}
            (root/'evidence/validation.json').write_text(json.dumps({'contract':contract,'artifacts':{'pex':{
                'netlist':'missing.spice','top_cell':'fvf7_rc','ports':['AVDD','AVSS','NB_10U','NBC_10U','VOUT','INM','INP']}}}))
            audit=full_rc_audit(root,{'contract':contract},root)
            self.assertEqual(audit['status'],'QUARANTINED_UNKNOWN')
            self.assertIn('FileNotFoundError',audit['error'])
            self.assertFalse(audit['original_RC_changed'])
            self.assertTrue((root/'full_rc_intent_audit.json').is_file())


if __name__=='__main__':unittest.main()
