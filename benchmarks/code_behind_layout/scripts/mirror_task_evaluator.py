"""Trusted parametric mirror baseline; same steady-DC bench as the characterized mirror.
Read only the per-point frozen contract and independent reference; never candidate reports.
"""
import argparse,json,math,pathlib,subprocess
import gdstk,numpy as np
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=pathlib.Path(a.output);gds=pathlib.Path(a.gds);contract=json.loads(pathlib.Path('/trusted/contract.json').read_text())
top,=gdstk.read_gds(gds).top_level()
if top.name!='mirror4':raise ValueError('Candidate top must be mirror4')
observation={k:contract[k] for k in ['task_id','configuration_id','reference_id']}
observation.update(executed=True,gds_emitted=True,checks={},corners={})
artifacts={'spice':{}}
def save():
 assessment=assess(contract,observation)
 complete=all(observation['corners'].get(c,{}).get('converged') is True for c in contract['required_corners'])
 rejected=(globals().get('drc',{}).get('completed') is True and observation['checks'].get('drc') is False) or ('lvs' in artifacts and (out/'lvs.rpt').is_file() and observation['checks'].get('lvs') is False)
 result={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,'complete_domain_evaluation':False,'point_evaluation_complete':complete or rejected,'analysis_complete':complete,'execution_integrity':'valid' if complete or rejected else 'incomplete','failure_class':None if assessment['S2'] else 'candidate' if complete or rejected else 'unknown','scope':'development_independent_trusted_mirror_point'}
 (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n');return result
def magic(tcl,stem):
 (out/(stem+'.tcl')).write_text(tcl)
 with (out/(stem+'.log')).open('w') as log:
  result=subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
 if result.returncode:raise RuntimeError('Magic failed')
drc=check_gds(gds,out/'drc',timeout=120)
(out/'drc/metadata.json').write_text(json.dumps(drc,indent=2)+'\n')
artifacts['drc']={'report':'drc/direct_drc.rpt','metadata':'drc/metadata.json'}
observation['checks']['drc']=drc['is_clean'];save()
magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load mirror4','select top cell','flatten mirror4_lvs','load mirror4_lvs','select top cell','extract all','ext2spice lvs','ext2spice -o extracted_lvs.spice','puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'lvs_extract')
with (out/'netgen.log').open('w') as log:
 result=subprocess.run(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' mirror4_lvs','/trusted/reference.spice mirror4','/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],stdout=log,stderr=subprocess.STDOUT,timeout=120)
lvs=netgen_lvs_report((out/'lvs.rpt').read_text() if (out/'lvs.rpt').exists() else '')
clean=lvs['is_clean'] and result.returncode==0
for key in ['lvs','devices','ports','intent']:observation['checks'][key]=clean
artifacts['lvs']={'report':'lvs.rpt'};save()
if not drc['completed']:raise RuntimeError('DRC did not complete')
if not drc['is_clean'] or not clean:raise SystemExit(2)
if a.fidelity=='pex_spice':
 magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load mirror4','select top cell','flatten mirror4_rc','load mirror4_rc','select top cell','extract do local','extract all','feedback save extraction_feedback.tcl','ext2sim labels on','ext2sim','extresist simplify off','extresist all','ext2spice lvs','ext2spice cthresh 0','ext2spice extresist on','ext2spice -o mirror4_pex.spice','puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'rc_extract')
 net=out/'mirror4_pex.spice';text=net.read_text();ports=['VREF','VOUT','VSS','B']
 inventory=rc_netlist_inventory(text,'mirror4_rc',ports)
 (out/'rc_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
 artifacts['pex']={'netlist':'mirror4_pex.spice','top_cell':'mirror4_rc','ports':ports}
 observation['pex']={'executed':True,'kind':'physical_rc','resistance_extracted':inventory['has_real_RC'],'capacitance_extracted':inventory['has_real_RC']};save()
 if not inventory['has_real_RC']:raise SystemExit(2)
 declaration=next(line.split() for line in text.splitlines() if line.lower().startswith('.subckt mirror4_rc '))
 bindings={'VREF':'ref','VOUT':'out','VSS':'vdd','B':'vdd'};nodes=[bindings[n.upper()] for n in declaration[2:]]
 for corner in contract['required_corners']:
  work=out/corner;work.mkdir();(work/'.spiceinit').write_text('set ngbehavior=hsa\n')
  common=['Mirror composition development DC qualification','.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner,'.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16','.temp 27','.include '+str(net),'VSUPPLY vdd 0 1.8','VOUT out 0 .9','IREF ref 0 10u','XDUT '+' '.join(nodes)+' mirror4_rc','.save v(ref) v(out) i(vout) i(vsupply)','.control','set wr_vecnames','set wr_singlescale']
  analyses={'op':['op','wrdata op.dat v(ref) v(out) i(vout) i(vsupply)'],'compliance':['dc VOUT .05 1.75 .025','wrdata compliance.dat v(ref) v(out) i(vout) i(vsupply)'],'input_gain':['dc IREF 2u 20u 2u','wrdata input_gain.dat v(ref) v(out) i(vout) i(vsupply)']}
  artifacts['spice'][corner]={'analyses':{}};validations={}
  for name,commands in analyses.items():
   (work/(name+'.spice')).write_text('\n'.join(common+commands+['quit','.endc','.end','']))
   timed_out=False
   with (work/(name+'_console.log')).open('w') as log:
    try:sim=subprocess.run(['ngspice','-b','-o',name+'.log',name+'.spice'],cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=90);returncode=sim.returncode
    except subprocess.TimeoutExpired:returncode=None;timed_out=True
   artifacts['spice'][corner]['analyses'][name]={'data':corner+'/'+name+'.dat','log':corner+'/'+name+'.log','returncode':returncode,'timeout':timed_out}
   validations[name]=validate_analysis(work/(name+'.dat'),work/(name+'.log'),contract['analysis_contracts'][name],returncode)
  (work/'analysis_validation.json').write_text(json.dumps(validations,indent=2)+'\n')
  complete=all(v['complete'] for v in validations.values());metrics={};healthy=False
  if complete:
   op=np.loadtxt(work/'op.dat',skiprows=1,ndmin=2)[0];curve=np.loadtxt(work/'compliance.dat',skiprows=1,ndmin=2);gain=np.loadtxt(work/'input_gain.dat',skiprows=1,ndmin=2)
   index=int(np.argmin(np.abs(curve[:,2]-.9)));current=curve[:,3];conductance=float(np.gradient(current,curve[:,2])[index]);ratio=float(current[index]/1e-5)
   healthy=0<float(op[1])<1.8 and abs(float(op[2])-.9)<1e-6 and float(current[index])>0
   metrics={'absolute_current_error':{'value':abs(ratio-1),'unit':'1'},'relative_current_error':{'value':ratio-1,'unit':'1'},'output_resistance':{'value':1/abs(conductance) if conductance else None,'unit':'ohm'},'incremental_input_gain':{'value':float(np.gradient(gain[:,3],gain[:,0])[4]),'unit':'1'}}
  observation['corners'][corner]={'converged':complete,'operating_point_valid':healthy,'metrics':metrics};save()
result=save();print(json.dumps(result),flush=True)
raise SystemExit(0 if result['assessment']['S2'] else 2)
