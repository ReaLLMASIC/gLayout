"""Applicable benches for the textbook train domains declared in E4 stage 1.

Three bench categories are rendered from the declared contract's ``nominal_operating_point``
(never hand-tuned here): ``mirror`` (C03, C13, C14; reference current in, output swept),
``single`` (C04, C06, C12, C15; single-stage voltage amplifier with the disclosed DC servo and
replica bias generators of the textbook benchmark) and ``diff_r`` (C16, C17; resistor-loaded
differential pair driven as in the C07 bench, differential output measured). Physical extraction follows
src/corpus_component_benches.py verbatim. No policy or evaluation-target generator is imported.
"""
import json
import math
from pathlib import Path
import subprocess

NFET = 'sky130_fd_pr__nfet_01v8'
PFET = 'sky130_fd_pr__pfet_01v8'
WDIV = {'diode': 1.0, 'cascode': 4.0, 'cascode3': 9.0}
BENCH_REVISION = 'textbook_physical_v3_mirror_input_port_IIN1_or_IB1'
MIRROR_BINDING = {'VSS': '0', 'IIN1': 'iin', 'IOUT1': 'out', 'IB1': 'ib1', 'IREF1': 'iref1'}
SINGLE_BINDING = {'VDD': 'vdd', 'VSS': '0', 'VIN1': 'vin', 'VOUT1': 'out', 'VB1': 'vb1', 'VB2': 'vb2', 'VB3': 'vb3'}
DIFF_BINDING = {'VDD': 'vdd', 'VSS': '0', 'VIN1': 'vinp', 'VIN2': 'vinn', 'VOUT1': 'outp', 'VOUT2': 'outn', 'IB1': 'tail', 'VB1': 'vb1'}


def dump(path, value): Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def replica_lines(node, spec, sizes, devices):
    """Disclosed ideal replica bias generator (textbook benchmark rule): the gate of a diode-connected copy of
    the named DUT device at the same per-finger size, carrying current x WDIV[kind] (V_T + n V_ov for cascode
    gates), fed from the separate 1.8 V bias supply so that DUT supply current stays separable."""
    dev = next(d for d in devices if d['name'] == spec['replica'])
    sz = sizes[dev['name']]
    current = spec['current'] * WDIV[spec.get('kind', 'diode')]
    unit = sz['w'] / sz['nf']
    if dev['kind'] == 'nfet':
        return [f"XB_{node} {node} {node} 0 0 {NFET} w={unit:g} l={sz['l']:g} m={sz['nf']}", f"IB_{node} vddbias {node} {current:g}"]
    return [f"XB_{node} {node} {node} vddbias vddbias {PFET} w={unit:g} l={sz['l']:g} m={sz['nf']}", f"IB_{node} {node} 0 {current:g}"]


def subckt_pins(netlist, name):
    """Pin order of the extracted DUT subcircuit; the bench binds by pin name so port label order never changes the wiring."""
    for line in Path(netlist).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == '.subckt' and parts[1] == name: return parts[2:]
    raise ValueError('Extracted netlist lacks the DUT subcircuit header: ' + name)


def dut_line(binding, ports, netlist, name):
    pins = subckt_pins(netlist, name)
    if sorted(pins) != sorted(ports): raise ValueError('Extracted DUT pins differ from the declared ports: ' + ' '.join(pins))
    return 'XDUT ' + ' '.join(binding[pin] for pin in pins) + ' ' + name


def benches(category, sizes, name, netlist, ports, corner, nop, devices, solver='trap'):
    common = ['Textbook train-domain development qualification',
              '.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ' + corner,
              '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16', '.temp 27', '.include ' + str(netlist), 'VSUPPLY vdd 0 1.8']
    if solver == 'gear2': common.insert(3, '.option method=gear maxord=2')
    elif solver != 'trap': raise ValueError('Unknown explicitly declared integration method')
    if category == 'mirror':
        binding = MIRROR_BINDING
        iref = nop['reference_current_A']; vt = nop['output_test_V']; lo, hi = nop['output_transient_levels_V']
        extra = nop.get('extra_current_sources_A', {})
        inport = 'IIN1' if 'IIN1' in ports else 'IB1'; vin = binding[inport]
        common += [dut_line(binding, ports, netlist, name), f"IIN vdd {vin} {iref:g}"]
        common += [f"I{port} vdd {binding[port]} {extra[port]:g}" for port in ports if port in extra and port != inport]
        common += ['.nodeset ' + ' '.join(f"v({binding[port]})=0.54" for port in ports if port not in ('VSS', 'IOUT1'))]
        bodies = {'ac': [f"VOUT out 0 {vt:g} ac 1", '.control', 'op', f"wrdata op.dat v({vin}) i(vout) i(vsupply)",
                         'ac dec 20 10 1G', 'wrdata ac.dat real(i(vout)) imag(i(vout))'],
                  'tran': [f"VOUT out 0 pulse({lo:g} {hi:g} 1u 10n 10n 1u 2u)", '.control', 'tran 5n 4u', 'wrdata tran.dat v(out) i(vout)'],
                  'dc': [f"VOUT out 0 {vt:g}", '.control', 'dc VOUT 0 1.8 .05', 'wrdata dc.dat v(out) i(vout)']}
    elif category == 'single':
        binding = SINGLE_BINDING
        cl = nop['load_capacitance_F']; step = nop['input_step_V']
        lines = ['VBIASSUPPLY vddbias 0 1.8']
        for port in ports:
            if port in nop.get('replica_bias', {}): lines += replica_lines(binding[port], nop['replica_bias'][port], sizes, devices)
        common += [dut_line(binding, ports, netlist, name)] + lines + [f"CL out 0 {cl:g}"]
        servo = ['LFB out vin 1e6', 'CIN vac vin 1e6']
        bodies = {'ac': servo + ['VAC vac 0 dc 0 ac 1', '.control', 'op', 'wrdata op.dat v(out) v(vin) i(vsupply)',
                                 'ac dec 20 10 1G', 'wrdata ac.dat real(v(out)) imag(v(out))'],
                  'tran': servo + [f"VAC vac 0 pulse({-step:g} {step:g} 1u 10n 10n 1u 2u)", '.control', 'tran 5n 4u', 'wrdata tran.dat v(vac) v(out)'],
                  'dc': ['VIN vin 0 0', '.control', 'dc VIN 0 1.8 .05', 'wrdata dc.dat v(vin) v(out)']}
    elif category == 'diff_r':
        binding = DIFF_BINDING
        cl = nop['load_capacitance_F']; vcm = nop['input_common_mode_V']; step = nop['differential_step_V']
        lines = ['VBIASSUPPLY vddbias 0 1.8', f"VCM vcm 0 {vcm:g}", 'EINP vinp vcm vd 0 .5', 'EINN vinn vcm vd 0 -.5', f"CL1 outp 0 {cl:g}", f"CL2 outn 0 {cl:g}"]
        for port in ports:
            if port in nop.get('replica_bias', {}): lines += replica_lines(binding[port], nop['replica_bias'][port], sizes, devices)
        if 'IB1' in ports: lines.append(f"ITAIL tail 0 {nop['tail_current_A']:g}")
        common += [dut_line(binding, ports, netlist, name)] + lines
        bodies = {'ac': ['VD vd 0 0 ac 1', '.control', 'op', 'wrdata op.dat v(outp) v(outn) i(vsupply)', 'ac dec 20 10 1G',
                         'let gd = v(outp)-v(outn)', 'wrdata ac.dat real(gd) imag(gd)'],
                  'tran': [f"VD vd 0 pulse({-step:g} {step:g} 1u 10n 10n 1u 2u)", '.control', 'tran 5n 4u', 'let dout = v(outp)-v(outn)', 'wrdata tran.dat v(vd) dout'],
                  'dc': ['VD vd 0 0', '.control', 'dc VD -.1 .1 .005', 'wrdata dc.dat v(vd) v(outp) v(outn)']}
    else:
        raise ValueError('Unknown declared bench category')
    return common, bodies


def diff_r_metrics(op, ac, dc, tran, windows, nop, ac_path):
    import numpy as np
    from src.corpus_metrics import frequency_3db
    vop, von, idd = float(op[1]), float(op[2]), float(-op[3])
    h = np.hypot(ac[:, 1], ac[:, 2]); gain_lf = float(h[0]); gain_db = 20 * math.log10(gain_lf) if gain_lf > 0 else None
    try: f3db = frequency_3db(ac_path)
    except ValueError: f3db = None
    diff = dc[:, 2] - dc[:, 3]; vd = dc[:, 1]
    crossing = np.flatnonzero((diff[:-1] <= 0) & (diff[1:] > 0)) if diff[0] <= diff[-1] else np.flatnonzero((diff[:-1] >= 0) & (diff[1:] < 0))
    offset = float(np.interp(0, diff, vd)) if len(crossing) and np.all(np.diff(diff) > 0) else (float(np.interp(0, diff[::-1], vd[::-1])) if len(crossing) and np.all(np.diff(diff) < 0) else None)
    step = nop['differential_step_V']
    settled = [(float(np.mean(tran[mask, 2])) - (vop - von)) / float(np.mean(tran[mask, 1])) for mask in windows]
    settled_gain = float(np.mean([abs(s) for s in settled]))
    metrics = {'output_common_mode_V': (vop + von) / 2, 'output_positive_bias_V': vop, 'output_negative_bias_V': von, 'supply_current_A': idd,
               'main_supply_power_W': 1.8 * idd, 'gain_lf': gain_lf, 'gain_lf_dB': gain_db, 'f3db_Hz': f3db,
               'systematic_input_offset_V': offset, 'dc_differential_output_span_V': float(np.max(diff) - np.min(diff)),
               'settled_step_gain': settled_gain, 'settled_step_gain_error_vs_AC': abs(settled_gain - gain_lf) / gain_lf if gain_lf > 0 else None,
               'differential_step_V': step}
    valid = 0.2 < (vop + von) / 2 < 1.6 and gain_lf > 1 and f3db is not None and offset is not None
    return metrics, bool(valid)


def mirror_metrics(op, ac, dc, tran, windows, nop):
    import numpy as np
    iref = nop['reference_current_A']; vt = nop['output_test_V']; tol = nop['tolerance']
    v = dc[:, 1]; current = -dc[:, 2]
    i_t = float(np.interp(vt, v, current))
    k = int(np.argmin(abs(v - vt))); k = min(max(k, 1), len(v) - 2)
    slope = float((current[k + 1] - current[k - 1]) / (v[k + 1] - v[k - 1]))
    errors = abs(current / iref - 1); good = errors <= tol; lower = upper = k
    if good[k]:
        while lower > 0 and good[lower - 1]: lower -= 1
        while upper + 1 < len(good) and good[upper + 1]: upper += 1
    settled = np.interp(tran[:, 1], v, current)
    region = (v >= vt - 0.2 - 1e-9) & (v <= vt + 0.2 + 1e-9)
    metrics = {'input_bias_V': float(op[1]), 'nominal_current_A': i_t, 'nominal_current_relative_error': float(abs(i_t / iref - 1)),
               'output_resistance_ohm': 1 / slope if slope > 0 else None, 'output_conductance_10Hz_S': float(-ac[0, 1]),
               'compliance_low_V': float(v[lower]) if good[k] else None, 'compliance_high_V': float(v[upper]) if good[k] else None,
               'max_current_relative_error_in_region': float(np.max(errors[region])),
               'settled_current_error_vs_DC_A': max(float(np.max(abs(-tran[mask, 2] - settled[mask]))) for mask in windows),
               'external_reference_supply_power_W': float(-1.8 * op[3]), 'DUT_input_port_power_W': float(op[1] * iref),
               'DUT_output_port_power_W': float(-vt * op[2])}
    valid = 0 < op[1] < 1.8 and i_t > 0 and slope > 0
    return metrics, bool(valid)


def single_metrics(op, ac, dc, tran, windows, nop, ac_path):
    import numpy as np
    from src.corpus_metrics import frequency_3db
    vout0 = float(op[1]); vin0 = float(op[2]); idd = float(-op[3])
    h = np.hypot(ac[:, 1], ac[:, 2]); gain_lf = float(h[0])
    gain_db = 20 * math.log10(gain_lf) if gain_lf > 0 else None
    try: f3db = frequency_3db(ac_path)
    except ValueError: f3db = None
    ugf = None
    crossing = np.flatnonzero((h[:-1] >= 1) & (h[1:] < 1))
    if len(crossing):
        i = int(crossing[0]); fraction = (h[i] - 1) / (h[i] - h[i + 1])
        ugf = float(math.exp(math.log(ac[i, 0]) + fraction * math.log(ac[i + 1, 0] / ac[i, 0])))
    transfer_slope = np.gradient(dc[:, 2], dc[:, 1])
    step = nop['input_step_V']
    settled = [(float(np.mean(tran[mask, 2])) - vout0) / float(np.mean(tran[mask, 1])) for mask in windows]
    settled_gain = float(np.mean([abs(s) for s in settled]))
    metrics = {'output_bias_V': vout0, 'input_bias_V': vin0, 'supply_current_A': idd, 'main_supply_power_W': 1.8 * idd,
               'gain_lf': gain_lf, 'gain_lf_dB': gain_db, 'f3db_Hz': f3db, 'unity_gain_frequency_Hz': ugf,
               'dc_transfer_max_gain': float(np.max(abs(transfer_slope))), 'dc_output_min_V': float(np.min(dc[:, 2])),
               'dc_output_max_V': float(np.max(dc[:, 2])), 'settled_step_gain': settled_gain,
               'settled_step_gain_error_vs_AC': abs(settled_gain - gain_lf) / gain_lf if gain_lf > 0 else None,
               'input_step_V': step}
    valid = 0.1 < vout0 < 1.7 and gain_lf > 1 and f3db is not None
    return metrics, bool(valid)


def simulate(output, category, sizes, name, netlist, ports, contract, devices, solver='trap'):
    import numpy as np
    from src.spice_validation import validate_analysis
    contracts = contract['analysis_contracts']; nop = contract['nominal_operating_point']
    result = {}
    for corner in ['tt', 'ss', 'ff']:
        work = output / corner; work.mkdir(); (work / '.spiceinit').write_text('set ngbehavior=hsa\n')
        common, bodies = benches(category, sizes, name, netlist, ports, corner, nop, devices, solver); analyses = {}
        for analysis, body in bodies.items():
            index = body.index('.control'); body = body[:index + 1] + ['set wr_vecnames', 'set wr_singlescale'] + body[index + 1:] + ['quit', '.endc', '.end', '']
            (work / (analysis + '.spice')).write_text('\n'.join(common + body))
            with (work / (analysis + '_console.log')).open('w') as log:
                ran = subprocess.run(['ngspice', '-b', '-o', analysis + '.log', analysis + '.spice'], cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            analyses[analysis] = {**validate_analysis(work / (analysis + '.dat'), work / (analysis + '.log'), contracts[analysis], ran.returncode), 'returncode': ran.returncode}
            if analysis == 'ac': analyses['op'] = {**validate_analysis(work / 'op.dat', work / 'ac.log', contracts['op'], ran.returncode), 'returncode': ran.returncode}
        complete = all(row['complete'] for row in analyses.values()); metrics = {}; op_valid = False
        if complete:
            data = lambda label: np.loadtxt(work / (label + '.dat'), skiprows=1, ndmin=2)
            op = data('op')[0]; ac = data('ac'); dc = data('dc'); tran = data('tran')
            windows = [(tran[:, 0] >= a) & (tran[:, 0] <= b) for a, b in contracts['tran']['required_windows']]
            if category == 'mirror': metrics, op_valid = mirror_metrics(op, ac, dc, tran, windows, nop)
            elif category == 'diff_r': metrics, op_valid = diff_r_metrics(op, ac, dc, tran, windows, nop, work / 'ac.dat')
            else: metrics, op_valid = single_metrics(op, ac, dc, tran, windows, nop, work / 'ac.dat')
        result[corner] = {'complete': complete, 'operating_point_valid': bool(op_valid), 'analyses': analyses, 'metrics': metrics}
        dump(output / 'spice_progress.json', result)
    return result


def evaluate(output, circuit, sizes, name, gds, gold, contract, devices, prelayout=False, solver='trap', pex_script=None):
    """Run independent schematic controls or the actual full DRC/LVS/positive-RC flow (verbatim procedure of
    src/corpus_component_benches.evaluate), then the declared bench."""
    output.mkdir(parents=True, exist_ok=True)
    record = {'scope': 'development_textbook_train_qualification_not_formal', 'circuit_id': circuit.circuit_id,
              'configuration_id': contract['configuration_id'], 'bench_category': contract['bench_category'], 'prelayout': prelayout,
              'formal_training_rows': 0, 'integration_method': solver, 'tight_tolerances_unchanged': True}
    netlist = gold; sim_name = name
    if not prelayout:
        import gdstk
        from src.physical_drc import check_gds
        from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
        from src.device_intent import compare_device_intent
        top, = gdstk.read_gds(gds).top_level()
        box = top.bounding_box(); record['area_um2'] = float((box[1][0] - box[0][0]) * (box[1][1] - box[0][1]))
        record['DRC'] = check_gds(gds, output / 'drc_full'); dump(output / 'physical.json', record)
        script = '\n'.join(['gds read {' + str(gds) + '}', 'load ' + name, 'select top cell', 'extract all', 'ext2spice lvs', 'ext2spice -o layout_lvs.spice', 'quit -noprompt', ''])
        (output / 'lvs_extract.tcl').write_text(script)
        with (output / 'lvs_magic.log').open('w') as log:
            subprocess.run(['magic', '-rcfile', '/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc', '-noconsole', '-dnull'], input=script, text=True, cwd=output, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        with (output / 'netgen.log').open('w') as log:
            subprocess.run(['netgen', '-batch', 'lvs', str(output / 'layout_lvs.spice') + ' ' + name, str(gold) + ' ' + name,
                            '/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl', str(output / 'netgen_lvs.rpt')], cwd=output, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        record['LVS'] = netgen_lvs_report((output / 'netgen_lvs.rpt').read_text()); dump(output / 'physical.json', record)
        if not (record['DRC']['is_clean'] and record['LVS']['is_clean']): return record
        record['DeviceIntent'] = compare_device_intent((output / 'layout_lvs.spice').read_text(), gold.read_text())
        dump(output / 'physical.json', record)
        if not record['DeviceIntent']['is_clean']: return record
        with (output / 'pex.log').open('w') as log:
            ran = subprocess.run(['bash', str(pex_script or '/work/vendor/glayout/src/glayout/verification/run_pex.sh'), str(gds), name], cwd=output, stdout=log, stderr=subprocess.STDOUT, timeout=360)
        netlist = output / (name + '_pex.spice'); sim_name = name + '_rc'; record['pex_returncode'] = ran.returncode
        record['RC'] = rc_netlist_inventory(netlist.read_text(), sim_name, circuit.ports); dump(output / 'physical.json', record)
        if ran.returncode or not record['RC']['has_real_RC']: return record
    record['corners'] = simulate(output, contract['bench_category'], sizes, sim_name, netlist, circuit.ports, contract, devices, solver)
    record['all_analyses_complete'] = all(row['complete'] for row in record['corners'].values())
    record['all_operating_points_valid'] = all(row['operating_point_valid'] for row in record['corners'].values())
    record['full_physical_analysis_complete'] = not prelayout and record['all_analyses_complete']
    dump(output / ('prelayout.json' if prelayout else 'physical.json'), record); return record
