import unittest
from src.e1_packets import bind_reference,policy_packet,public_cells,public_sizings,PUBLIC_CONTRACT_FIELDS


class E1PacketsTest(unittest.TestCase):
    def test_reference_preserves_per_finger_width_and_parallel_count(self):
        graph=bind_reference('.subckt t D G S B\nX1 D G S B sky130_fd_pr__nfet_01v8 w=3 l=1 m=2\nX2 D G S B sky130_fd_pr__nfet_01v8 w=3 l=1\n.ends t\n','t','ref')
        self.assertEqual(graph['expanded_MOS_count'],3)
        self.assertEqual(graph['primitives'][0]['width_um'],3)
        self.assertEqual(graph['primitives'][0]['fingers'],3)
        self.assertFalse(graph['primitives'][0]['with_dummy'])

    def test_mim_pin_order_is_top_then_bottom(self):
        graph=bind_reference('.subckt t A B\nXCC A B sky130_fd_pr__cap_mim_m3_1 w=25 l=25\n.ends t\n','t','ref')
        self.assertEqual(graph['instances'][0]['nets'],{'P':'A','N':'B'})
        self.assertEqual(graph['primitives'][0]['model_pin_order'],['P_top_plate','N_bottom_plate'])

    def test_policy_packet_does_not_forward_trusted_manifest_fields(self):
        task={'task_id':'draft','stratum':'composition','target':'test','top_cell':'t',
            'anchor_contract':{'task_id':'draft','reference_id':'ref','configuration_id':'anchor','hidden_table':['SECRET']},
            'visible_configurations':[{'configuration_id':'anchor','parameters':{'width':3}}],
            'initial_patch':'ANSWER','oracle':'SECRET','ancestry':'PRIVATE','hidden_configurations':['HIDDEN']}
        graph=bind_reference('.subckt t A B C D\nX1 A B C D sky130_fd_pr__nfet_01v8 w=3 l=1\n.ends t\n','t','ref')
        packet=policy_packet(task,'G0',pdk={'rules':{}},anchor_graph=graph)
        text=repr(packet)
        for marker in ['SECRET','ANSWER','PRIVATE','HIDDEN']:self.assertNotIn(marker,text)
        self.assertEqual(packet['budget']['maximum_context_tokens'],8192)
        self.assertEqual(packet['budget']['maximum_output_tokens'],1024)
        self.assertIn('library.write_gds',packet['visible_sources']['generator.py'])

    def test_unbound_or_unsupported_reference_fails(self):
        with self.assertRaises(ValueError):bind_reference('.subckt other A B\n.ends other','t','ref')
        with self.assertRaises(ValueError):bind_reference('.subckt t A B\nX1 A B arbitrary w=1 l=1\n.ends t','t','ref')

    def test_full_terminal_metadata_roundtrip(self):
        angles={'N':90,'E':0,'S':270,'W':180}
        coordinates={'N':[.005,.1,.29,67],'E':[.2,0,.31,68],'S':[-.005,-.1,.29,67],'W':[-.2,0,.31,68]}
        rows=[[t,d,*coordinates[d][:3],angles[d],coordinates[d][3],20] for t in 'DGSB' for d in 'NESW']
        result=public_cells([{'primitive_id':'primitive_00','terminal_access':rows,'bbox_um':[[-1,-1],[1,1]]}])
        access=result['cells']['primitive_00']['terminal_pairs'];self.assertEqual(len(access),4)
        for pair in access:
            cx,cy,nx,ny,nw,nl,ex,ey,ew,el=pair
            restored=[[cx+nx,cy+ny,nw,nl],[cx+ex,cy+ey,ew,el],[cx-nx,cy-ny,nw,nl],[cx-ex,cy-ey,ew,el]]
            for original,values in zip(rows[:4],restored):
                self.assertEqual(values[:3],[round(x*1000,3) for x in original[2:5]])
                self.assertEqual(result['layers'][values[3]],tuple(original[6:8]))

    def test_sizing_table_retains_every_parameter(self):
        points=[{'configuration_id':str(i),'parameters':{'width':i+1,'length':1,'fingers':2}} for i in range(9)]
        result=public_sizings(points)
        for point in points:
            restored={**result['fixed_parameters'],**dict(zip(result['variable_parameter_names'],result['configurations'][point['configuration_id']]))}
            self.assertEqual(restored,point['parameters'])
        self.assertIsInstance(PUBLIC_CONTRACT_FIELDS,tuple)


if __name__=='__main__':unittest.main()
