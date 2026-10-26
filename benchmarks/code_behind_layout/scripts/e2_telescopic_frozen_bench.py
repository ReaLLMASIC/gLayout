"""Qualified telescopic bench transport for a protected E2 trusted capsule.

The original bench_decks/electrical functions are copied unchanged beside this
module as original_bench.py. No candidate Python is imported. Full calls retain
all twelve separate analyses; nominal calls execute the original TT OP and AC
decks separately and advertise two real SPICE invocations.
"""
import importlib.util
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import time


def write(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def metric_row(row):
    values=row['metrics'];result={}
    if row['complete']:
        mapping={'gain':('gain_at_10Hz_dB','dB'),'phase_margin':('phase_margin_deg','deg'),
            'ugb':('ugb_Hz','Hz'),'power':('total_bias_included_power_W','W'),
            'output_voltage':('output_OP_V','V'),'saturation_margin':('minimum_abs_Vds_over_abs_Vdsat','1'),
            'minimum_channel_voltage':('minimum_abs_Vds_V','V'),'minimum_finger_current':('minimum_abs_finger_current_A','A'),
            'transient_incremental_gain':('transient_incremental_gain','1'),
            'dc_incremental_gain_min':('dc_incremental_gain_min','1'),'dc_incremental_gain_max':('dc_incremental_gain_max','1')}
        for name,(original,unit) in mapping.items():
            # Complete waveforms can have no unity crossing or no usable
            # response. Keep the missing metric as a completed spec failure.
            if original not in values or values[original] is None:continue
            value=values[original]
            if type(value) not in [int,float] or not math.isfinite(value):raise ValueError('Nonfinite original metric: '+original)
            result[name]={'value':value,'unit':unit}
        errors=values.get('transient_final_plateau_relative_errors',[])
        if errors and all(type(v) in [int,float] and math.isfinite(v) for v in errors):
            result['transient_plateau_error']={'value':max(errors),'unit':'1'}
        voltage=[r['output_V'] for r in values.get('sampled_dc_input_output_V',[])]
        if voltage and all(type(v) in [int,float] and math.isfinite(v) for v in voltage):
            result['dc_output_min']={'value':min(voltage),'unit':'V'}
            result['dc_output_max']={'value':max(voltage),'unit':'V'}
    return result


def normalize(rows,out):
    out=Path(out);corners={}
    for corner,row in rows.items():
        artifacts={}
        for name,item in row['analyses'].items():
            label='tran' if name=='transient' else name
            artifacts[label]={'data':str(out/corner/(name+'.dat')),'log':str(out/corner/(name+'.log')),
                'returncode':item['process']['returncode']}
        corners[corner]={'converged':bool(row['complete']),'operating_point_valid':bool(row['operating_point_valid']),
            'original_development_constraints_passed':bool(row['specifications_passed']),
            'metrics':metric_row(row),'analyses':artifacts,'raw':row}
    return {'corners':corners,'full_bench_functions_unchanged':True}


def run_post_rc(out,pex,cell,ports,parameters,contract,*,kind,bench_snapshot,reference_path):
    if kind!='telescopic' or parameters!=contract['immutable_parameters']:
        raise ValueError('The telescopic exact sized contract differs')
    out=Path(out);work=out/'post_rc_measurements';work.mkdir()
    specification=Path('/trusted/telescopic_declaration.json')
    control=Path('/trusted/telescopic_bias.json')
    # The independent launcher is the same profiling seam used by the existing
    # protected E2 cached evaluator; no source/GDS/RC acquisition is repeated.
    launcher=work/'run_bench.py'
    text='\n'.join(['import json,resource,subprocess,time,sys', 'from pathlib import Path',
        "sys.path.insert(0,'/trusted')",'import original_bench as bench',
        'out=Path('+repr(str(work))+')','calls=[]',
        'def invoke(argv,cwd,logname,timeout,stdin=None):',
        '    before=resource.getrusage(resource.RUSAGE_CHILDREN);started=time.monotonic();code=None;error=None',
        '    try:',
        "        with (cwd/logname).open('w') as log:",
        '            result=subprocess.run(argv,cwd=cwd,input=stdin,text=True,stdout=log,stderr=subprocess.STDOUT,timeout=timeout);code=result.returncode',
        '    except subprocess.TimeoutExpired:error="declared_wall_timeout"',
        '    after=resource.getrusage(resource.RUSAGE_CHILDREN)',
        "    row={'argv':argv,'returncode':code,'error':error,'wall_seconds':time.monotonic()-started,'actual_waited_child_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,'log':str(cwd/logname),'timeout_seconds':timeout}",
        "    calls.append(row);(out/'actual_processes.json').write_text(json.dumps(calls,indent=2)+'\\n');return row",
        'declaration=json.loads(Path('+repr(str(specification))+').read_text())',
        'declaration["corners"]='+repr(contract['required_corners']),
        'rows=bench.electrical(Path('+repr(str(pex))+'),'+repr(cell)+','+repr(ports)+',json.loads(Path('+repr(str(control))+').read_text()),declaration,out,invoke)',
        "(out/'raw_corner_results.json').write_text(json.dumps(rows,indent=2,allow_nan=False)+'\\n')",''])
    launcher.write_text(text)
    declaration=json.loads(specification.read_text());limit=len(contract['required_corners'])*4*declaration['per_analysis_wall_limit_s']+60
    with (work/'bench_console.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(launcher)],stdout=log,stderr=subprocess.STDOUT)
        try:code=process.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            process.kill();process.wait();raise TimeoutError('Declared complete telescopic bench budget expired')
    if code:raise RuntimeError('Frozen telescopic electrical launcher failed; raw preserved')
    rows=json.loads((work/'raw_corner_results.json').read_text())
    return normalize(rows,work)


def run_nominal(out,pex,cell,ports,parameters,contract,*,kind,bench_snapshot,reference_path):
    """Only the two original TT decks; no prediction or S2 is produced."""
    if kind!='telescopic' or parameters!=contract['immutable_parameters']:raise ValueError('Nominal sized intent differs')
    import numpy as np
    from src.spice_validation import validate_analysis
    spec=importlib.util.spec_from_file_location('_telescopic_original',bench_snapshot)
    bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)
    declaration=json.loads(Path('/trusted/telescopic_declaration.json').read_text())
    control=json.loads(Path('/trusted/telescopic_bias.json').read_text())
    out=Path(out);work=out/'nominal_tt';work.mkdir();(work/'.spiceinit').write_text('set ngbehavior=hsa\n')
    prefix,analyses=bench.bench_decks(Path(pex),cell,ports,control,declaration)
    actual={};started=time.monotonic()
    for name in ['op','ac']:
        sources,nodes,commands,original_contract=analyses[name]
        deck='\n'.join(prefix+['.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt']+sources+
            ['XDUT '+nodes+' '+cell,'.control','set wr_vecnames','set wr_singlescale']+commands+['quit','.endc','.end',''])
        (work/(name+'.spice')).write_text(deck)
        before=resource.getrusage(resource.RUSAGE_CHILDREN);began=time.monotonic();code=None;error=None
        argv=['ngspice','-b','-o',name+'.log',name+'.spice']
        try:
            with (work/(name+'_console.log')).open('w') as log:
                process=subprocess.run(argv,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=declaration['per_analysis_wall_limit_s']);code=process.returncode
        except subprocess.TimeoutExpired:error='declared_wall_timeout'
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        usage={'argv':argv,'returncode':code,'error':error,'wall_seconds':time.monotonic()-began,
            'waited_child_user_CPU_seconds':after.ru_utime-before.ru_utime,'waited_child_system_CPU_seconds':after.ru_stime-before.ru_stime,
            'scope':'Actual serial nominal SPICE component; do not add twice to trusted-container total'}
        write(work/(name+'_process_resource.json'),usage)
        actual[name]={'data':str(work/(name+'.dat')),'log':str(work/(name+'.log')),'returncode':code,
            'validation':validate_analysis(work/(name+'.dat'),work/(name+'.log'),original_contract,code),'actual_cost':usage}
    devices=bench.printed_mos_OP((work/'op.log').read_text() if (work/'op.log').exists() else '',32)
    write(work/'actual_MOS_OP.json',devices)
    complete=devices['complete'] and all(v['validation']['complete'] for v in actual.values())
    metrics={};healthy=False
    if complete:
        op=np.loadtxt(work/'op.dat',skiprows=1,ndmin=2)[0];ac=np.loadtxt(work/'ac.dat',skiprows=1,ndmin=2)
        power=float(bench.power(op,control,5));limits=declaration['fixed_requirements']
        ratios=[abs(d['vds'])/max(abs(d['vdsat']),1e-30) for d in devices['devices'].values()]
        healthy=bool(limits['nominal_output_OP_acceptance_min_V']<=op[1]<=limits['nominal_output_OP_acceptance_max_V']
            and 0<power<=limits['total_VDD_and_cascode_bias_power_W_max'] and min(ratios)>=limits['minimum_abs_Vds_over_abs_Vdsat']
            and min(abs(d['vds']) for d in devices['devices'].values())>=limits['minimum_absolute_channel_voltage_V']
            and min(abs(d['id']) for d in devices['devices'].values())>1e-12)
        response=ac[:,1]+1j*ac[:,2];gain=20*np.log10(np.maximum(np.abs(response),1e-300));phase=np.unwrap(np.angle(response))*180/np.pi
        crossing=np.flatnonzero((gain[:-1]>=0)&(gain[1:]<0))
        metrics.update(tt_gain_dB=float(gain[0]),tt_output_V=float(op[1]),tt_power_W=power,
            tt_positive_low_frequency_gain=bool(response[0].real>0))
        if len(crossing):
            i=int(crossing[0]);f=-gain[i]/(gain[i+1]-gain[i])
            metrics.update(tt_ugb_Hz=float(np.exp(np.log(ac[i,0])+f*np.log(ac[i+1,0]/ac[i,0]))),
                tt_phase_margin_deg=float(180+phase[i]+f*(phase[i+1]-phase[i])))
        healthy=healthy and metrics['tt_positive_low_frequency_gain']
    record={'scope':'E2_telescopic_actual_two_deck_TT_OP_AC_NOT_S2','complete':bool(complete),'operating_point_valid':bool(healthy),
        'metrics':metrics,'analyses':{k:{n:v[n] for n in ['data','log','returncode']} for k,v in actual.items()},
        'analysis_validation':{k:v['validation'] for k,v in actual.items()},'actual_processes':actual,
        'new_SPICE_calls':2,'new_Tran_DC_SS_FF_SPICE_calls':0,'original_deck_renderer_unchanged':True,
        'measurement_function_or_loop_unchanged':False,'numeric_formula_transport_calibration_required':True,
        'full_bench_completion_claimed':False,'UGB_worst_corner_prediction':None,'analysis_wall_seconds':time.monotonic()-started}
    write(out/'nominal_measurement.json',record);return record
