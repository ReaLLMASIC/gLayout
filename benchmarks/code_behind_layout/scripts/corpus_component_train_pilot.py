"""Actual development controls for the cropped-compiler C07 and TRAIN_TG01."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode=True
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--table',type=Path,required=True);p.add_argument('--configuration-id',required=True);p.add_argument('--prelayout-only',action='store_true');p.add_argument('--solver',choices=['trap','gear2'],default='trap');p.add_argument('--retry-of');p.add_argument('--independent-transient-inputs',action='store_true');a=p.parse_args()
root=Path('/work');out=Path.cwd();table=json.loads(a.table.read_text());point=next(row for row in table['configurations'] if row['configuration_id']==a.configuration_id)
if table['circuit_id'] not in ['C02','C07','TRAIN_TG01']:raise ValueError('Unsupported explicitly declared graph')
source=out/'source_pack';shutil.copytree(root/'runtime/train_collections/c01_collection_v1/source_pack',source)
for path in source.rglob('*'):
    if path.is_dir():path.chmod(0o755)
source.chmod(0o755)
descriptor=json.loads((root/table['circuit_input_file']).read_text())
for name,value in [('circuit_input.json',descriptor),('sizing_input.json',point['parameters']['sizing'])]:
    file=source/name;file.chmod(0o644);file.write_text(json.dumps(value,indent=2)+'\n')
verification=out/'verification_source/src';verification.mkdir(parents=True)
for name in ['physical_drc.py','report_parsers.py','spice_validation.py','corpus_metrics.py','device_intent.py']:
    shutil.copyfile(root/'src'/name,verification/name)
(verification/'__init__.py').write_text('')
shutil.copyfile(root/'src/corpus_component_benches.py',out/'corpus_component_benches.py')
sys.path[:0]=[str(verification.parent),str(out),str(source),str(root)]
from textbook_sharing.netlist import Circuit,emit_subckt
from corpus_component_benches import dump,evaluate
circuit=Circuit.from_json(descriptor);sizes=point['parameters']['sizing'];name='corpus_'+circuit.circuit_id.lower()
gold=out/'target.spice';declared=(root/point['reference_file']).read_text()
if emit_subckt('sky130',circuit,sizes,name,per_finger=True,lvs=True)!=declared:raise ValueError('Original emitter differs from the reference exported before any layout')
gold.write_text(declared);contract=json.loads((root/point['contract_file']).read_text());dump(out/'contract.json',contract)
dump(out/'configuration.json',{'circuit':descriptor,'sizing':sizes,'configuration_id':point['configuration_id']})
dump(out/'development_numerical_control.json',{'integration_method':a.solver,'retry_of':a.retry_of,'changed_electrical_specifications':False,
    'changed_tolerances':False,'changed_RC':False,'independent_transient_inputs':a.independent_transient_inputs,
    'scope':'development_only_new_run_original_evidence_retained'})
gds=out/'candidate.gds'
if not a.prelayout_only:
    import gdstk
    from glayout import sky130
    from textbook_sharing.layout import build
    built=build(sky130,circuit,sizes,mode='independent',name=name);built['component'].write_gds(gds)
    top,=gdstk.read_gds(gds).top_level();top.flatten();top.name=name;library=gdstk.Library();library.add(top);library.write_gds(gds)
    dump(out/'compiler_metadata.json',{key:built[key] for key in ['applied_plans','assembly_stats']})
loaded={key:str(Path(module.__file__).resolve()) for key,module in sys.modules.items() if key.startswith(('glayout','textbook_sharing')) and getattr(module,'__file__',None)}
if not all(Path(path).is_relative_to(source) for path in loaded.values()):raise ValueError('Compiler source escaped its cropped pack')
dump(out/'loaded_modules.json',loaded)
result=evaluate(out/'evaluation',circuit,sizes,name,gds,gold,contract,prelayout=a.prelayout_only,solver=a.solver,independent_transient_inputs=a.independent_transient_inputs)
dump(out/'bench_result.json',result)
print(json.dumps(result,indent=2),flush=True)
raise SystemExit(0 if result.get('all_analyses_complete') and result.get('all_operating_points_valid') and (a.prelayout_only or result.get('full_physical_analysis_complete')) else 2)
