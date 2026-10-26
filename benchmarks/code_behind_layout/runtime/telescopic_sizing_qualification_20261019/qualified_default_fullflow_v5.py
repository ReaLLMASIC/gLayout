"""One prospective physical control after the fixed telescopic ideal pilot.

This trusted engineering probe never imports candidate code. It uses the first
predeclared bias that passed all three ideal corners, verifies the unchanged
independent reference/source, and retains physical and electrical failures.
"""
import json
import ast
import math
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path('/work') if Path('/work/src').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.spice_validation import validate_analysis


OLD_FACTORY_CALL = '''        device = factory(sky130, width=s[category+"_width"], length=s[category+"_length"],
            fingers=s[category+"_fingers"], with_dummy=False, with_tie=True,
            with_dnwell=False).copy().remove_layers(annotations, include_labels=True)'''
NEW_FACTORY_CALL = '''        kwargs = dict(width=s[category+"_width"], length=s[category+"_length"],
            fingers=s[category+"_fingers"], with_dummy=False, with_tie=True)
        device = (factory(sky130, with_dnwell=False, **kwargs) if kind == "n" else
            factory(sky130, dnwell=False, **kwargs)).copy().remove_layers(annotations, include_labels=True)'''


def bound_design(input_directory):
    """Bind the original measured N/bias/decks and an explicit API-only v5 fix."""
    from src.generators.telescopic_ota_reference import DEFAULT, schematic
    input_directory = Path(input_directory)
    amendment_path = input_directory/'engineering_amendment.json'
    amendment = json.loads(amendment_path.read_text()) if amendment_path.is_file() else None
    ideal = ROOT/amendment['original_ideal_run_relative'] if amendment else input_directory
    prior = json.loads((ideal/'summary.json').read_text())
    binding = json.loads((ideal/'input_preparation_binding.json').read_text())
    prepared = Path(binding['preparation'])
    manifest = json.loads((prepared/'design_manifest.json').read_text())
    if prior['actual_OP_AC_corner_calls'] != 12 or not prior['all12_corner_calls_complete'] or not prior['positive_controls']:
        raise ValueError('Physical control requires all twelve actual ideal results and a positive control')
    identifier = prior['first_predeclared_positive_control']
    expected = [c['id'] for c in manifest['controls'] if c['id'] in prior['positive_controls']][0]
    if identifier != expected or manifest['immutable_per_finger_sizing'] != DEFAULT:
        raise ValueError('Ideal selection rule or independent default sizing differs')
    if schematic().encode() != (prepared/identifier/'independent_reference.spice').read_bytes():
        raise ValueError('The independent N(z) differs from the original positive ideal control')
    snapshot = input_directory/'source_snapshot' if amendment else prepared/'source_snapshot'
    for name in ['telescopic_ota.py','telescopic_ota_reference.py','terminal_access.py']:
        current = (ROOT/'src/generators'/name).read_bytes()
        if current != (snapshot/name).read_bytes():
            raise ValueError('Source differs from the explicit engineering snapshot: '+name)
        original = (prepared/'source_snapshot'/name).read_bytes()
        if amendment and name == 'telescopic_ota.py':
            old = original.decode()
            if old.count(OLD_FACTORY_CALL) != 1 or current != old.replace(OLD_FACTORY_CALL,NEW_FACTORY_CALL).encode():
                raise ValueError('The v5 builder amendment must contain only the declared factory keyword correction')
        elif current != original:
            raise ValueError('Independent reference or frozen common access changed: '+name)
    declaration = json.loads((ROOT/'configs/development/telescopic_ota_fullflow.json').read_text())
    if declaration['application'] != manifest['design']['application']:
        raise ValueError('The full-flow application differs from the positive ideal control')
    proof = None
    if amendment:
        failed = ROOT/amendment['original_failed_fullflow_relative']
        failed_manifest = json.loads((failed/'pilot_manifest.json').read_text())
        old_source = (input_directory/'prior_fullflow_source.py').read_text()
        if failed_manifest['status'] != 'FAILED' or (failed/'telescopic_ota_fullflow.py').read_text() != old_source:
            raise ValueError('The preserved original failed physical-control source is not bound')
        names = ['bench_decks','electrical','printed_mos_OP','power']
        def functions(text):
            return {n.name:ast.get_source_segment(text,n) for n in ast.parse(text).body
                if isinstance(n,ast.FunctionDef) and n.name in names}
        if functions(Path(__file__).read_text()) != functions(old_source):
            raise ValueError('The original full electrical bench or measurement formula changed')
        if declaration != json.loads((input_directory/'original_fullflow_declaration.json').read_text()):
            raise ValueError('The original full-flow declaration changed')
        proof = {**amendment,'old_ideal_control_preserved':True,'independent_reference_bytes_identical':True,
            'all_original_biases_and_ideal_decks_reused_without_new_selection':True,
            'full_bench_functions_and_declaration_bytes_unchanged':True,
            'only_builder_delta':'NMOS with_dnwell=False; PMOS dnwell=False',
            'new_ideal_calls':0,'source_identity':amendment['engineering_source_identity']}
    return {'ideal':ideal,'prepared':prepared,'manifest':manifest,'control':next(c for c in manifest['controls'] if c['id']==identifier),
        'declaration':declaration,'engineering_amendment':proof,'source_snapshot':snapshot}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def printed_mos_OP(text, expected):
    """All actual PEX DUT MOS parameters; exact intent is checked separately."""
    names, devices, errors = [], {}, []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'device':
            names = fields[1:]
            for name in names:
                if name.lower().startswith('m.xdut.'):
                    if name in devices:
                        errors.append('duplicate_printed_device_name:'+name)
                    devices[name] = {}
        elif fields[0] in ['gm','gds','id','vds','vdsat']:
            for name, raw in zip(names, fields[1:]):
                if name not in devices:
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    value = None
                if value is None or not math.isfinite(value):
                    devices[name][fields[0]] = raw
                    errors.append('unreadable_or_nonfinite:'+name+':'+fields[0])
                else:
                    devices[name][fields[0]] = value
    complete = not errors and len(devices) == expected and all(
        set(values) == {'gm','gds','id','vds','vdsat'} for values in devices.values())
    return {'complete': complete, 'expected': expected, 'devices': devices, 'errors': errors,
        'scope': 'Actual PEX printed OP inventory, separate from exact per-finger reference graph'}


def power(row, control, first_current):
    return -1.8*row[first_current]-control['VBN_V']*row[first_current+1]-control['VBP_V']*row[first_current+2]


def bench_decks(netlist, cell, ports, control, declaration):
    """Render exactly this source's declared four analyses, not a circuit DSL."""
    bindings = {'VDD':'vdd','GND':'0','IBIAS':'bias','VBN':'vbn','VBP':'vbp',
        'VP':'vp','VN':'vn','VOUT':'out'}
    if len(ports) != 8 or set(p.upper() for p in ports) != set(bindings):
        raise ValueError('Extracted interface differs from the independent eight-port intent')
    prefix = ['Independent telescopic OTA complete physical-control bench',
        '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16',
        '.temp 27', '.include '+str(netlist), 'VSUPPLY vdd 0 1.8', 'IREF vdd bias 10u',
        'VBN vbn 0 '+str(control['VBN_V']), 'VBP vbp 0 '+str(control['VBP_V']), 'CL out 0 2p']
    sources = ['VIN vp 0 dc 1 ac 1', 'LSERVO out vn 1G', 'CAC vn 0 1G']
    names = ' '.join(bindings[p.upper()] for p in ports)
    closed = dict(bindings, VN='out')
    closed_names = ' '.join(closed[p.upper()] for p in ports)
    vectors = 'v(out) v(vp) v(vn) v(bias) i(vsupply) i(vbn) i(vbp)'
    analyses = {
        'op': (sources, names, ['op','wrdata op.dat '+vectors,'show all'],
            {'kind':'op','columns':8,'expected_rows':1}),
        'ac': (sources, names, ['ac dec 30 10 1G','wrdata ac.dat real(v(out)) imag(v(out))'],
            {'kind':'ac','columns':3,'start':10.,'end':1e9,'points':241,'scale':'log'}),
        'transient': ([declaration['transient']['stimulus']], closed_names,
            [declaration['transient']['analysis'],'wrdata transient.dat v(vp) v(out) v(bias)'],
            {'kind':'transient','columns':4,'start':0.,'end':16e-6,
                'required_windows':declaration['transient']['settling_check_windows_s']}),
        'dc': (['VIN vp 0 1'], closed_names,
            [declaration['dc']['analysis'],'wrdata dc.dat v(vp) v(out) v(bias) i(vsupply) i(vbn) i(vbp)'],
            {'kind':'dc','columns':7,'expected_axis':declaration['dc']['expected_axis_V'],
                'start':.9,'end':1.1,'points':5,'scale':'linear'})}
    return prefix, analyses


def electrical(netlist, cell, ports, control, declaration, out, invoke):
    import numpy as np
    prefix, analyses = bench_decks(netlist, cell, ports, control, declaration)
    results = {}
    for corner in declaration['corners']:
        directory = out / corner
        directory.mkdir()
        (directory / '.spiceinit').write_text('set ngbehavior=hsa\n')
        rows = {}
        for kind, (sources, nodes, commands, contract) in analyses.items():
            deck = '\n'.join(prefix+['.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner]
                +sources+['XDUT '+nodes+' '+cell,'.control','set wr_vecnames','set wr_singlescale']
                +commands+['quit','.endc','.end',''])
            (directory / (kind+'.spice')).write_text(deck)
            process = invoke(['ngspice','-b','-o',kind+'.log',kind+'.spice'], directory,
                kind+'_console.log', declaration['per_analysis_wall_limit_s'])
            validation = validate_analysis(directory/(kind+'.dat'), directory/(kind+'.log'),
                contract, process['returncode'])
            rows[kind] = {'validation': validation, 'process': process, 'contract': contract}
        details = printed_mos_OP((directory/'op.log').read_text() if (directory/'op.log').exists() else '',32)
        write(directory/'actual_MOS_OP.json', details)
        complete = all(row['validation']['complete'] for row in rows.values()) and details['complete']
        metrics, passed, op_valid = {}, False, False
        if complete:
            values = {kind: np.loadtxt(directory/(kind+'.dat'),skiprows=1,ndmin=2) for kind in analyses}
            op, ac, dc, tran = values['op'][0], values['ac'], values['dc'], values['transient']
            limits = declaration['fixed_requirements']
            total_power = float(power(op,control,5))
            ratios = [abs(d['vds'])/max(abs(d['vdsat']),1e-30) for d in details['devices'].values()]
            min_vds = min(abs(d['vds']) for d in details['devices'].values())
            min_id = min(abs(d['id']) for d in details['devices'].values())
            op_valid = bool(limits['nominal_output_OP_acceptance_min_V'] <= op[1] <= limits['nominal_output_OP_acceptance_max_V']
                and 0 < total_power <= limits['total_VDD_and_cascode_bias_power_W_max']
                and min(ratios) >= limits['minimum_abs_Vds_over_abs_Vdsat']
                and min_vds >= limits['minimum_absolute_channel_voltage_V'] and min_id > 1e-12)
            response = ac[:,1]+1j*ac[:,2]
            gain = 20*np.log10(np.maximum(np.abs(response),1e-300))
            phase = np.unwrap(np.angle(response))*180/np.pi
            crossing = np.flatnonzero((gain[:-1]>=0)&(gain[1:]<0))
            metrics.update(output_OP_V=float(op[1]), total_bias_included_power_W=total_power,
                minimum_abs_Vds_over_abs_Vdsat=min(ratios), minimum_abs_Vds_V=min_vds,
                minimum_abs_finger_current_A=min_id, gain_at_10Hz_dB=float(gain[0]),
                positive_low_frequency_gain=bool(response[0].real>0), descending_unity_crossings=len(crossing))
            if len(crossing):
                i = int(crossing[0]); f = -gain[i]/(gain[i+1]-gain[i])
                metrics.update(ugb_Hz=float(np.exp(np.log(ac[i,0])+f*np.log(ac[i+1,0]/ac[i,0]))),
                    phase_margin_deg=float(180+phase[i]+f*(phase[i+1]-phase[i])))
            def window(bounds):
                selected = (tran[:,0]>bounds[0])&(tran[:,0]<bounds[1])
                if not selected.any():
                    raise ValueError('Declared waveform window lacks actual samples')
                return tran[selected,2]
            high = float(window(declaration['transient']['high_plateau_window_s']).mean())
            low = float(window(declaration['transient']['low_plateau_window_s']).mean())
            span = abs(high-low)
            errors = [float(np.max(np.abs(window(bounds)-final))/span) if span>0 else None
                for bounds,final in zip(declaration['transient']['settling_check_windows_s'],[high,low])]
            slopes = np.diff(dc[:,2])/np.diff(dc[:,1])
            metrics.update(transient_incremental_gain=(high-low)/.02,
                transient_final_plateau_relative_errors=errors,
                dc_incremental_gain_min=float(slopes.min()), dc_incremental_gain_max=float(slopes.max()),
                sampled_dc_input_output_V=[{'input_V':float(row[1]),'output_V':float(row[2])} for row in dc],
                dc_total_power_W=[float(power(row,control,4)) for row in dc])
            passed = bool(op_valid and metrics['positive_low_frequency_gain']
                and metrics['gain_at_10Hz_dB']>=limits['gain_at_10Hz_dB_min']
                and metrics.get('ugb_Hz',0)>=limits['ugb_Hz_min']
                and limits['phase_margin_deg_min']<=metrics.get('phase_margin_deg',-1)<=limits['phase_margin_deg_max']
                and limits['transient_incremental_gain_min']<=metrics['transient_incremental_gain']<=limits['transient_incremental_gain_max']
                and all(error is not None and error<=limits['transient_final_plateau_relative_error_max'] for error in errors)
                and limits['dc_incremental_gain_min']<=slopes.min()<=slopes.max()<=limits['dc_incremental_gain_max']
                and bool(np.all((dc[:,2]>=.7)&(dc[:,2]<=1.2))))
        record = {'complete':bool(complete),'operating_point_valid':op_valid,'specifications_passed':passed,
            'metrics':metrics,'analyses':rows,'printed_actual_per_finger_OP_complete':details['complete']}
        write(directory/'result.json',record)
        results[corner] = record
        write(out/'electrical_progress.json',results)
    return results


def main():
    from src.generators.telescopic_ota import build
    from src.generators.telescopic_ota_reference import DEFAULT, PORTS, schematic
    from src.physical_drc import check_gds
    from src.device_intent import compare_device_intent
    from src.report_parsers import netgen_lvs_report, rc_netlist_inventory

    out = Path.cwd()
    bound = bound_design(Path(os.environ['PROBE_INPUT']))
    ideal, control = bound['ideal'], bound['control']
    reference = out/'independent_reference.spice'
    reference.write_text(schematic())
    for name in ['telescopic_ota.py','telescopic_ota_reference.py','terminal_access.py']:
        source = ROOT/'src/generators'/name
        shutil.copyfile(source,out/name)
    declaration = bound['declaration']
    write(out/'frozen_fullflow_declaration.json',declaration)
    result = {'scope':'development_telescopic_OTA_independent_fullflow_control_NOT_FORMAL_NOT_TRAIN',
        'source_identity':(bound['engineering_amendment'] or {}).get('source_identity',declaration['source_identity']),
        'engineering_amendment':bound['engineering_amendment'],'ideal_positive_control_run':str(ideal),
        'selected_predeclared_bias':control,'sizing':DEFAULT,'tool_processes':[],
        'cost_scope':'Each recorded tool process is an actual waited-child CPU component. Whole probe profiling additionally includes generation and full DRC; do not add these components twice.',
        'status':'RUNNING','S0':False,'S1':False,'S2':False,'candidate_failure':False}
    def save(): write(out/'qualification.json',result)
    def invoke(argv,cwd,logname,timeout,stdin=None):
        before = resource.getrusage(resource.RUSAGE_CHILDREN); began = time.monotonic()
        try:
            with (cwd/logname).open('w') as log:
                run = subprocess.run(argv,cwd=cwd,input=stdin,text=True,stdout=log,
                    stderr=subprocess.STDOUT,timeout=timeout)
            code,error = run.returncode,None
        except subprocess.TimeoutExpired:
            code,error = None,'declared_wall_timeout'
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {'argv':argv,'returncode':code,'error':error,'wall_seconds':time.monotonic()-began,
            'actual_waited_child_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            'log':str(cwd/logname),'timeout_seconds':timeout}
        result['tool_processes'].append(record);save()
        return record
    def magic(lines,stem,timeout):
        text = '\n'.join(lines+['puts stdout EXTRACTION_COMPLETE','quit -noprompt',''])
        (out/(stem+'.tcl')).write_text(text)
        process = invoke(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc',
            '-noconsole','-dnull'],out,stem+'.log',timeout,text)
        if process['returncode']!=0 or 'EXTRACTION_COMPLETE' not in (out/(stem+'.log')).read_text():
            raise RuntimeError('Magic extraction is incomplete; preserve as unknown')
    save()
    try:
        gds = build(out)
        result['S0'] = True;save()
        result['DRC'] = check_gds(gds,out/'drc_full',timeout=180);save()
        if not result['DRC']['completed']:
            raise RuntimeError('Full-rule DRC did not complete')
        if not result['DRC']['is_clean']:
            result.update(status='COMPLETED_PHYSICAL_DRC_FAILURE',candidate_failure=True);save();return
        top = 'telescopic_mirror_ota'
        magic(['drc off','gds read {'+str(gds)+'}','load '+top,'select top cell','flatten '+top+'_lvs',
            'load '+top+'_lvs','select top cell','extract all','ext2spice lvs',
            'ext2spice -o extracted_lvs.spice'],'lvs_extract',180)
        netgen = invoke(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' '+top+'_lvs',
            str(reference)+' '+top,'/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],
            out,'netgen.log',180)
        if netgen['returncode'] is None or not (out/'lvs.rpt').is_file():
            raise RuntimeError('Independent LVS tool did not complete')
        lvs_report = (out/'lvs.rpt').read_text()
        if 'Final result:' not in lvs_report:
            raise RuntimeError('LVS report lacks its final result; not a connectivity-negative label')
        result['LVS'] = netgen_lvs_report(lvs_report)
        result['device_intent'] = compare_device_intent((out/'extracted_lvs.spice').read_text(),reference.read_text());save()
        if netgen['returncode']!=0 or not result['LVS']['is_clean'] or not result['device_intent']['is_clean']:
            result.update(status='COMPLETED_INDEPENDENT_CONNECTIVITY_OR_DEVICE_FAILURE',candidate_failure=True);save();return
        result['S1'] = True;save()
        cell = top+'_rc'; pex = out/(top+'_pex.spice')
        magic(['drc off','gds read {'+str(gds)+'}','load '+top,'select top cell','flatten '+cell,
            'load '+cell,'select top cell','extract do local','extract all','feedback save extraction_feedback.tcl',
            'ext2sim labels on','ext2sim','extresist simplify off','extresist all','ext2spice lvs',
            'ext2spice cthresh 0','ext2spice extresist on','ext2spice -o '+pex.name],'rc_extract',240)
        result['RC'] = rc_netlist_inventory(pex.read_text(),cell,PORTS);save()
        if not result['RC']['has_real_RC']:
            raise RuntimeError('Positive full RC and its complete interface were not established')
        result['corners'] = electrical(pex,cell,result['RC']['ports'],control,declaration,out,invoke)
        complete = all(row['complete'] for row in result['corners'].values())
        result.update(S2=complete and all(row['specifications_passed'] for row in result['corners'].values()),
            candidate_failure=complete and not all(row['specifications_passed'] for row in result['corners'].values()),
            status='COMPLETE' if complete else 'INCOMPLETE_ELECTRICAL_UNKNOWN')
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,subprocess.TimeoutExpired) as error:
        result.update(status='INFRASTRUCTURE_OR_NUMERICAL_UNKNOWN',error=type(error).__name__+': '+str(error))
    save()
    print(json.dumps(result,indent=2,allow_nan=False),flush=True)


if __name__ == '__main__':
    main()
