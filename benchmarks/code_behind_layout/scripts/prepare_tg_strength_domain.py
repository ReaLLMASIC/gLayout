"""Declare a new TG sizing domain after the retained weak-channel diagnostic."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/textbook-sharing-readonly/benchmarks/textbook_sharing'))
from textbook_sharing.netlist import Circuit,emit_subckt

original=ROOT/'configs/development/train_tg01_family'
out=ROOT/'configs/development/train_tg01_strength4_family'
if out.exists():raise ValueError('Preserve existing prospective sizing declarations')
(out/'references').mkdir(parents=True);(out/'contracts').mkdir()
descriptor=json.loads((original/'circuit_input.json').read_text());circuit=Circuit.from_json(descriptor)
(out/'circuit_input.json').write_text(json.dumps(descriptor,indent=2)+'\n')
table=json.loads((original/'configurations.json').read_text());table['circuit_input_file']=str((out/'circuit_input.json').relative_to(ROOT))
table['development_domain_id']='TRAIN_TG01_strength4'
table['sizing_change']={'parent_table':str((original/'configurations.json').relative_to(ROOT)),
    'width_and_fingers_multiplier':4,'channel_length_unchanged':True,'external_load_and_all_specs_unchanged':True,
    'reason':'Original real schematic and postlayout SS loaded gain about0.345/0.348 failed the declared0.5 core gate. This new engineering sizing is not training data or an edited source candidate.'}
for row in table['configurations']:
    identifier=row['configuration_id'];sizing=row['parameters']['sizing']
    for value in sizing.values():value['w']*=4;value['nf']*=4
    ref=out/'references'/(identifier+'.spice');ref.write_text(emit_subckt('sky130',circuit,sizing,'corpus_train_tg01',per_finger=True,lvs=True))
    contract=json.loads((ROOT/row['contract_file']).read_text());contract['task_id']='development_train_domain_train_tg01_strength4'
    contract['reference_id']='train_tg01_strength4_'+identifier+'_perfinger';contract['sizing_origin']=table['sizing_change']
    file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
    row.update(reference_file=str(ref.relative_to(ROOT)),contract_file=str(file.relative_to(ROOT)))
(out/'configurations.json').write_text(json.dumps(table,indent=2)+'\n')
print(json.dumps({'new_table':str(out/'configurations.json'),'old_table_unchanged':True,'source_lineages':1,'formal_training_rows':0}))
