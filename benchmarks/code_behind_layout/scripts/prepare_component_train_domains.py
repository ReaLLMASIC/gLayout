"""Declare real C07 pair and authored TRAIN_TG01 switch inputs before layout."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];public=ROOT/'vendor/textbook-sharing-readonly'
revision=subprocess.check_output(['git','-C',str(public),'rev-parse','HEAD'],text=True).strip()
if revision!='1f90e33913208e572744b7c5a144a7da8c073235':raise ValueError('Public compiler revision changed')
sys.path.insert(0,str(public/'benchmarks/textbook_sharing'))
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.netlist import Circuit,emit_subckt

pair=CIRCUITS['C07'].to_json()
tg={'circuit_id':'TRAIN_TG01','name':'authored_complementary_transmission_gate',
    'ports':['VDD','VSS','VIN1','VOUT1','VC1','VC2'],
    'devices':[{'name':'M1','kind':'nfet','nets':['VOUT1','VC1','VIN1','VSS'],'params':{}},
               {'name':'M2','kind':'pfet','nets':['VOUT1','VC2','VIN1','VDD'],'params':{}}],
    'source':{'kind':'new_authored_task_descriptor','author_role':'research_engineering',
              'not_an_existing_public_C04':'Public C04 is a common-source amplifier; no TG exists among the public18 descriptors.',
              'graph':'Parallel NMOS/PMOS channels; complementary external controls, separate well/body rails.'},
    'notes':['Circuit input to the same public universal compiler, not an independent generator lineage.']}
points=[('anchor',1,.5,.3),('dev_nf_half',.5,.5,.3),('dev_nf_3quarters',.75,.5,.3),('dev_nf_1half',1.5,.5,.3),
        ('dev_nf_double',2,.5,.3),('dev_len045',1,.5,.45),('dev_len060',1,.5,.6),('dev_unit075',1,.75,.3),('dev_unit100',1,1.,.3)]
for descriptor,nominal_nf in [(pair,{'M1':8,'M2':8,'M3':8,'M4':8}),(tg,{'M1':4,'M2':8})]:
    cid=descriptor['circuit_id'];root=ROOT/'configs/development'/(cid.lower()+'_family')
    if root.exists():raise ValueError('Preserve the existing declared domain: '+str(root))
    (root/'references').mkdir(parents=True);(root/'contracts').mkdir();(root/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n')
    rows=[]
    for identifier,scale,unit,length in points:
        sizing={name:{'w':int(nf*scale)*unit,'l':length,'nf':int(nf*scale)} for name,nf in nominal_nf.items()}
        if any(nf*scale!=int(nf*scale) for nf in nominal_nf.values()):raise ValueError('Preserve integral matched finger ratios')
        reference=root/'references'/(identifier+'.spice');reference.write_text(emit_subckt('sky130',Circuit.from_json(descriptor),sizing,'corpus_'+cid.lower(),per_finger=True,lvs=True))
        contracts=({'op':{'kind':'op','columns':6,'expected_rows':1},'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':161,'scale':'log'},
            'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
            'dc':{'kind':'dc','columns':5,'start':-.1,'end':.1,'points':41,'scale':'linear'}} if cid=='C07' else
            {'op':{'kind':'op','columns':4,'expected_rows':1},'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':161,'scale':'log'},
             'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
             'dc':{'kind':'dc','columns':3,'start':.1,'end':1.7,'points':17,'scale':'linear'},
             'off':{'kind':'dc','columns':3,'start':.1,'end':1.7,'points':17,'scale':'linear'}})
        bench=({'supply_V':1.8,'temperature_C':27,'input_common_mode_V':.9,'clamped_outputs_V':[.9,.9],
            'ideal_tail_sink_A':40e-6,'external_PMOS_replica_current_A':20e-6,'differential_AC_input_V':1,
            'differential_transient_levels_V':[-.01,.01],'differential_DC_sweep_V':[-.1,.1,.005],
            'load_definition':'Each output has an ideal 0.9V clamp. Measure differential output-current transconductance, systematic offset and current steering, not free-output voltage gain or mismatch yield.',
            'power_definition':'Main VDD supply power only; separate diode-reference and output-clamp port work are reported separately.'} if cid=='C07' else
            {'supply_V':1.8,'temperature_C':27,'on_controls_V':[1.8,0],'off_controls_V':[0,1.8],
             'nominal_input_V':.9,'on_load_R_ohm':100000,'on_load_C_F':1e-12,'input_DC_sweep_V':[.1,1.7,.1],
             'input_transient_levels_V':[.2,1.6],'off_output_clamp_V':.9,
             'load_definition':'Enabled signal transfer uses100kOhm||1pF; disabled leakage uses only an ideal0.9V output clamp, without the load resistor. Controls are static, so no switching-charge-injection claim.',
             'power_definition':'Signal-source work, external resistor dissipation, main well-supply work and channel conduction loss are separate quantities.'})
        contract={'task_id':'development_train_domain_'+cid.lower(),'configuration_id':identifier,'reference_id':cid.lower()+'_'+identifier+'_perfinger',
            'required_corners':['tt','ss','ff'],'scope':'DRAFT_DEVELOPMENT_QUALIFICATION_NOT_FORMAL',
            'objective':{'id':cid.lower()+'_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'},
            'specifications':[],'pending_before_freeze':['Actual independent anchor and all nine geometry qualification required before selecting prospective electrical floors.'],
            'nominal_operating_point':bench,'analysis_contracts':contracts}
        file=root/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
        rows.append({'configuration_id':identifier,'role':'anchor' if identifier=='anchor' else 'development','parameters':{'sizing':sizing},
            'reference_file':str(reference.relative_to(ROOT)),'contract_file':str(file.relative_to(ROOT))})
    table={'scope':'development_only_train_component_qualification','source_revision':revision,'parent_lineage':'textbook_universal_compiler_cropped',
        'circuit_id':cid,'circuit_input_file':str((root/'circuit_input.json').relative_to(ROOT)),'configurations':rows,
        'ancestry':'One cropped public universal compiler source lineage; new descriptors and geometry configurations are not new source implementations.'}
    (root/'configurations.json').write_text(json.dumps(table,indent=2)+'\n');print(json.dumps({'table':str(root/'configurations.json'),'circuit':cid,'points':len(rows),'physical_runs':0}))
