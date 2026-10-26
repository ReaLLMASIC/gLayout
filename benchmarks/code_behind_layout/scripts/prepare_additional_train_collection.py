"""Create a read-only draft C05/C08 capsule after complete measured qualification."""
import argparse,ast
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--circuit',choices=['C05','C08'],required=True);a=p.parse_args();cid=a.circuit
qualification=json.loads((ROOT/'results/derived/C05_C08_domain_development_qualification.json').read_text())['circuits'][cid]
if not qualification['all_points_ready']:raise ValueError('Every declared geometry must finish full physical/electrical qualification before this preparation')
v1=json.loads((ROOT/'runtime/train_collections/c01_collection_v1/collection.json').read_text());source=Path(v1['source_pack'])
specs=([{'name':'gain_10Hz_real','unit':'1','min':.6},{'name':'f3db_Hz','unit':'Hz','min':40e6},{'name':'DUT_supply_power_W','unit':'W','max':100e-6}] if cid=='C05' else
       [{'name':'gain_10Hz_dB','unit':'dB','min':25},{'name':'ugb_Hz','unit':'Hz','min':10e6},{'name':'phase_margin_deg','unit':'deg','min':60},{'name':'settled_tracking_error_V','unit':'V','max':.015},{'name':'DUT_supply_power_W','unit':'W','max':100e-6}])
for point in qualification['points']:
    for corner,metrics in point['corners'].items():
        for spec in specs:
            value=metrics[spec['name']]
            if ('min' in spec and value<spec['min']) or ('max' in spec and value>spec['max']):raise ValueError('Proposed prospective hard specification is not feasible: '+point['configuration_id']+'/'+corner+'/'+spec['name'])
out=ROOT/'runtime/collection_preparation'/(cid.lower()+'_collection_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
trusted=out/'trusted';(trusted/'contracts').mkdir(parents=True);(trusted/'references').mkdir()
shutil.copyfile(ROOT/'scripts/corpus_additional_collection_evaluator.py',trusted/'evaluate.py')
shutil.copyfile(ROOT/'vendor/glayout/src/glayout/verification/run_pex.sh',trusted/'run_pex.sh')
code=(ROOT/'scripts/corpus_yield_pilot.py').read_text();tree=ast.parse(code);function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='evaluate_gds')
(trusted/'physical.py').write_text('import json\nfrom pathlib import Path\nimport subprocess\nREVISION="1f90e33913208e572744b7c5a144a7da8c073235"\ndef dump(path,data):Path(path).write_text(json.dumps(data,indent=2)+"\\n")\n'+ast.get_source_segment(code,function)+'\n')
for name in ['physical_drc.py','report_parsers.py','spice_validation.py','measurement.py','corpus_metrics.py']:
    path=trusted/'src'/name;path.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/'src'/name,path)
(trusted/'src/__init__.py').write_text('')
table=json.loads((ROOT/'configs/development'/(cid.lower()+'_family/configurations.json')).read_text())
original_run=Path(next(row['raw_run'] for row in qualification['points'] if row['configuration_id']=='anchor'))
circuit=json.loads((original_run/'circuit_input.json').read_text());points=[]
for point in table['configurations']:
    identifier=point['configuration_id'];contract=json.loads((ROOT/point['contract_file']).read_text())
    contract.update(task_id='train_collection_'+cid.lower(),scope='DRAFT_COLLECTION_AFTER_ACTUAL_NINE_POINT_QUALIFICATION',specifications=specs)
    contract.pop('pending_before_freeze',None)
    (trusted/'contracts'/(identifier+'.json')).write_text(json.dumps(contract,indent=2)+'\n');shutil.copyfile(ROOT/point['reference_file'],trusted/'references'/(identifier+'.spice'))
    points.append({'configuration_id':identifier,'role':point['role'],'reference_id':contract['reference_id'],'contract':contract,
        'parameters':{'configuration_id':identifier,'circuit':circuit,'sizing':point['parameters']['sizing'],'top_cell':'corpus_'+cid.lower()}})
objective=cid.lower()+'_area_min'
metadata={'status':'DRAFT_READONLY_COLLECTION_CAPSULE_NOT_FROZEN','circuit_id':cid,'source_revision':table['source_revision'],
    'parent_lineage':table['parent_lineage'],'source_pack':str(source),'source_files':sorted(str(path.relative_to(source)) for path in source.rglob('*') if path.is_file()),
    'editable_paths':['textbook_sharing/layout.py'],'trusted_bundle':str(trusted),'trusted_files':sorted(str(path.relative_to(trusted)) for path in trusted.rglob('*') if path.is_file()),
    'configurations':points,'qualification_path':str(ROOT/'results/derived/C05_C08_domain_development_qualification.json'),
    'prospective_hard_specifications':specs,'objective':points[0]['contract']['objective'],
    'label_rule_draft':{'objectives':{objective:{'metric':'area','unit':'um2','direction':'min','quality_absolute_tolerance':1e-8,'quality_relative_tolerance':1e-6,'quality_minimum_relative_effect':.01}}},
    'source_scope_note':'Actual generic C01-v1 source capsule is reused byte-for-byte; generator.py consumes the host configuration, not the unused frozen circuit_input.json. The sole editable layout.py is the same compiler lineage.',
    'power_scope':'DUT supply only; external20uA/40uA diode-bias power recorded separately. Three process corners at1.8V/27C.',
    'formal_collection_started':False,'old_development_evidence_relabelled':False}
(out/'preparation.json').write_text(json.dumps(metadata,indent=2)+'\n')
for path in sorted(out.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
out.chmod(0o555)
print(json.dumps({'preparation':str(out/'preparation.json'),'circuit':cid,'source_files':len(metadata['source_files']),'trusted_files':len(metadata['trusted_files']),'state':'DRAFT_NEEDS_REAL_ISOLATED_FINAL_SMOKE'}))
