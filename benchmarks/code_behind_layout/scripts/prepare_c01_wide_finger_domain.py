"""Predeclare all nine wide-device nf points; test an explicit model hypothesis."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'vendor/textbook-sharing-readonly/benchmarks/textbook_sharing'))
from textbook_sharing.netlist import Circuit,emit_subckt
prior=ROOT/'configs/development/c01_per_device_nf_family';table=json.loads((prior/'configurations.json').read_text())
out=ROOT/'configs/development/c01_per_device_nf_wide_family'
if out.exists():raise ValueError('Do not alter a predeclared grid after measurements')
(out/'references').mkdir(parents=True);(out/'contracts').mkdir();descriptor=json.loads((prior/'circuit_input.json').read_text());(out/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n');circuit=Circuit.from_json(descriptor);points=[]
for old in table['configurations']:
    identifier='wide_'+old['configuration_id'];sizing={name:{**s,'w':30.0} for name,s in old['parameters']['sizing'].items()}
    reference=out/'references'/(identifier+'.spice');reference.write_text(emit_subckt('sky130',circuit,sizing,'corpus_c01',per_finger=True,lvs=True))
    contract=json.loads((ROOT/old['contract_file']).read_text());contract.update(task_id='development_train_domain_c01_wide_nf',configuration_id=identifier,
        reference_id='c01_wide_'+old['configuration_id']+'_perfinger',scope='DRAFT_PREDECLARED_WIDE_WIDTH_IDEAL_QUALIFICATION_PENDING',
        sizing_semantics={'total_width_um':30.0,'length_um':.6,'nf':{name:s['nf'] for name,s in sizing.items()},'per_finger_width_um':{name:30/s['nf'] for name,s in sizing.items()},'matched_ratio':'1:1'})
    file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
    points.append({'configuration_id':identifier,'role':old['role'],'parameters':{'circuit_id':'C01','sizing':sizing},'reference_file':str(reference.relative_to(ROOT)),'contract_file':str(file.relative_to(ROOT)),'same_nf_pair_as':old['configuration_id'],'grouping_expectation':old['predicted_grouping']})
record={'status':'DRAFT_NO_IDEAL_OR_LAYOUT_MEASUREMENTS','source_revision':table['source_revision'],'parent_lineage':table['parent_lineage'],'source_lineages':1,
    'circuit_id':'C01','development_domain_id':'C01_wide_per_device_nf','circuit_input_file':str((out/'circuit_input.json').relative_to(ROOT)),'configurations':points,
    'hypothesis':'The complete same-nf and off-diagonal grid remains {2,4,6}x{2,4,6}; both device total widths are prospectively 30um, so finger widths are5/7.5/15um rather than.5/.75/1.5um. This tests whether model narrow-width dependence caused the original ideal mismatch. No physical pass or current matching is assumed; unchanged5% current/300kohm/compliance constraints apply. All nine ideal points must qualify before any layout.',
    'configuration_or_spec_selected_by_postlayout_outcomes':False,'retained_original_domain_unchanged':str(prior/'configurations.json'),
    'reference_sizing_fixed_before_any_new_ideal_simulation':True,'formal_training_rows':0,'model_requests':0,'ideal_or_layout_runs':0}
(out/'configurations.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'table':str(out/'configurations.json'),'points':len(points),'ideal_or_layout_runs':0}))
