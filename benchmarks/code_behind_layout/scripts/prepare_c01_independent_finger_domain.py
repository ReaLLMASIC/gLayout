"""Declare a new unlaunched C01 domain separating total width from finger count."""
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
out=ROOT/'configs/development/c01_independent_nf_family'
if out.exists():raise ValueError('Preserve the prospective declaration; do not overwrite points after observing outcomes')
(out/'references').mkdir(parents=True);(out/'contracts').mkdir();(out/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n')
grid=[(4,.6)]+[point for point in itertools.product([2,4,6],[.3,.6,.9]) if point!=(4,.6)]
rows=[];commands=[]
for nf,length in grid:
    identifier='anchor' if (nf,length)==(4,.6) else 'dev_nf'+str(nf)+'_l'+str(int(length*100)).zfill(3)
    sizing={name:{'w':3.0,'l':length,'nf':nf} for name in ['M1','M2']}
    reference=out/'references'/(identifier+'.spice');reference.write_text(emit_subckt('sky130',circuit,sizing,'corpus_c01',per_finger=True,lvs=True))
    contract=json.loads(json.dumps(anchor['contract']));contract.update(task_id='development_train_domain_c01_independent_nf',configuration_id=identifier,
        reference_id='c01_independent_nf_'+identifier+'_perfinger',scope='DRAFT_UNLAUNCHED_INDEPENDENT_FINGER_AXIS')
    contract['sizing_semantics']={'total_width_um':3.0,'matched_ratio':'1:1','nf':nf,'per_finger_width_um':3.0/nf,
        'axes':'Full3x3 Cartesian nf={2,4,6},L={.3,.6,.9}um at fixed totalW3um. No point was selected from candidate outcomes.'}
    file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
    rows.append({'configuration_id':identifier,'role':'anchor' if identifier=='anchor' else 'development',
        'parameters':{'circuit_id':'C01','sizing':sizing},'reference_file':str(reference.relative_to(ROOT)),
        'contract_file':str(file.relative_to(ROOT)),'independently_generated_reference_before_any_candidate':True})
    commands.append({'configuration_id':identifier,'argv':['python3','scripts/run_eda_probe.py','--script','corpus_yield_pilot.py','--magic-runtime','magic-8.3.685','--timeout','1200','--',
        '--circuit','C01','--limit','0','--family-table','/work/configs/development/c01_independent_nf_family/configurations.json','--configuration-id',identifier]})
table={'status':'DRAFT_DECLARED_NO_PHYSICS_OR_MODEL_REQUESTS','source_revision':'1f90e33913208e572744b7c5a144a7da8c073235',
    'parent_lineage':'textbook_universal_compiler_cropped','circuit_id':'C01','development_domain_id':'C01_independent_nf',
    'circuit_input_file':str((out/'circuit_input.json').relative_to(ROOT)),'configurations':rows,
    'hypothesis':'At fixed totalW, changing nf changes legal per-finger width, grouping and placement. Test whether these independent axes produce actual configuration-dependent area/feasibility rankings. The current domain already varies nf1..8 with mostly coupled totalW; no causal claim is made about its zero observed preference conflicts.',
    'grid_selected_from_candidate_outcomes':False,'source_lineages':1,'physical_runs':0,'model_requests':0,
    'old_frozen_domains_and_labels_changed':False,'requires_actual_original_program9point_qualification_before_collection_freeze':True}
(out/'configurations.json').write_text(json.dumps(table,indent=2)+'\n')
(out/'qualification_commands.json').write_text(json.dumps({'status':'PREPARED_NOT_LAUNCHED','resource_rule':'Do not compete with current C07/TG two-worker qualification; later at most one2CPU job and actualbusy+2<=24/RAM<=190GiB','commands':commands},indent=2)+'\n')
print(json.dumps({'table':str(out/'configurations.json'),'points':9,'total_W_um':3.0,'nf_values':[2,4,6],'per_finger_W_um':[1.5,.75,.5],'physical_runs':0,'formal_training_rows':0}))
