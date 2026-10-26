"""Declare the full C01 per-device finger-count Cartesian domain before physics."""
import itertools
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/textbook-sharing-readonly/benchmarks/textbook_sharing'))
from textbook_sharing.netlist import Circuit,emit_subckt

base=json.loads((ROOT/'runtime/train_collections/c01_collection_v1/collection.json').read_text())
registry=json.loads(Path(base['registry_path']).read_text());anchor=next(p for p in registry['configurations'] if p['domain_role']=='anchor')
descriptor=anchor['parameters']['circuit'];circuit=Circuit.from_json(descriptor)
out=ROOT/'configs/development/c01_per_device_nf_family'
if out.exists():raise ValueError('Preserve the prospective declaration; do not overwrite points after observing outcomes')
(out/'references').mkdir(parents=True);(out/'contracts').mkdir();(out/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n')
grid=[(4,4)]+[point for point in itertools.product([2,4,6],[2,4,6]) if point!=(4,4)]
rows=[];commands=[]
for nf1,nf2 in grid:
    length=.6
    identifier='anchor' if (nf1,nf2)==(4,4) else 'dev_n'+str(nf1)+'_'+str(nf2)
    sizing={name:{'w':3.0,'l':length,'nf':nf} for name,nf in [('M1',nf1),('M2',nf2)]}
    reference=out/'references'/(identifier+'.spice');reference.write_text(emit_subckt('sky130',circuit,sizing,'corpus_c01',per_finger=True,lvs=True))
    contract=json.loads(json.dumps(anchor['contract']));contract.update(task_id='development_train_domain_c01_per_device_nf',configuration_id=identifier,
        reference_id='c01_per_device_nf_'+identifier+'_perfinger',scope='DRAFT_UNLAUNCHED_INDEPENDENT_PER_DEVICE_FINGER_AXES')
    contract['sizing_semantics']={'total_width_um':3.0,'matched_ratio':'1:1','nf':{'M1':nf1,'M2':nf2},'per_finger_width_um':{'M1':3.0/nf1,'M2':3.0/nf2},
        'axes':'Full3x3 Cartesian nf(M1),nf(M2)={2,4,6}, fixed totalW3um and L.6um per device. No point selected from candidate outcomes.'}
    file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
    rows.append({'configuration_id':identifier,'role':'anchor' if identifier=='anchor' else 'development',
        'parameters':{'circuit_id':'C01','sizing':sizing},'reference_file':str(reference.relative_to(ROOT)),
        'contract_file':str(file.relative_to(ROOT)),'independently_generated_reference_before_any_candidate':True,'predicted_grouping':{'sharing_group_sizes':[2] if nf1==nf2 else [1,1],'basis':'Actual source sharing_groups requires equal L and per-finger unit_width; graph and body remain identical. This is an algorithmic grouping expectation, not a physical pass or preference label.'}})
    commands.append({'configuration_id':identifier,'argv':['python3','scripts/run_eda_probe.py','--script','corpus_yield_pilot.py','--magic-runtime','magic-8.3.685','--timeout','1200','--',
        '--circuit','C01','--limit','0','--family-table','/work/configs/development/c01_per_device_nf_family/configurations.json','--configuration-id',identifier]})
table={'status':'DRAFT_DECLARED_NO_PHYSICS_OR_MODEL_REQUESTS','source_revision':'1f90e33913208e572744b7c5a144a7da8c073235',
    'parent_lineage':'textbook_universal_compiler_cropped','circuit_id':'C01','development_domain_id':'C01_per_device_nf',
    'circuit_input_file':str((out/'circuit_input.json').relative_to(ROOT)),'configurations':rows,
    'hypothesis':'At fixed electrical totalW/L and1:1 ratio, independent per-device fingerization changes equal-unitwidth grouping: three diagonal two-device groups and six offdiagonal two-single-device cases. Actual current matching, ro, compliance, physical feasibility and candidate preferences remain unknown until measurement. No opposite preference or successful label is assumed.',
    'grid_selected_from_candidate_outcomes':False,'source_lineages':1,'physical_runs':0,'model_requests':0,
    'old_frozen_domains_and_labels_changed':False,'requires_actual_original_program9point_qualification_before_collection_freeze':True}
(out/'configurations.json').write_text(json.dumps(table,indent=2)+'\n')
(out/'qualification_commands.json').write_text(json.dumps({'status':'PREPARED_NOT_LAUNCHED','resource_rule':'Only after the current C02 qualification lane has completed; one2CPU worker, actualbusy+2<=24/RAM<=190GiB before every dispatch','commands':commands},indent=2)+'\n')
print(json.dumps({'table':str(out/'configurations.json'),'points':9,'total_W_um':3.0,'nf_values_per_device':[2,4,6],'fixed_L_um':.6,'per_finger_W_um':[1.5,.75,.5],'physical_runs':0,'formal_training_rows':0}))
