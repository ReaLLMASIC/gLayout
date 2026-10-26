"""Qualify a disjoint validation OTA for three-corner UGB calibration only.

OP/AC are the declared analyses here. This does not establish transient/DC S2.
"""
import ast,json,math,os,subprocess,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,'/work')
from src.generators.validation_row_ota import build
from src.generators.validation_row_ota_reference import DEFAULT,PORTS,schematic
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.device_intent import compare_device_intent
from src.spice_validation import validate_analysis

out=Path.cwd();top='validation_row_ota'
inputs=Path(os.environ['PROBE_INPUT']) if os.environ.get('PROBE_INPUT') else None
case=json.loads((inputs/'case.json').read_text()) if inputs and (inputs/'case.json').is_file() else None
layout={'device_gap':24.,'bus_pitch':3.,'bus_width':.8}
if case:layout.update(case['layout'])
reference=out/'independent_reference.spice';reference.write_text(schematic())
for name in ['validation_row_ota.py','validation_row_ota_reference.py','terminal_access.py']:
    (out/name).write_bytes((Path('/work/src/generators')/name).read_bytes())
result={'scope':'validation_only_OP_AC_calibration_not_full_S2','source_lineage':'validation_row_bus_ota_v1',
        'split':'validation','sizing':DEFAULT,'layout':layout,
        'load_F':2e-12,'vcm_V':1.1,'supply_V':1.8,'temperature_C':27,'bias_reference_A':40e-6,
        'source_ancestry':'Separately authored; shared MOS/terminal-access primitives and disclosed high-level row/global-bus strategy with evaluation assembly',
        'measurements':{},'full_S2_established':False}


def save(): (out/'qualification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


def simulate(net,cell,stage,corner):
    folder=out/(stage+'_'+corner);folder.mkdir()
    declaration=next(line.split() for line in net.read_text().splitlines() if line.lower().startswith('.subckt '+cell.lower()+' '))
    bindings={'VDD':'vdd','GND':'0','VBIAS':'bias','VP':'vp','VN':'vn','VOUT':'out'}
    nodes=' '.join(bindings[p.upper()] for p in declaration[2:])
    prefix=['Independent validation row OTA OP/AC calibration',
        '.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner,
        '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16','.temp 27',
        '.include '+str(net),'VSUPPLY vdd 0 1.8','VBIASSUPPLY external 0 1.8','IREF external bias 40u',
        'XREPLICA bias bias 0 0 sky130_fd_pr__nfet_01v8 w=3 l=1 m=4',
        'VIN vp 0 dc 1.1 ac 1','LSERVO out vn 1G','CAC vn 0 1G','CL out 0 2p',
        'XDUT '+nodes+' '+cell,'.control','set wr_vecnames','set wr_singlescale']
    analyses={'OP':(['op','wrdata OP.dat v(out) v(bias) i(vsupply) i(vbiassupply) v(vp)'],
                    {'kind':'op','columns':6,'expected_rows':1}),
              'AC':(['ac dec 30 10 1G','wrdata AC.dat v(out)'],
                    {'kind':'ac','columns':3,'start':10.,'end':1e9,'points':241,'scale':'log'})}
    raw={};complete=True
    for name,(commands,contract) in analyses.items():
        (folder/(name+'.spice')).write_text('\n'.join(prefix+commands+['quit','.endc','.end','']))
        (folder/'.spiceinit').write_text('set ngbehavior=hsa\n')
        began=time.monotonic()
        try:
            with (folder/(name+'_console.log')).open('w') as log:
                process=subprocess.run(['ngspice','-b','-o',name+'.log',name+'.spice'],cwd=folder,
                    stdout=log,stderr=subprocess.STDOUT,timeout=90)
            code=process.returncode
        except subprocess.TimeoutExpired:code=None
        integrity=validate_analysis(folder/(name+'.dat'),folder/(name+'.log'),contract,code)
        raw[name]={'returncode':code,'wall_seconds':time.monotonic()-began,'integrity':integrity}
        complete=complete and integrity['complete']
    row={'complete':complete,'analyses':raw,'metrics':None}
    if complete:
        op=np.loadtxt(folder/'OP.dat',skiprows=1,ndmin=2)[0]
        ac=np.loadtxt(folder/'AC.dat',skiprows=1,ndmin=2);frequency=ac[:,0];response=ac[:,1]+1j*ac[:,2]
        db=20*np.log10(np.abs(response));phase=np.unwrap(np.angle(response))*180/np.pi
        crossing=np.where((db[:-1]>=0)&(db[1:]<0))[0]
        ugb=margin=None
        if len(crossing):
            index=int(crossing[0]);fraction=float(-db[index]/(db[index+1]-db[index]))
            ugb=float(10**(np.log10(frequency[index])+fraction*np.log10(frequency[index+1]/frequency[index])))
            margin=float(180+phase[index]+fraction*(phase[index+1]-phase[index]))
        row['metrics']={'gain_10Hz_dB':float(db[0]),'positive_low_frequency_gain':bool(ac[0,1]>0),
            'ugb_Hz':ugb,'phase_margin_deg':margin,'output_V':float(op[1]),'bias_V':float(op[2]),
            'DUT_power_W':float(-1.8*op[3]),'external_bias_power_W':float(-1.8*op[4])}
        row['calibration_electrically_valid']=bool(ac[0,1]>0 and ugb and margin and margin>=60
            and abs(op[1]-1.1)<.05 and .3<op[2]<1.3 and -1.8*op[3]>0)
    else:row['calibration_electrically_valid']=False
    (folder/'measurement.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
    result['measurements'][stage+'_'+corner]=row;save();return row


adopt=(Path('/work')/Path(case['reuse_schematic_run']).relative_to('/srv/code-behind-layout')) if case else inputs
if adopt:
    prior=json.loads((adopt/'qualification.json').read_text())
    if (adopt/'independent_reference.spice').read_bytes()!=reference.read_bytes():
        raise ValueError('Adopted schematic differs from the new independently rendered reference')
    if any(prior[key]!=result[key] for key in ['scope','sizing','load_F','vcm_V','supply_V','temperature_C','bias_reference_A']):
        raise ValueError('Adopted schematic bench settings differ')
    def function_source(path):
        text=path.read_text();tree=ast.parse(text)
        node=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='simulate')
        return ast.get_source_segment(text,node)
    if function_source(adopt/Path(__file__).name)!=function_source(Path(__file__)):
        raise ValueError('Adopted schematic simulation and measurement body differs')
    for corner in ['tt','ss','ff']:
        row=prior['measurements']['schematic_'+corner]
        if not row['complete'] or not row['calibration_electrically_valid']:
            raise ValueError('Cannot adopt an incomplete or infeasible schematic point')
        result['measurements']['schematic_'+corner]=row
    result['adopted_schematic_evidence']={'original_run':str(adopt),'new_schematic_simulations':0,
        'reason':'Exact reference, bench settings and simulate/measurement body unchanged; only layout deep-well construction changed',
        'original_resource_cost_is_not_charged_twice':True}
    save()
else:
    for corner in ['tt','ss','ff']:
        if not simulate(reference,top,'schematic',corner)['calibration_electrically_valid']:
            result['status']='SCHEMATIC_INCOMPLETE_OR_INFEASIBLE';save();raise SystemExit(2)
gds=build(out,**layout)
result['DRC']=check_gds(gds,out/'drc_full',timeout=120);save()
if not result['DRC']['completed'] or not result['DRC']['is_clean']:
    result['status']='PHYSICAL_REJECTED_OR_INCOMPLETE';save();raise SystemExit(2)
tcl='\n'.join(['drc off','gds read {'+str(gds)+'}','load '+top,'select top cell','flatten '+top+'_lvs',
    'load '+top+'_lvs','select top cell','extract all','ext2spice lvs','ext2spice -o extracted_lvs.spice','quit -noprompt',''])
(out/'lvs_extract.tcl').write_text(tcl)
with (out/'lvs_extract.log').open('w') as log:
    process=subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],
        input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
if process.returncode:raise RuntimeError('Validation Magic extraction failed')
with (out/'netgen.log').open('w') as log:
    process=subprocess.run(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' '+top+'_lvs',str(reference)+' '+top,
        '/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],stdout=log,stderr=subprocess.STDOUT,timeout=120)
result['LVS']=netgen_lvs_report((out/'lvs.rpt').read_text())
result['device_intent']=compare_device_intent((out/'extracted_lvs.spice').read_text(),reference.read_text());save()
if process.returncode or not result['LVS']['is_clean'] or not result['device_intent']['is_clean']:
    result['status']='INDEPENDENT_CONNECTIVITY_OR_INTENT_REJECTED';save();raise SystemExit(2)
with (out/'pex.log').open('w') as log:
    process=subprocess.run(['bash','/work/vendor/glayout/src/glayout/verification/run_pex.sh',str(gds),top],
        stdout=log,stderr=subprocess.STDOUT,timeout=180)
net=out/(top+'_pex.spice')
result['PEX_returncode']=process.returncode
result['RC']=rc_netlist_inventory(net.read_text(),top+'_rc',PORTS) if net.exists() else None;save()
if process.returncode or not result['RC'] or not result['RC']['has_real_RC']:
    result['status']='FULL_RC_NOT_ESTABLISHED';save();raise SystemExit(2)
for corner in ['tt','ss','ff']:simulate(net,top+'_rc','postlayout',corner)
result['status']='COMPLETE_VALIDATION_AC_CALIBRATION' if all(r['calibration_electrically_valid'] for r in result['measurements'].values()) else 'INCOMPLETE_OR_ELECTRICALLY_INFEASIBLE'
save();print(json.dumps(result,indent=2),flush=True)
raise SystemExit(0 if result['status']=='COMPLETE_VALIDATION_AC_CALIBRATION' else 2)
