"""Applicable current-output differential-pair and TG characterization benches.

Physical extraction code follows scripts/corpus_yield_pilot.py's retained
DRC/LVS/PEX procedure. No policy or evaluation-target generator is imported.
"""
import json
from pathlib import Path
import subprocess


def dump(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def benches(cid,sizes,name,netlist,ports,corner,solver='trap',independent_transient_inputs=False):
    common=['Component train-domain development qualification',
        '.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner,
        '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16','.temp 27','.include '+str(netlist),'VSUPPLY vdd 0 1.8']
    if solver=='gear2':common.insert(3,'.option method=gear maxord=2')
    elif solver!='trap':raise ValueError('Unknown explicitly declared integration method')
    binding=({'VSS':'0','IIN1':'bias','IOUT1':'out'} if cid=='C02' else
             {'VDD':'vdd','VSS':'0','VIN1':'vinp','VIN2':'vinn','VOUT1':'outp','VOUT2':'outn','VB1':'bias','IB1':'tail'} if cid=='C07' else
             {'VDD':'vdd','VSS':'0','VIN1':'vin','VOUT1':'out','VC1':'ctrl','VC2':'ctrlb'})
    common+=['XDUT '+' '.join(binding[port] for port in ports)+' '+name]
    if cid=='C02':
        common+=['IBIAS vdd bias 5u']
        bodies={'ac':['VOUT out 0 1.5 ac 1','.control','op','wrdata op.dat v(bias) i(vout) i(vsupply)',
            'ac dec 20 10 1G','wrdata ac.dat real(i(vout)) imag(i(vout))'],
            'tran':['VOUT out 0 pulse(1.475 1.525 1u 10n 10n 1u 2u)','.control','tran 5n 4u','wrdata tran.dat v(out) i(vout)'],
            'dc':['VOUT out 0 1.5','.control','dc VOUT 0 1.8 .05','wrdata dc.dat v(out) i(vout)']}
    elif cid=='C07':
        ref=sizes['M3']
        common+=['VBIASSUPPLY vddbias 0 1.8','IBIAS bias 0 20u',
            f"XBIAS bias bias vddbias vddbias sky130_fd_pr__pfet_01v8 w={ref['w']/ref['nf']:g} l={ref['l']:g} m={ref['nf']}",
            'ITAIL tail 0 40u','VCM vcm 0 .9','EINP vinp vcm vd 0 .5','EINN vinn vcm vd 0 -.5',
            'VCL1 outp 0 .9','VCL2 outn 0 .9','.nodeset v(tail)=.3 v(bias)=1.2']
        bodies={'ac':['VD vd 0 0 ac 1','.control','op','wrdata op.dat v(tail) v(bias) i(vsupply) i(vcl1) i(vcl2)',
            'ac dec 20 10 1G','let gd = i(vcl2)-i(vcl1)','wrdata ac.dat real(gd) imag(gd)'],
            'tran':['VD vd 0 pulse(-.01 .01 1u 10n 10n 1u 2u)','.control','tran 5n 4u','let diffcurrent=i(vcl2)-i(vcl1)','wrdata tran.dat v(vd) diffcurrent'],
            'dc':['VD vd 0 0','.control','dc VD -.1 .1 .005','wrdata dc.dat v(vd) v(tail) i(vcl1) i(vcl2)']}
    elif cid=='TRAIN_TG01':
        load=['VCTRL ctrl 0 1.8','VCTRLB ctrlb 0 0','RLOAD out 0 100k','CLOAD out 0 1p']
        bodies={'ac':load+['VIN vin 0 .9 ac 1','.control','op','wrdata op.dat v(out) i(vin) i(vsupply)','ac dec 20 10 1G','wrdata ac.dat real(v(out)) imag(v(out))'],
            'tran':load+['VIN vin 0 pulse(.2 1.6 1u 10n 10n 1u 2u)','.control','tran 5n 4u','wrdata tran.dat v(vin) v(out)'],
            'dc':load+['VIN vin 0 .9','.control','dc VIN .1 1.7 .1','wrdata dc.dat v(vin) v(out)'],
            'off':['VCTRL ctrl 0 0','VCTRLB ctrlb 0 1.8','VOUT_FORCE out 0 .9','VIN vin 0 .9','.control','dc VIN .1 1.7 .1','wrdata off.dat v(vin) i(vout_force)']}
    else:raise ValueError('Unknown declared component graph')
    if independent_transient_inputs:
        if cid!='C07':raise ValueError('Equivalent independent input drive is defined only for C07')
        # Replace the two ideal E-source constraints only during transient.
        # Both port waveforms are algebraically identical to VCM +/- VD/2.
        bodies['tran']=['VINP vinp 0 pulse(.895 .905 1u 10n 10n 1u 2u)',
            'VINN vinn 0 pulse(.905 .895 1u 10n 10n 1u 2u)']+bodies['tran']
    return common,bodies


def simulate(output,cid,sizes,name,netlist,ports,contracts,solver='trap',independent_transient_inputs=False):
    import numpy as np
    from src.spice_validation import validate_analysis
    from src.corpus_metrics import frequency_3db
    result={}
    for corner in ['tt','ss','ff']:
        work=output/corner;work.mkdir();(work/'.spiceinit').write_text('set ngbehavior=hsa\n')
        common,bodies=benches(cid,sizes,name,netlist,ports,corner,solver,independent_transient_inputs);analyses={}
        for analysis,body in bodies.items():
            index=body.index('.control');body=body[:index+1]+['set wr_vecnames','set wr_singlescale']+body[index+1:]+['quit','.endc','.end','']
            analysis_common=([line for line in common if not line.startswith(('EINP ','EINN '))] if independent_transient_inputs and analysis=='tran' else common)
            (work/(analysis+'.spice')).write_text('\n'.join(analysis_common+body))
            with (work/(analysis+'_console.log')).open('w') as log:
                ran=subprocess.run(['ngspice','-b','-o',analysis+'.log',analysis+'.spice'],cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            analyses[analysis]={**validate_analysis(work/(analysis+'.dat'),work/(analysis+'.log'),contracts[analysis],ran.returncode),'returncode':ran.returncode}
            if analysis=='ac':analyses['op']={**validate_analysis(work/'op.dat',work/'ac.log',contracts['op'],ran.returncode),'returncode':ran.returncode}
        complete=all(row['complete'] for row in analyses.values());metrics={};op_valid=False
        if complete:
            data=lambda label:np.loadtxt(work/(label+'.dat'),skiprows=1,ndmin=2)
            op=data('op')[0];ac=data('ac');dc=data('dc');tran=data('tran')
            windows=[(tran[:,0]>=a)&(tran[:,0]<=b) for a,b in [(1.8e-6,1.99e-6),(2.8e-6,2.99e-6)]]
            if cid=='C02':
                current=-dc[:,2];nominal=int(np.argmin(abs(dc[:,0]-1.5)))
                errors=abs(current/5e-6-1);good=errors<=.05;lower=upper=nominal
                if good[nominal]:
                    while lower>0 and good[lower-1]:lower-=1
                    while upper+1<len(good) and good[upper+1]:upper+=1
                slope=float((current[nominal+1]-current[nominal-1])/(dc[nominal+1,0]-dc[nominal-1,0]))
                settled=np.interp(tran[:,1],dc[:,0],current)
                region=(dc[:,0]>=1.3-1e-9)&(dc[:,0]<=1.7+1e-9)
                metrics={'input_bias_V':float(op[1]),'nominal_current_A':float(current[nominal]),
                    'nominal_current_relative_error':float(errors[nominal]),
                    'output_resistance_ohm':1/slope if slope>0 else None,
                    'output_conductance_10Hz_S':float(-ac[0,1]),
                    'compliance_5percent_sampled_low_V':float(dc[lower,0]) if good[nominal] else None,
                    'compliance_5percent_sampled_high_V':float(dc[upper,0]) if good[nominal] else None,
                    'max_current_relative_error_1p3_to_1p7V':float(np.max(errors[region])),
                    'settled_current_error_vs_DC_A':max(float(np.max(abs(-tran[mask,2]-settled[mask]))) for mask in windows),
                    'external_reference_supply_power_W':float(-1.8*op[3]),
                    'DUT_input_port_power_W':float(op[1]*5e-6),'DUT_output_port_power_W':float(-1.5*op[2])}
                op_valid=0<op[1]<1.8 and current[nominal]>0 and slope>0
            elif cid=='C07':
                gm=float(ac[0,1]);current=dc[:,4]-dc[:,3];zero=int(np.argmin(abs(dc[:,0])));cross=np.flatnonzero((current[:-1]<=0)&(current[1:]>=0))
                offset=float(np.interp(0,current,dc[:,0])) if len(cross) else None
                expected=np.interp(tran[:,1],dc[:,0],current)
                metrics={'tail_bias_V':float(op[1]),'PMOS_bias_V':float(op[2]),'main_supply_power_W':float(-1.8*op[3]),
                    'external_replica_supply_power_W':36e-6,'output_clamp_port_work_W':float(-.9*(op[4]+op[5])),
                    'differential_transconductance_S':gm,'zero_input_differential_current_A':float(current[zero]),'systematic_input_offset_V':offset,
                    'differential_current_span_A':float(current[-1]-current[0]),
                    'settled_current_error_vs_DC_A':max(float(np.max(abs(tran[mask,2]-expected[mask]))) for mask in windows),
                    'gm_at_1GHz_fraction':float(abs(ac[-1,1]+1j*ac[-1,2])/abs(ac[0,1]+1j*ac[0,2]))}
                op_valid=0<op[1]<.9 and 0<op[2]<1.8 and gm>0 and offset is not None and np.all((dc[:,2]>0)&(dc[:,2]<.9))
            else:
                ron=(dc[:,1]-dc[:,2])/(dc[:,2]/100000);off=data('off')
                metrics={'output_bias_V':float(op[1]),'signal_source_power_W':float(-.9*op[2]),'main_well_supply_power_W':float(-1.8*op[3]),
                    'external_RLOAD_power_W':float(op[1]**2/100000),'on_channel_dissipation_W':float((.9-op[1])*op[1]/100000),
                    'on_gain_10Hz':float(ac[0,1]),'on_f3db_Hz':frequency_3db(work/'ac.dat'),
                    'max_on_resistance_ohm':float(np.max(ron)),'min_on_resistance_ohm':float(np.min(ron)),
                    'max_on_DC_tracking_error_V':float(np.max(abs(dc[:,1]-dc[:,2]))),'max_off_leakage_A':float(np.max(abs(off[:,2]))),
                    'settled_signal_tracking_error_V':max(float(np.max(abs(tran[mask,1]-tran[mask,2]))) for mask in windows)}
                op_valid=0<op[1]<.9 and np.all(ron>0) and metrics['on_gain_10Hz']>.5 and metrics['on_f3db_Hz'] is not None
        result[corner]={'complete':complete,'operating_point_valid':bool(op_valid),'analyses':analyses,'metrics':metrics}
        dump(output/'spice_progress.json',result)
    return result


def evaluate(output,circuit,sizes,name,gds,gold,contract,prelayout=False,solver='trap',independent_transient_inputs=False,pex_script=None):
    """Run independent schematic controls or actual full DRC/LVS/positive-RC flow."""
    output.mkdir(parents=True,exist_ok=True);record={'scope':'development_component_train_qualification_not_formal',
        'circuit_id':circuit.circuit_id,'configuration_id':contract['configuration_id'],'prelayout':prelayout,'formal_training_rows':0,
        'integration_method':solver,'tight_tolerances_unchanged':True,'independent_transient_inputs':independent_transient_inputs}
    netlist=gold;sim_name=name
    if not prelayout:
        import gdstk
        from src.physical_drc import check_gds
        from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
        from src.device_intent import compare_device_intent
        top,=gdstk.read_gds(gds).top_level();record['area_um2']=float((top.bounding_box()[1][0]-top.bounding_box()[0][0])*(top.bounding_box()[1][1]-top.bounding_box()[0][1]))
        record['DRC']=check_gds(gds,output/'drc_full');dump(output/'physical.json',record)
        script='\n'.join(['gds read {'+str(gds)+'}','load '+name,'select top cell','extract all','ext2spice lvs','ext2spice -o layout_lvs.spice','quit -noprompt',''])
        (output/'lvs_extract.tcl').write_text(script)
        with (output/'lvs_magic.log').open('w') as log:
            subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],input=script,text=True,cwd=output,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        with (output/'netgen.log').open('w') as log:
            subprocess.run(['netgen','-batch','lvs',str(output/'layout_lvs.spice')+' '+name,str(gold)+' '+name,
                '/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(output/'netgen_lvs.rpt')],cwd=output,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        record['LVS']=netgen_lvs_report((output/'netgen_lvs.rpt').read_text());dump(output/'physical.json',record)
        if not(record['DRC']['is_clean'] and record['LVS']['is_clean']):return record
        record['DeviceIntent']=compare_device_intent((output/'layout_lvs.spice').read_text(),gold.read_text())
        dump(output/'physical.json',record)
        if not record['DeviceIntent']['is_clean']:return record
        with (output/'pex.log').open('w') as log:
            ran=subprocess.run(['bash',str(pex_script or '/work/vendor/glayout/src/glayout/verification/run_pex.sh'),str(gds),name],cwd=output,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        netlist=output/(name+'_pex.spice');sim_name=name+'_rc';record['pex_returncode']=ran.returncode
        record['RC']=rc_netlist_inventory(netlist.read_text(),sim_name,circuit.ports);dump(output/'physical.json',record)
        if ran.returncode or not record['RC']['has_real_RC']:return record
    record['corners']=simulate(output,circuit.circuit_id,sizes,sim_name,netlist,circuit.ports,contract['analysis_contracts'],solver,independent_transient_inputs)
    record['all_analyses_complete']=all(row['complete'] for row in record['corners'].values())
    record['all_operating_points_valid']=all(row['operating_point_valid'] for row in record['corners'].values())
    record['full_physical_analysis_complete']=not prelayout and record['all_analyses_complete']
    dump(output/('prelayout.json' if prelayout else 'physical.json'),record);return record
