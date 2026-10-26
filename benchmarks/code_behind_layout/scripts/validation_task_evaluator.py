"""Trusted development adapter for the independent validation NMOS mirror."""
import argparse,json,pathlib,subprocess
import gdstk,numpy as np
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis
from src.measurement import assess

p=argparse.ArgumentParser();p.add_argument('--gds');p.add_argument('--output');p.add_argument('--fidelity');a=p.parse_args()
out=pathlib.Path(a.output);gds=pathlib.Path(a.gds)
contract=json.loads(pathlib.Path('/trusted/contract.json').read_text())
observation={k:contract[k] for k in ('task_id','configuration_id','reference_id')}
observation.update(executed=True,gds_emitted=True,checks={},corners={})
artifacts={'spice':{}};validations={};interface_error=None
def save():
    assessment=assess(contract,observation)
    complete=all(observation['corners'].get(c,{}).get('converged') is True for c in contract['required_corners'])
    rejected=globals().get('drc',{}).get('completed') is True and observation['checks'].get('drc') is False
    rejected=rejected or ('lvs' in artifacts and observation['checks'].get('lvs') is False)
    result={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,
        'analysis_validation':validations,'point_evaluation_complete':complete or rejected,
        'complete_domain_evaluation':False,'execution_integrity':'valid' if complete or rejected else 'incomplete',
        'failure_class':None if assessment['S2'] else 'candidate' if complete or rejected else 'unknown',
        'scope':'development_validation_mirror_budget_calibration','interface_error':interface_error}
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n');return result
def magic(tcl,stem):
    (out/(stem+'.tcl')).write_text(tcl)
    with (out/(stem+'.log')).open('w') as log:
        result=subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],
            input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
    if result.returncode:raise RuntimeError('Magic failed')
try:drc=check_gds(gds,out/'drc',timeout=120,top_name='validation_mirror')
except ValueError as exc:
    interface_error={'type':'contract_target_selection','message':str(exc)}
    save();raise SystemExit(3)
(out/'drc/metadata.json').write_text(json.dumps(drc,indent=2)+'\n')
artifacts['drc']={'report':'drc/direct_drc.rpt','metadata':'drc/metadata.json'}
observation['checks']['drc']=drc['is_clean'];save()
magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load validation_mirror','select top cell',
    'flatten validation_mirror_lvs','load validation_mirror_lvs','select top cell','extract all',
    'ext2spice lvs','ext2spice -o extracted_lvs.spice','puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'lvs_extract')
with (out/'netgen.log').open('w') as log:
    result=subprocess.run(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' validation_mirror_lvs',
        '/trusted/reference.spice validation_mirror','/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],
        stdout=log,stderr=subprocess.STDOUT,timeout=120)
lvs=netgen_lvs_report((out/'lvs.rpt').read_text() if (out/'lvs.rpt').exists() else '')
clean=lvs['is_clean'] and result.returncode==0
for key in ('lvs','devices','ports','intent'):observation['checks'][key]=clean
artifacts['lvs']={'report':'lvs.rpt'};save()
if not drc['completed']:raise RuntimeError('DRC did not complete')
if not drc['is_clean'] or not clean:raise SystemExit(2)
if a.fidelity=='pex_spice':
    magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load validation_mirror','select top cell',
        'flatten validation_mirror_rc','load validation_mirror_rc','select top cell','extract do local','extract all',
        'feedback save extraction_feedback.tcl','ext2sim labels on','ext2sim','extresist simplify off','extresist all',
        'ext2spice lvs','ext2spice cthresh 0','ext2spice extresist on','ext2spice -o validation_mirror_pex.spice',
        'puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'rc_extract')
    net=out/'validation_mirror_pex.spice';text=net.read_text();ports=['REF','OUT','GND']
    inventory=rc_netlist_inventory(text,'validation_mirror_rc',ports)
    (out/'rc_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    artifacts['pex']={'netlist':net.name,'top_cell':'validation_mirror_rc','ports':ports}
    observation['pex']={'executed':True,'kind':'physical_rc','resistance_extracted':inventory['has_real_RC'],
        'capacitance_extracted':inventory['has_real_RC']};save()
    if not inventory['has_real_RC']:raise SystemExit(2)
    binding={'REF':'ref','OUT':'out','GND':'0'};nodes=[binding[name.upper()] for name in inventory['ports']]
    for corner in contract['required_corners']:
        work=out/corner;work.mkdir();(work/'.spiceinit').write_text('set ngbehavior=hsa\n')
        deck=['Independent validation current mirror post-RC qualification',
            '.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner,
            '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16','.temp 27',
            '.include '+str(net),'VSUPPLY vdd 0 1.8','IREF vdd ref 10u','VOUT out 0 .9',
            'XDUT '+' '.join(nodes)+' validation_mirror_rc','.save v(ref) v(out) i(vout)',
            '.control','op','set wr_vecnames','set wr_singlescale','wrdata op.dat v(ref) v(out) i(vout)',
            'dc VOUT .1 1.7 .1','wrdata dc.dat v(ref) v(out) i(vout)','quit','.endc','.end','']
        (work/'dc.spice').write_text('\n'.join(deck));timed_out=False
        with (work/'console.log').open('w') as log:
            try:r=subprocess.run(['ngspice','-b','-o','ngspice.log','dc.spice'],cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120);rc=r.returncode
            except subprocess.TimeoutExpired:rc=None;timed_out=True
        artifacts['spice'][corner]={'analyses':{name:{'data':corner+'/'+name+'.dat','log':corner+'/ngspice.log',
            'returncode':rc,'timeout':timed_out} for name in ('op','dc')}}
        validations[corner]={name:validate_analysis(work/(name+'.dat'),work/'ngspice.log',spec,rc)
            for name,spec in contract['analysis_contracts'].items()}
        complete=all(v['complete'] for v in validations[corner].values());metrics={};healthy=False
        if complete:
            op=np.loadtxt(work/'op.dat',skiprows=1,ndmin=2)[0];data=np.loadtxt(work/'dc.dat',skiprows=1,ndmin=2)
            index=int(np.argmin(abs(data[:,2]-.9)));current=-data[:,3]
            conductance=float(np.gradient(current,data[:,2])[index])
            healthy=bool(0<op[1]<1.8 and current[index]>0 and abs(data[index,2]-.9)<1e-6)
            metrics={'absolute_current_error':{'value':float(abs(current[index]/1e-5-1)),'unit':'1'},
                'output_resistance':{'value':1/conductance if conductance>0 else None,'unit':'ohm'}}
        observation['corners'][corner]={'converged':complete,'operating_point_valid':healthy,'metrics':metrics};save()
result=save();print(json.dumps(result),flush=True)
raise SystemExit(0 if result['assessment']['S2'] else 2)
