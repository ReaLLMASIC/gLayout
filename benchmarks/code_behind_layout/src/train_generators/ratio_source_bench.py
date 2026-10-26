"""Independent two-output current-source electrical qualification.

This module never imports a layout assembly. Both outputs have independently
driven DC/AC/transient controls; all data/log completeness is checked before
current accuracy, conductance, compliance or settling is measured.
"""
import math
from pathlib import Path
import subprocess

from src.spice_validation import validate_analysis


def analysis_decks(configuration, reference, corner):
    contract = configuration['contract']; parameters = configuration['parameters']
    if contract['ports'] != ['VSS', 'IREF', 'IOUT1', 'IOUT2']:
        raise ValueError('Reference terminal order differs from this declared bench')
    common = ['Independent ratio current-source qualification',
        '.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice ' + corner,
        '.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16',
        '.temp 27', '.include "' + str(reference) + '"',
        'VSUPPLY vdd 0 1.8', 'IBIAS vdd bias 5u',
        'XDUT 0 bias out1 out2 ' + parameters['top_cell']]
    result = {}
    for branch in (1, 2):
        for kind in ('ac', 'dc', 'tran'):
            name = kind + str(branch); sources = []
            for port in (1, 2):
                value = ('pulse(.875 .925 1u 10n 10n 1u 2u)' if kind == 'tran' and port == branch else '.9')
                if kind == 'ac':
                    value += ' ac ' + ('1' if port == branch else '0')
                sources.append(f'VOUT{port} out{port} 0 {value}')
            body = ['.control', 'set wr_vecnames', 'set wr_singlescale']
            if name == 'ac1':
                body += ['op', 'wrdata op.dat v(bias) i(vout1) i(vout2) i(vsupply)']
            if kind == 'ac':
                body += ['ac dec 20 10 1G', f'wrdata {name}.dat real(i(vout1)) imag(i(vout1)) real(i(vout2)) imag(i(vout2))']
            elif kind == 'dc':
                body += [f'dc VOUT{branch} 0 1.8 .1',
                    f'wrdata {name}.dat v(out{branch}) i(vout1) i(vout2) v(bias) i(vsupply)']
            else:
                body += ['tran 5n 4u',
                    f'wrdata {name}.dat v(out1) v(out2) i(vout1) i(vout2) v(bias) i(vsupply)']
            result[name] = '\n'.join(common + sources + body + ['quit', '.endc', '.end', ''])
    return result


def numeric_rows(path):
    return [[float(value) for value in line.split()] for line in Path(path).read_text().splitlines()[1:] if line.strip()]


def interpolate(x, rows, column):
    if x < rows[0][0] - 1e-12 or x > rows[-1][0] + 1e-12:
        raise ValueError('Settling control left the declared DC sweep')
    for left, right in zip(rows, rows[1:]):
        if left[0] - 1e-12 <= x <= right[0] + 1e-12:
            fraction = (x - left[0]) / (right[0] - left[0])
            return left[column] + fraction * (right[column] - left[column])
    raise ValueError('DC interpolation interval is absent')


def measure(configuration, data):
    """Input tables must already have passed their complete analysis contracts."""
    ratio = configuration['parameters']['R']; contract = configuration['contract']
    op, = data['op']; metrics = {}; targets = {1: 5e-6, 2: 5e-6 * ratio}
    valid = 0 < op[1] < 1.8 and op[2] < 0 and op[3] < 0
    nominal = 9
    for branch in (1, 2):
        dc = data['dc' + str(branch)]; column = branch + 1
        current = [-row[column] for row in dc]
        errors = [abs(value / targets[branch] - 1) for value in current]
        conductance = (current[10] - current[8]) / (dc[10][0] - dc[8][0])
        band = [errors[i] for i, row in enumerate(dc) if .7 - 1e-8 <= row[0] <= 1.0 + 1e-8]
        if len(band) != 4:
            raise ValueError('The four predeclared compliance samples are absent')
        lower = upper = nominal
        if errors[nominal] <= .05:
            while lower > 0 and errors[lower - 1] <= .05: lower -= 1
            while upper + 1 < len(errors) and errors[upper + 1] <= .05: upper += 1
            compliance = [dc[lower][0], dc[upper][0]]
        else:
            compliance = [None, None]
        ac_conductance = -data['ac' + str(branch)][0][1 if branch == 1 else 3]
        valid = valid and current[nominal] > 0 and conductance > 0 and ac_conductance > 0
        prefix = 'branch' + str(branch) + '_'
        metrics.update({prefix + 'nominal_current_A': current[nominal],
            prefix + 'nominal_current_relative_error': errors[nominal],
            prefix + 'sampled_compliance_max_relative_error': max(band),
            prefix + 'output_resistance_ohm': 1 / conductance if conductance > 0 else None,
            prefix + 'output_conductance_10Hz_S': ac_conductance,
            prefix + 'sampled_5percent_compliance_component_V': compliance,
            prefix + 'DC_sweep_relative_errors': [{'voltage_V': row[0], 'relative_error': error}
                                                for row, error in zip(dc, errors)]})
    settled = []
    for driven in (1, 2):
        dc = data['dc' + str(driven)]; transient = data['tran' + str(driven)]
        for start, end in contract['analysis_contracts']['tran' + str(driven)]['required_windows']:
            selected = [row for row in transient if start < row[0] < end]
            if not selected:
                raise ValueError('A required settled window is absent')
            for row in selected:
                for branch in (1, 2):
                    expected = -interpolate(row[driven], dc, branch + 1)
                    settled.append(abs(-row[branch + 2] - expected) / targets[branch])
    metrics.update(max_settled_relative_current_error_vs_DC=max(settled),
        input_bias_V=op[1], input_port_power_W=op[1] * 5e-6,
        output1_port_power_W=-.9 * op[2], output2_port_power_W=-.9 * op[3],
        DUT_total_port_power_W=op[1] * 5e-6 - .9 * (op[2] + op[3]),
        external_reference_supply_work_W=-1.8 * op[4])
    passed = valid
    for spec in contract['specifications']:
        value = metrics.get(spec['name'])
        passed = passed and (type(value) in (int, float) and math.isfinite(value) and
            ('min' not in spec or value >= spec['min']) and ('max' not in spec or value <= spec['max']))
    return {'operating_point_valid': bool(valid), 'metrics': metrics,
            'ideal_application_constraints_pass': bool(passed)}


def simulate(configuration, reference, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False); result = {}
    for corner in configuration['contract']['required_corners']:
        work = output / corner; work.mkdir(); (work / '.spiceinit').write_text('set ngbehavior=hsa\n')
        analyses = {}
        for name, source in analysis_decks(configuration, reference, corner).items():
            (work / (name + '.spice')).write_text(source)
            with (work / (name + '_console.log')).open('w') as log:
                ran = subprocess.run(['ngspice', '-b', '-o', name + '.log', name + '.spice'],
                    cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            analyses[name] = validate_analysis(work / (name + '.dat'), work / (name + '.log'),
                configuration['contract']['analysis_contracts'][name], ran.returncode)
            if name == 'ac1':
                analyses['op'] = validate_analysis(work / 'op.dat', work / 'ac1.log',
                    configuration['contract']['analysis_contracts']['op'], ran.returncode)
        complete = all(row['complete'] for row in analyses.values())
        result[corner] = {'analyses': analyses, 'complete': complete,
            **(measure(configuration, {name: numeric_rows(work / (name + '.dat')) for name in analyses}) if complete else
               {'operating_point_valid': False, 'metrics': {}, 'ideal_application_constraints_pass': False})}
    return result
