"""Declare C02 cascode-mirror input, per-point reference and applicable bench."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
public=ROOT/'vendor/textbook-sharing-readonly'
revision=subprocess.check_output(['git','-C',str(public),'rev-parse','HEAD'],text=True).strip()
if revision!='1f90e33913208e572744b7c5a144a7da8c073235':raise ValueError('Public compiler revision differs')
sys.path.insert(0,str(public/'benchmarks/textbook_sharing'))
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.netlist import Circuit,emit_subckt

descriptor=CIRCUITS['C02'].to_json()
if [(d['name'],d['nets']) for d in descriptor['devices']]!=[
    ('M1',['IIN1','IIN1','net6','VSS']),('M2',['net6','net6','VSS','VSS']),
    ('M3',['IOUT1','IIN1','net12','VSS']),('M4',['net12','net6','VSS','VSS'])]:
    raise ValueError('Expected the actual four-NMOS self-biased cascode mirror')
out=ROOT/'configs/development/c02_family'
if out.exists():raise ValueError('Do not overwrite an existing declared domain')
(out/'contracts').mkdir(parents=True);(out/'references').mkdir()
(out/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n')
points=[('anchor',1,.5,.6),('dev_nf_half',.5,.5,.6),('dev_nf_3quarters',.75,.5,.6),
    ('dev_nf_1half',1.5,.5,.6),('dev_nf_double',2,.5,.6),('dev_len045',1,.5,.45),
    ('dev_len090',1,.5,.9),('dev_unit075',1,.75,.6),('dev_unit100',1,1.,.6)]
rows=[]
for identifier,scale,unit,length in points:
    nf=int(8*scale)
    sizes={device['name']:{'w':nf*unit,'l':length,'nf':nf} for device in descriptor['devices']}
    reference=out/'references'/(identifier+'.spice')
    reference.write_text(emit_subckt('sky130',Circuit.from_json(descriptor),sizes,'corpus_c02',per_finger=True,lvs=True))
    contract={'task_id':'development_train_domain_c02','configuration_id':identifier,
        'reference_id':'c02_'+identifier+'_perfinger','required_corners':['tt','ss','ff'],
        'scope':'DRAFT_DEVELOPMENT_QUALIFICATION_NOT_FORMAL',
        'objective':{'id':'c02_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'},
        'specifications':[],'pending_before_freeze':['Actual schematic and full physical domain qualification; prospective application constraints are not formal labels.'],
        'prospective_application_constraints':{'nominal_current_relative_error_max':.05,'output_resistance_ohm_min':300000,
            'max_current_relative_error_1p3_to_1p7V':.05},
        'nominal_operating_point':{'supply_V':1.8,'temperature_C':27,'reference_current_A':5e-6,'output_V':1.5,
            'output_DC_sweep_V':[0,1.8,.05],'output_transient_levels_V':[1.475,1.525],
            'current_compliance_application_region_V':[1.3,1.7],
            'load_definition':'Output voltage source sweeps the cascode compliance region; output-port current is measured. Bias is the two diode-connected reference devices in the immutable DUT, with a5uA external source from1.8V. No0.9V mirror clamp or voltage-gain claim.',
            'power_definition':'Three-port DUT has no VDD pin. Report input-port and output-port dissipation, and external1.8V reference-source supply work separately.'},
        'analysis_contracts':{'op':{'kind':'op','columns':4,'expected_rows':1},
            'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':161,'scale':'log'},
            'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
            'dc':{'kind':'dc','columns':3,'start':0,'end':1.8,'points':37,'scale':'linear'}}}
    file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
    rows.append({'configuration_id':identifier,'role':'anchor' if identifier=='anchor' else 'development',
        'parameters':{'sizing':sizes},'reference_file':str(reference.relative_to(ROOT)),'contract_file':str(file.relative_to(ROOT))})
table={'scope':'DRAFT_DEVELOPMENT_QUALIFICATION_ONLY','source_revision':revision,'parent_lineage':'textbook_universal_compiler_cropped',
    'circuit_id':'C02','circuit_input_file':str((out/'circuit_input.json').relative_to(ROOT)),'configurations':rows,
    'ancestry':'Same cropped universal compiler source; no new source lineage. Geometry and per-finger references are fixed before any layout.'}
(out/'configurations.json').write_text(json.dumps(table,indent=2)+'\n')
print(json.dumps({'table':str(out/'configurations.json'),'points':9,'physical_runs':0,'model_requests':0}))
