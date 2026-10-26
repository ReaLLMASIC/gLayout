"""Execute actual development compiler proposals through the two-container gate.

Candidate sees only the cropped program/library and configuration. The separate
trusted process receives only its GDS, an immutable pre-existing gold and bench.
This produces engineering yield evidence, never formal corpus admission.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor,apply_source_patch

CANDIDATE=r'''import argparse,json,sys
from pathlib import Path
import gdstk
sys.path.insert(0,"/source")
from glayout import sky130
from textbook_sharing.netlist import Circuit
from textbook_sharing.layout import build
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
configuration=json.loads(Path(a.configuration).read_text())
circuit=Circuit.from_json(configuration["circuit"])
result=build(sky130,circuit,configuration["sizing"],mode="independent",name=configuration["top_cell"])
result["component"].write_gds(a.output)
top,=gdstk.read_gds(a.output).top_level();top.flatten();top.name=configuration["top_cell"]
library=gdstk.Library();library.add(top);library.write_gds(a.output)
'''

EVALUATOR=r'''import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,"/trusted")
from corpus_yield_pilot import evaluate_gds
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=Path(a.output);configuration=json.loads(Path("/configuration.json").read_text())
contract=json.loads(Path("/trusted/contract.json").read_text())
circuit=SimpleNamespace(circuit_id=configuration["circuit"]["circuit_id"],ports=configuration["circuit"]["ports"])
result=evaluate_gds(out,circuit,configuration["sizing"],configuration["top_cell"],Path(a.gds),Path("/trusted/reference.spice"),Path("/trusted/run_pex.sh"))
(out/"drc_full/metadata.json").write_text(json.dumps(result["DRC"],indent=2)+"\n")
observation={key:contract[key] for key in ["task_id","configuration_id","reference_id"]}
clean=result.get("LVS",{}).get("is_clean",False)
observation.update(executed=True,gds_emitted=True,checks={"drc":result.get("DRC",{}).get("is_clean",False),"lvs":clean,"devices":clean,"ports":clean,"intent":clean},corners={})
rc=result.get("RC",{});real=rc.get("has_real_RC",False)
observation["pex"]={"executed":result.get("pex_returncode")==0,"kind":"physical_rc","resistance_extracted":real,"capacitance_extracted":real}
artifacts={"drc":{"report":"drc_full/direct_drc.rpt","metadata":"drc_full/metadata.json"},"lvs":{"report":"netgen_lvs.rpt"},"spice":{}}
if real:artifacts["pex"]={"netlist":configuration["top_cell"]+"_pex.spice","top_cell":configuration["top_cell"]+"_rc","ports":circuit.ports}
for corner,row in result.get("corners",{}).items():
 metrics=row["metrics"]
 units={"nominal_current_relative_error":"1","gain_10Hz_real":"1","f3db_Hz":"Hz","gain_10Hz_dB":"dB","phase_margin_deg":"deg","ugb_Hz":"Hz","settled_tracking_error_V":"V"}
 measured={key:{"value":metrics[key],"unit":unit} for key,unit in units.items() if key in metrics}
 valid=row["complete"] and 0<metrics.get("bias_V",0)<1.8
 if circuit.circuit_id=="C01":valid=valid and abs(metrics.get("output_bias_V",0)-.9)<1e-6
 elif circuit.circuit_id=="C05":valid=valid and .1<metrics.get("output_bias_V",0)<1.7
 elif circuit.circuit_id=="C08":valid=valid and abs(metrics.get("output_bias_V",0)-.9)<=.015
 observation["corners"][corner]={"converged":row["complete"],"operating_point_valid":valid,"metrics":measured}
 artifacts["spice"][corner]={"analyses":{name:{"data":corner+"/"+name+".dat","log":corner+"/"+("ac" if name=="op" else name)+".log","returncode":analysis["returncode"]} for name,analysis in row["analyses"].items()}}
validation={"contract":contract,"observation":observation,"artifacts":artifacts,"assessment":assess(contract,observation),"scope":"development_corpus_yield_not_formal_or_training","analysis_complete":result.get("full_physical_analysis_complete",False)}
(out/"validation.json").write_text(json.dumps(validation,indent=2)+"\n")
print(json.dumps(validation,indent=2),flush=True)
raise SystemExit(0 if validation["assessment"]["S2"] and validation["analysis_complete"] else 2)
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--model-pool',help='Filename under source-run; absent runs the original baseline only')
    p.add_argument('--limit',type=int,default=8)
    p.add_argument('--source-pack',type=Path)
    p.add_argument('--reference',type=Path)
    a=p.parse_args();original=a.source_run.resolve();original.relative_to(ROOT/'runs/phase0')
    if not 1<=a.limit<=16:raise ValueError('Use a bounded 1..16 candidate batch')
    base=(a.source_pack or original/'base_source').resolve();text=(base/'textbook_sharing/layout.py').read_text()
    circuit=json.loads((base/'circuit_input.json').read_text());sizing=json.loads((base/'sizing_input.json').read_text())
    cid=circuit['circuit_id']
    if cid not in ['C01','C05','C08']:raise ValueError('Only explicitly implemented circuit benches are allowed')
    if a.model_pool:
        pool=json.loads((original/a.model_pool).read_text())
        if pool['editable_source']!=text or pool['circuit_id']!=circuit['circuit_id']:raise ValueError('Pool initial state changed')
        proposals=pool['candidates'][:a.limit]
    else:proposals=[{'candidate_id':'original_baseline','patch':'','proposal_source':'unmodified_compiler_boundary_smoke'}]
    name='corpus_'+cid.lower();out=ROOT/'runs/development/corpus_isolated_inputs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+uuid.uuid4().hex[:6]);out.mkdir(parents=True)
    trusted=out/'trusted';trusted.mkdir()
    reference=(a.reference or original/'baseline/target.spice').resolve()
    text_reference=reference.read_text();declarations=[line.split() for line in text_reference.splitlines() if line.lower().startswith('.subckt ')]
    if len(declarations)!=1:raise ValueError('The pre-existing immutable gold must contain one target subcircuit')
    original_name=declarations[0][1]
    # Cell identity changes only the top declaration/end marker, never graph, ports or sizes.
    text_reference='\n'.join(('.subckt '+name+' '+' '.join(line.split()[2:])) if line.lower().startswith('.subckt ') else ('.ends '+name) if line.lower().startswith('.ends') else line for line in text_reference.splitlines())+'\n'
    (trusted/'reference.spice').write_text(text_reference)
    (trusted/'reference_origin.json').write_text(json.dumps({'path':str(reference),'original_top':original_name,'evaluated_top':name,'graph_and_sizes_changed':False},indent=2)+'\n')
    shutil.copyfile(ROOT/'vendor/glayout/src/glayout/verification/run_pex.sh',trusted/'run_pex.sh')
    shutil.copyfile(ROOT/'scripts/corpus_yield_pilot.py',trusted/'corpus_yield_pilot.py')
    (trusted/'evaluate.py').write_text(EVALUATOR)
    for filename in ['physical_drc.py','report_parsers.py','spice_validation.py','measurement.py','corpus_metrics.py']:
        destination=trusted/'src'/filename;destination.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/'src'/filename,destination)
    (trusted/'src/__init__.py').write_text('')
    contract={'task_id':'development_corpus_'+cid+'_original_compiler','configuration_id':'anchor','reference_id':cid+'_original_perfinger_reference',
              'required_corners':['tt','ss','ff'],'specifications':[{'name':'nominal_current_relative_error','unit':'1','max':.1}],
              'objective':{'metric':'nominal_current_relative_error','direction':'min','corner_aggregation':'worst'},
              'analysis_contracts':{'op':{'kind':'op','columns':4,'expected_rows':1},'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':161,'scale':'log'},'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6]]},'dc':{'kind':'dc','columns':3,'start':0,'end':1.8,'points':19,'scale':'linear'}},
              'scope':'development_only_not_frozen'}
    if cid=='C05':
        contract.update(specifications=[{'name':'gain_10Hz_real','unit':'1','min':.6}],objective={'metric':'f3db_Hz','direction':'max','corner_aggregation':'worst'})
        contract['analysis_contracts']['dc'].update(start=.8,end=1.4,points=13)
    elif cid=='C08':
        contract.update(specifications=[{'name':'gain_10Hz_dB','unit':'dB','min':25},{'name':'phase_margin_deg','unit':'deg','min':60},{'name':'settled_tracking_error_V','unit':'V','max':.015}],objective={'metric':'ugb_Hz','direction':'max','corner_aggregation':'worst'})
        contract['analysis_contracts']['ac']['points']=241
        contract['analysis_contracts']['dc'].update(start=.6,end=1.2,points=7)
        contract['analysis_contracts']['tran']['required_windows']=[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]
    (trusted/'contract.json').write_text(json.dumps(contract,indent=2)+'\n')
    trusted_paths=sorted(str(path.relative_to(trusted)) for path in trusted.rglob('*') if path.is_file())
    executor=CandidateExecutor(ROOT/'runtime/GLdev',ROOT/'runs/development/corpus_isolated',ROOT/'runtime/magic-8.3.685',timeout=360)
    summary={'scope':'development_corpus_isolated_yield_not_formal_or_training','source_run':str(original),'proposals':[],'formal_training_rows':0}
    seen_sources={}
    for item in proposals:
        candidate_id=item['candidate_id']
        if not candidate_id.replace('_','').isalnum():raise ValueError('Unsupported candidate identifier')
        work=out/candidate_id;work.mkdir();source=work/'source';shutil.copytree(base,source)
        (work/'proposal.json').write_text(json.dumps(item,indent=2)+'\n')
        (source/'generator.py').write_text(CANDIDATE)
        if item['patch']:
            try:apply_source_patch(source,item['patch'],['textbook_sharing/layout.py'])
            except (ValueError,subprocess.CalledProcessError) as exc:
                # Exact original model diff/error retained; no repair or reformat.
                (work/'patch_failure.txt').write_text(str(exc)+'\n'+str(getattr(exc,'stderr','')))
                summary['proposals'].append({'candidate_id':candidate_id,'status':'CANDIDATE_INVALID_PATCH','physical_evaluated':False});(out/'yield.json').write_text(json.dumps(summary,indent=2)+'\n');continue
        elif a.model_pool:
            summary['proposals'].append({'candidate_id':candidate_id,'status':'CANDIDATE_NO_PATCH','physical_evaluated':False});(out/'yield.json').write_text(json.dumps(summary,indent=2)+'\n');continue
        actual_source=(source/'textbook_sharing/layout.py').read_text()
        # Actual sampled models emitted a remove/add pair with identical text.
        # Compare this small complete editable file directly: a no-op/duplicate
        # cannot yield another label and need not repeat a minute of EDA.
        if a.model_pool and actual_source==text:
            summary['proposals'].append({'candidate_id':candidate_id,'status':'CANDIDATE_NO_SOURCE_CHANGE','physical_evaluated':False});(out/'yield.json').write_text(json.dumps(summary,indent=2)+'\n');continue
        if actual_source in seen_sources:
            summary['proposals'].append({'candidate_id':candidate_id,'status':'CANDIDATE_DUPLICATE_SOURCE','duplicate_of':seen_sources[actual_source],'physical_evaluated':False});(out/'yield.json').write_text(json.dumps(summary,indent=2)+'\n');continue
        seen_sources[actual_source]=candidate_id
        files=sorted(str(path.relative_to(source)) for path in source.rglob('*') if path.is_file() and '__pycache__' not in str(path))
        result=executor.execute(source_dir=source,source_paths=files,entrypoint='generator.py',representation='G2',configuration={'circuit':circuit,'sizing':sizing,'top_cell':name},trusted_dir=trusted,trusted_paths=trusted_paths,fidelity='pex_spice',context={'phase':'development_corpus_yield','candidate_id':candidate_id,'source_role':'development_not_training','parent_lineage':'textbook_universal_compiler_cropped','configuration_id':'anchor','pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'})
        summary['proposals'].append({'candidate_id':candidate_id,'physical_evaluated':True,**result});(out/'yield.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({'candidate_id':candidate_id,'status':result['status'],'run_directory':result['run_directory'],'assessment':(result.get('physical_result') or {}).get('assessment')}),flush=True)
    print(json.dumps({'summary':str(out/'yield.json'),'candidate_count':len(summary['proposals'])}),flush=True)


if __name__=='__main__':
    import subprocess
    main()
