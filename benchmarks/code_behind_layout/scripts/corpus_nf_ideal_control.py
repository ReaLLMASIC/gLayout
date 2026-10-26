"""Replay every declared nf point's retained bench using its independent ideal N."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

root=Path('/work');out=Path.cwd();sys.path.insert(0,str(root))
from src.spice_validation import validate_analysis
from src.corpus_metrics import mirror_dc_metrics

points=json.loads((Path(os.environ['PROBE_INPUT'])/'points.json').read_text())
result={'scope':'development_schematic_control_not_training_or_relabelled_physics','model_requests':0,
    'declared_complete_nine_point_domain_preserved':True,'same_N_counterfactual_as_postlayout':all(not p.get('independent_N_file') for p in points),
    'changed_only':['independent_N_include','XDUT_terminal_order_and_subcircuit'],
    'unchanged':['bias','loads','supply','temperature','process_corners','analysis_commands','tolerances','application_specs'],
    'points':[]}
for point in points:
    post=Path(point['postlayout_baseline']);work=out/point['configuration_id'];work.mkdir()
    gold=root/point['independent_N_file'] if point.get('independent_N_file') else post/'target.spice'
    target=work/'target.spice';shutil.copyfile(gold,target)
    original=(root/point['reference_file']).read_text()
    if target.read_text()!=original:raise ValueError('Retained postlayout independent N differs from predeclared reference')
    declaration=next(line.split() for line in original.splitlines() if line.lower().startswith('.subckt corpus_c01 '))
    binding={'VSS':'0','IB1':'bias','IOUT1':'out'}
    invocation='XDUT '+' '.join(binding[p.upper()] for p in declaration[2:])+' '+declaration[1]
    contract=json.loads((root/point['contract_file']).read_text())['analysis_contracts']
    raw=json.loads((post/'physical.json').read_text());corners={}
    for corner in ['tt','ss','ff']:
        bench=work/corner;bench.mkdir();(bench/'.spiceinit').write_text('set ngbehavior=hsa\n');analyses={}
        for analysis in ['ac','tran','dc']:
            retained=(post/corner/(analysis+'.spice')).read_text()
            source,n=re.subn(r'(?m)^\.include .+$','.include '+str(target),retained)
            source,m=re.subn(r'(?m)^XDUT .+$',invocation,source)
            if n!=1 or m!=1:raise ValueError('Expected exactly one immutable DUT include and invocation')
            (bench/(analysis+'.spice')).write_text(source)
            with (bench/(analysis+'_console.log')).open('w') as log:
                ran=subprocess.run(['ngspice','-b','-o',analysis+'.log',analysis+'.spice'],cwd=bench,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            analyses[analysis]=validate_analysis(bench/(analysis+'.dat'),bench/(analysis+'.log'),contract[analysis],ran.returncode)
            if analysis=='ac':analyses['op']=validate_analysis(bench/'op.dat',bench/'ac.log',contract['op'],ran.returncode)
        complete=all(row['complete'] for row in analyses.values());metrics=mirror_dc_metrics(bench/'dc.dat') if complete else {}
        band=[v['relative_error'] for v in metrics.get('dc_sweep_relative_errors',[]) if .7-1e-7<=v['voltage_V']<=1+1e-7]
        passed=bool(complete and len(band)==4 and metrics.get('nominal_current_relative_error',1) <=.05 and metrics.get('output_resistance_ohm',0)>=300000 and max(band)<=.05)
        corners[corner]={'analyses':analyses,'complete':complete,'ideal_application_constraints_pass':passed,'ideal_metrics':metrics,
            'postlayout_metrics':None if point.get('independent_N_file') else raw.get('corners',{}).get(corner,{}).get('metrics',{})}
    result['points'].append({**point,'corners':corners,'all_analyses_complete':all(c['complete'] for c in corners.values()),
        'ideal_application_constraints_pass':all(c['ideal_application_constraints_pass'] for c in corners.values())})
    (out/'ideal_control.json').write_text(json.dumps(result,indent=2)+'\n')
result.update(status='COMPLETED_DECLARED_NINE_POINT_IDEAL_CONTROLS',all_nine_ideal_qualified=len(result['points'])==9 and all(p['ideal_application_constraints_pass'] for p in result['points']))
(out/'ideal_control.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'points':len(result['points']),'qualified':sum(p['ideal_application_constraints_pass'] for p in result['points'])}),flush=True)
