"""Create the actual read-only draft C01 source/reference/evaluator capsule."""
import ast
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.corpus_isolated_evaluate import CANDIDATE
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
out=ROOT/'runtime/collection_preparation'/('c01_'+stamp);out.mkdir(parents=True)
source=out/'source_pack';shutil.copytree(ROOT/'runs/phase0/phase0_20261018T234700264280Z_corpus_yield_pilot/base_source',source)
(source/'generator.py').write_text(CANDIDATE)
trusted=out/'trusted';trusted.mkdir()
shutil.copyfile(ROOT/'scripts/c01_collection_evaluator.py',trusted/'evaluate.py')
shutil.copyfile(ROOT/'vendor/glayout/src/glayout/verification/run_pex.sh',trusted/'run_pex.sh')
physical_source=(ROOT/'scripts/corpus_yield_pilot.py').read_text();tree=ast.parse(physical_source)
function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='evaluate_gds')
(trusted/'physical.py').write_text('import json\nfrom pathlib import Path\nimport subprocess\nREVISION="1f90e33913208e572744b7c5a144a7da8c073235"\ndef dump(path,data):Path(path).write_text(json.dumps(data,indent=2)+"\\n")\n'+ast.get_source_segment(physical_source,function)+'\n')
for name in ['physical_drc.py','report_parsers.py','spice_validation.py','measurement.py','corpus_metrics.py']:
 path=trusted/'src'/name;path.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/'src'/name,path)
(trusted/'src/__init__.py').write_text('')
(trusted/'references').mkdir();(trusted/'contracts').mkdir()
table=json.loads((ROOT/'configs/development/c01_family/configurations.json').read_text())
circuit=json.loads((source/'circuit_input.json').read_text());points=[]
for point in table['configurations']:
 id=point['configuration_id'];contract=json.loads((ROOT/point['contract_file']).read_text())
 contract.update(task_id='train_collection_c01',scope='DRAFT_NOT_FROZEN',specifications=[{'name':'nominal_current_relative_error','unit':'1','max':.05},{'name':'output_resistance','unit':'ohm','min':300000},{'name':'compliance_band_max_relative_error','unit':'1','max':.05}],objective={'id':'c01_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'})
 contract['declared_compliance_sample_grid_V']=[.7,.8,.9,1.0]
 (trusted/'contracts'/(id+'.json')).write_text(json.dumps(contract,indent=2)+'\n')
 shutil.copyfile(ROOT/point['reference_file'],trusted/'references'/(id+'.spice'))
 parameters={'configuration_id':id,'circuit':circuit,'sizing':point['parameters']['sizing'],'top_cell':'corpus_c01'}
 points.append({'configuration_id':id,'parameters':parameters,'reference_id':contract['reference_id'],'contract':contract,'role':'anchor' if id=='anchor' else 'development'})
files=lambda root:sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())
metadata={'status':'DRAFT_READONLY_COLLECTION_CAPSULE_NOT_FROZEN','source_revision':table['source_revision'],'parent_lineage':table['parent_lineage'],'source_pack':str(source),'source_files':files(source),'editable_paths':['textbook_sharing/layout.py','glayout/sharing/enumeration.py'],'trusted_bundle':str(trusted),'trusted_files':files(trusted),'configurations':points,'formal_training_rows':0,'formal_collection_started':False,'per_task_context_scope':'complete modules only; actual length gate, no truncation; C08 uses a separate narrower scope if necessary','candidate_boundary':'explicit source/library only, sole GDS handoff to trusted process','label_rule_draft':{'objectives':{'c01_area_min':{'metric':'area','unit':'um2','direction':'min','quality_absolute_tolerance':1e-8,'quality_relative_tolerance':1e-6,'quality_minimum_relative_effect':.01}}}}
(out/'preparation.json').write_text(json.dumps(metadata,indent=2)+'\n')
for path in sorted(out.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
out.chmod(0o555)
print(json.dumps({'preparation':str(out/'preparation.json'),'source_pack':str(source),'trusted_bundle':str(trusted),'trusted_files':len(metadata['trusted_files']),'source_files':len(metadata['source_files']),'status':metadata['status']}),flush=True)
