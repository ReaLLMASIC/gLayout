"""Matched E1 trusted GDS evaluator; candidate source is never imported here."""
import argparse,json,subprocess,sys,threading
from pathlib import Path
from types import SimpleNamespace
import gdstk
import numpy as np
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.device_intent import compare_device_intent
from src.measurement import assess
from src.spice_validation import validate_analysis

p=argparse.ArgumentParser();p.add_argument('--gds');p.add_argument('--output');p.add_argument('--fidelity');args=p.parse_args()
out=Path(args.output);gds=Path(args.gds);meta=json.loads(Path('/trusted/meta.json').read_text());top_name=meta['top_cell']
contract=json.loads(Path('/trusted/contract.json').read_text());configuration=json.loads(Path('/configuration.json').read_text())
if configuration['parameters']!=contract['immutable_parameters']:raise ValueError('Current parameters differ from the independent frozen reference binding')
observation={k:contract[k] for k in ('task_id','configuration_id','reference_id')}
observation.update(executed=True,gds_emitted=True,checks={},corners={});artifacts={'spice':{}}
complete=False;rejected=False;analysis_complete=False

def save():
    assessment=assess(contract,observation)
    result={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,
        'point_evaluation_complete':complete or rejected,'complete_domain_evaluation':False,'analysis_complete':analysis_complete,
        'execution_integrity':'valid' if complete or rejected else 'incomplete',
        'failure_class':None if assessment['S2'] else 'candidate' if complete or rejected else 'unknown',
        'scope':'development_matched_E1_trusted_point_no_candidate_source_import'}
    (out/'validation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');return result


def magic(lines,stem):
    tcl='\n'.join(lines+['puts stdout EXTRACTION_COMPLETE','quit -noprompt','']);(out/(stem+'.tcl')).write_text(tcl)
    with (out/(stem+'.log')).open('w') as log:
        run=subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],
            input=tcl,text=True,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if run.returncode:raise RuntimeError('Magic failed; original Tcl and log retained')


library=gdstk.read_gds(gds);matches=[c for c in library.cells if c.name==top_name]
if len(matches)!=1:
    observation['interface_error']='The contract-named target must exist exactly once: '+top_name
    rejected=True;print(json.dumps(save()),flush=True);raise SystemExit(2)
top=matches[0];bbox=top.bounding_box()
if bbox is None:
    observation['interface_error']='The declared target has no physical geometry'
    rejected=True;print(json.dumps(save()),flush=True);raise SystemExit(2)
area=float((bbox[1][0]-bbox[0][0])*(bbox[1][1]-bbox[0][1])*(library.unit/1e-6)**2)
drc=check_gds(gds,out/'drc',timeout=180,top_name=top_name);(out/'drc/metadata.json').write_text(json.dumps(drc,indent=2)+'\n')
artifacts['drc']={'report':'drc/direct_drc.rpt','metadata':'drc/metadata.json'};observation['checks']['drc']=drc['is_clean']
rejected=drc['completed'] and not drc['is_clean'];save()
if not drc['completed']:raise RuntimeError('Actual-top full-bbox full-style DRC did not complete')
if rejected:print(json.dumps(save()),flush=True);raise SystemExit(2)
magic(['drc off','gds read {'+str(gds)+'}','load '+top_name,'select top cell','flatten '+top_name+'_lvs',
    'load '+top_name+'_lvs','select top cell','extract all','ext2spice lvs','ext2spice -o extracted_lvs.spice'],'lvs_extract')
with (out/'netgen.log').open('w') as log:
    process=subprocess.run(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' '+top_name+'_lvs',
        '/trusted/reference.spice '+top_name,'/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],
        stdout=log,stderr=subprocess.STDOUT,timeout=180)
lvs=netgen_lvs_report((out/'lvs.rpt').read_text() if (out/'lvs.rpt').exists() else '')
if process.returncode!=0 or not (out/'lvs.rpt').is_file():raise RuntimeError('Independent LVS tool did not complete; preserve as infrastructure/unknown')
if not lvs['is_clean']:
    observation['checks'].update(lvs=False,devices=False,ports=False,intent=False)
    artifacts['lvs']={'report':'lvs.rpt','netlist':'extracted_lvs.spice','reference':'reference.spice'}
    (out/'reference.spice').write_bytes(Path('/trusted/reference.spice').read_bytes())
    rejected=True;print(json.dumps(save()),flush=True);raise SystemExit(2)
intent=compare_device_intent((out/'extracted_lvs.spice').read_text(),Path('/trusted/reference.spice').read_text())
(out/'device_intent.json').write_text(json.dumps(intent,indent=2)+'\n')
observation['checks'].update(lvs=process.returncode==0 and lvs['is_clean'],devices=intent['per_device_dimensions_match'],
    ports=intent['ports_match'],intent=intent['is_clean'])
artifacts['lvs']={'report':'lvs.rpt','netlist':'extracted_lvs.spice','reference':'reference.spice','device_intent':'device_intent.json'}
# Keep the independent gold beside the extraction for later readonly admission.
(out/'reference.spice').write_bytes(Path('/trusted/reference.spice').read_bytes())
rejected=not all(observation['checks'].values());save()
if rejected:print(json.dumps(save()),flush=True);raise SystemExit(2)
if args.fidelity=='basic':
    complete=True;print(json.dumps(save()),flush=True);raise SystemExit(0)
cell=top_name+'_rc';pex=out/(top_name+'_pex.spice')
magic(['drc off','gds read {'+str(gds)+'}','load '+top_name,'select top cell','flatten '+cell,'load '+cell,'select top cell',
    'extract do local','extract all','feedback save extraction_feedback.tcl','ext2sim labels on','ext2sim','extresist simplify off','extresist all',
    'ext2spice lvs','ext2spice cthresh 0','ext2spice extresist on','ext2spice -o '+pex.name],'rc_extract')
inventory=rc_netlist_inventory(pex.read_text(),cell,meta['ports']);(out/'rc_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
artifacts['pex']={'netlist':pex.name,'top_cell':cell,'ports':inventory['ports']}
real=inventory['has_real_RC'];observation['pex']={'executed':True,'kind':'physical_rc','resistance_extracted':real,'capacitance_extracted':real};save()
if not real:raise RuntimeError('Positive unsimplified physical RC is not established')
if meta['bench_kind']=='mirror':
    namespace={'out':out,'contract':contract,'np':np,'math':__import__('math'),'json':json,'subprocess':subprocess,
        'validate_analysis':validate_analysis,'observation':observation,'artifacts':artifacts,'save':save,
        'net':pex,'nodes':[{'VREF':'ref','VOUT':'out','VSS':'vdd','B':'vdd'}[n.upper()] for n in inventory['ports']]}
    exec(compile(Path('/trusted/bench.py').read_text(),'/trusted/bench.py','exec'),namespace)
elif meta['bench_kind']=='independent':
    import bench
    bench.out=out
    if meta['bench_function']=='corner_run':
        bench.gold,bench.cell,bench.name=pex,cell,meta['circuit']
        bench.nodes=[meta['bindings'][port.upper()] for port in inventory['ports']]
        bench.a=SimpleNamespace(analysis_timeout=180);bench.record={'results':{}};bench.lock=threading.Lock()
        bench.save=lambda:(out/'bench_measurements.json').write_text(json.dumps(bench.record,indent=2,allow_nan=False)+'\n')
    for corner in contract['required_corners']:
        if meta['bench_function']=='measure':
            row=bench.measure(pex,cell,'post_rc',corner,inventory['ports']);prefix='post_rc/'+corner+'/'
            healthy=row.get('electrical_meaning',row.get('operating_point_valid',False))
        else:
            bench.corner_run(corner);row=bench.record['results'][corner];prefix=corner+'/'
            healthy=row.get('development_electrical_meaning',False)
        metrics={'area':{'value':area,'unit':'um2'}}
        if row['complete']:
            for key,definition in meta['metric_bindings'].items():
                value=row['metrics'][definition['source']]
                metrics[key]={'value':abs(value) if definition.get('absolute') else value,'unit':definition['unit']}
        observation['corners'][corner]={'converged':row['complete'],'operating_point_valid':bool(healthy),'metrics':metrics}
        analyses=dict(row['analyses'])
        if 'op' in contract['analysis_contracts'] and 'op' not in analyses:analyses['op']=analyses['ac']
        artifacts['spice'][corner]={'analyses':{key:{'data':prefix+key+'.dat','log':prefix+('ac' if key=='op' else key)+'.log',
            'returncode':item['returncode']} for key,item in analyses.items()}}
        save()
elif meta['bench_kind'] in ('ota','vendor_ota'):
    import ota_frozen_bench
    measure=ota_frozen_bench.run_post_rc if meta['bench_kind']=='ota' else ota_frozen_bench.run_vendor_post_rc
    returned=measure(out,pex,cell,inventory['ports'],configuration['parameters'],contract,
        kind=meta['circuit'],bench_snapshot='/trusted/original_bench.py',reference_path='/trusted/reference.spice')
    for corner,row in returned['corners'].items():
        observation['corners'][corner]={k:row[k] for k in ('converged','operating_point_valid','metrics')}
        observation['corners'][corner]['original_development_constraints_passed']=row['original_development_constraints_passed']
        observation['corners'][corner]['metrics']['original_development_predicate']={'value':int(row['original_development_constraints_passed']),'unit':'1'}
        observation['corners'][corner]['metrics']['area']={'value':area,'unit':'um2'}
        artifacts['spice'][corner]={'analyses':{name:{**entry,'data':str(Path(entry['data']).relative_to(out)),
            'log':str(Path(entry['log']).relative_to(out))} for name,entry in row['analyses'].items()}}
else:raise ValueError('No frozen original benchmark binding for this task')
analysis_complete=True
for corner in contract['required_corners']:
    reports={}
    for name,definition in contract['analysis_contracts'].items():
        artifact=artifacts['spice'][corner]['analyses'][name]
        reports[name]=validate_analysis(out/artifact['data'],out/artifact['log'],definition,artifact.get('returncode'))
    (out/(corner+'_analysis_validation.json')).write_text(json.dumps(reports,indent=2)+'\n')
    if not all(r['complete'] for r in reports.values()):analysis_complete=False
complete=analysis_complete and set(observation['corners'])==set(contract['required_corners'])
print(json.dumps(save()),flush=True)
raise SystemExit(0 if complete and assess(contract,observation)['S2'] else 2)
