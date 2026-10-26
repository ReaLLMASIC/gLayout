import unittest
from src.device_intent import compare_device_intent


class DeviceIntentTests(unittest.TestCase):
    def netlist(self,devices):return '.subckt test D G S B\n'+devices+'\n.ends test\n'

    def test_parallel_per_finger_expansion_passes_but_aggregated_width_does_not(self):
        gold=self.netlist('Xref D G S B sky130_fd_pr__nfet_01v8 w=3 l=.6 m=2')
        actual=self.netlist('X0 D G S B sky130_fd_pr__nfet_01v8 w=3 l=.6\nX1 S G D B sky130_fd_pr__nfet_01v8 w=3 l=.6')
        self.assertTrue(compare_device_intent(actual,gold)['is_clean'])
        wide=self.netlist('Xwide D G S B sky130_fd_pr__nfet_01v8 w=6 l=.6')
        report=compare_device_intent(wide,gold)
        self.assertFalse(report['is_clean']);self.assertTrue(report['missing']);self.assertTrue(report['extra'])

    def test_preserves_model_length_nf_and_mim_size(self):
        gold=self.netlist('X0 D G S B sky130_fd_pr__nfet_01v8 w=3 l=.6\nXC D G sky130_fd_pr__cap_mim_m3_1 w=30 l=30')
        for before,after in [('w=30','w=31'),('l=.6','l=.605'),('nfet_01v8','nfet_01v8_lvt'),('w=3 l=.6','w=3 l=.6 nf=2')]:
            self.assertFalse(compare_device_intent(gold.replace(before,after),gold)['is_clean'])

    def test_rejects_unelaborated_reference_and_parameter_expressions(self):
        gold=self.netlist('X0 D G S B sky130_fd_pr__nfet_01v8 w=3 l=.6')
        for changed in [gold.replace('w=3','w={width}'),self.netlist('Xchild D G S B hierarchy')]:
            with self.assertRaises(ValueError):compare_device_intent(changed,gold)

    def test_per_finger_sizes_must_stay_on_the_correct_branch(self):
        def branch(node,widths):
            return '\n'.join('X'+node+str(i)+' '+node+' G S B sky130_fd_pr__nfet_01v8 w='+str(w)+' l=.6'
                             for i,w in enumerate(widths))
        gold='.subckt test A C G S B\n'+branch('A',[1,3])+'\n'+branch('C',[2,2])+'\n.ends test\n'
        changed='.subckt test A C G S B\n'+branch('A',[2,2])+'\n'+branch('C',[1,3])+'\n.ends test\n'
        report=compare_device_intent(changed,gold)
        self.assertTrue(report['per_device_dimensions_match'])
        self.assertFalse(report['device_terminal_graph_match'])
        self.assertFalse(report['is_clean'])

    def test_internal_renaming_is_valid_but_terminal_roles_are_fixed(self):
        gold=self.netlist('X0 D G internal B sky130_fd_pr__nfet_01v8 w=3 l=.6\n'
                          'X1 internal G S B sky130_fd_pr__nfet_01v8 w=3 l=.6\n'
                          'XC D internal sky130_fd_pr__cap_mim_m3_1 w=5 l=5')
        self.assertTrue(compare_device_intent(gold.replace('internal','n_772'),gold)['is_clean'])
        for changed in [gold.replace('X0 D G internal B','X0 D B internal G'),
                        gold.replace('XC D internal','XC internal D')]:
            self.assertFalse(compare_device_intent(changed,gold)['is_clean'])

    def test_identical_dummy_parallel_counts_are_preserved_without_symmetry_search(self):
        gold=self.netlist('X0 B B B B sky130_fd_pr__nfet_01v8 w=4.15 l=1 m=70\n'
                          'X1 D G S B sky130_fd_pr__nfet_01v8 w=2 l=.6 m=4')
        actual=self.netlist('\n'.join('Xd'+str(i)+' B B B B sky130_fd_pr__nfet_01v8 w=4.15 l=1' for i in range(70))+'\n'
                            'XM D G S B sky130_fd_pr__nfet_01v8 w=2 l=.6 m=4')
        self.assertTrue(compare_device_intent(actual,gold)['is_clean'])
        self.assertFalse(compare_device_intent(actual.replace('Xd69','*Xd69'),gold)['is_clean'])


if __name__=='__main__':unittest.main()
