"""Literal software graphs used only to test the read-only RC contraction."""
import unittest
from scripts.audit_train_pair_nf_rc import contracted_devices
from src.device_intent import compare_device_intent


class NFRCIntentTests(unittest.TestCase):
    gold = '.subckt gold VDD VSS IN OUT\nXn OUT IN VSS VSS sky130_fd_pr__nfet_01v8 w=.5 l=.3\nXp OUT IN VDD VDD sky130_fd_pr__pfet_01v8 w=.5 l=.3\n.ends gold\n'
    rc = '.subckt rc VDD VSS IN OUT\nXn od ig vs vs sky130_fd_pr__nfet_01v8 w=.5 l=.3\nXp od ig vd vd sky130_fd_pr__pfet_01v8 w=.5 l=.3\nRvdd VDD vd 1\nRvss VSS vs 2\nRin IN ig 3\nRout OUT od 4\nCwire od vs 1f\n.ends rc\n'

    def test_both_mos_flavors_and_all_four_terminal_roles_survive_wire_contraction(self):
        view = contracted_devices(self.rc, 'rc', ['VDD', 'VSS', 'IN', 'OUT'])
        self.assertTrue(compare_device_intent(view, self.gold)['is_clean'])
        changed = self.rc.replace('Xp od ig vd vd', 'Xp od ig vd vs')
        self.assertFalse(compare_device_intent(contracted_devices(changed, 'rc', ['VDD', 'VSS', 'IN', 'OUT']), self.gold)['is_clean'])

    def test_missing_finger_or_different_mos_flavor_is_not_hidden_by_positive_rc(self):
        missing = '\n'.join(line for line in self.rc.splitlines() if not line.startswith('Xp '))
        self.assertFalse(compare_device_intent(contracted_devices(missing, 'rc', ['VDD', 'VSS', 'IN', 'OUT']), self.gold)['is_clean'])
        changed = self.rc.replace('sky130_fd_pr__pfet_01v8', 'sky130_fd_pr__nfet_01v8')
        self.assertFalse(compare_device_intent(contracted_devices(changed, 'rc', ['VDD', 'VSS', 'IN', 'OUT']), self.gold)['is_clean'])

    def test_port_permutation_and_wire_short_cannot_masquerade_as_original_bench(self):
        with self.assertRaisesRegex(ValueError, 'port order'):
            contracted_devices(self.rc.replace('VDD VSS IN OUT', 'VSS VDD IN OUT'), 'rc', ['VDD', 'VSS', 'IN', 'OUT'])
        with self.assertRaisesRegex(ValueError, 'distinct'):
            contracted_devices(self.rc.replace('Cwire', 'Rshort IN OUT 1\nCwire'), 'rc', ['VDD', 'VSS', 'IN', 'OUT'])


if __name__ == '__main__':
    unittest.main()
