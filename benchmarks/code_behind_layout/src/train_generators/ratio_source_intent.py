"""Independent transistor intent and prior application contract, without layout."""

LINEAGE = 'research_train_ratio_current_source_array_v1'
CIRCUIT = 'TRAIN_RATIO_CS01'
K_VALUES = (2, 4, 8)
R_VALUES = (1, 2, 4)
PORTS = ('VSS', 'IREF', 'IOUT1', 'IOUT2')
DEVICES = (
    ('MREF', ('IREF', 'IREF', 'VSS', 'VSS')),
    ('MOUT1', ('IOUT1', 'IREF', 'VSS', 'VSS')),
    ('MOUT2', ('IOUT2', 'IREF', 'VSS', 'VSS')),
)


def point(k, ratio):
    if type(k) is not int or k not in K_VALUES or type(ratio) is not int or ratio not in R_VALUES:
        raise ValueError('Preserve the complete declared K=2/4/8 by R=1/2/4 domain')
    identifier = f'ratio_cs_k{k}_r{ratio}'
    sizing = {name: {'w': .5 * nf, 'l': .6, 'nf': nf}
              for name, nf in [('MREF', k), ('MOUT1', k), ('MOUT2', k * ratio)]}
    analyses = {'op': {'kind': 'op', 'columns': 5, 'expected_rows': 1}}
    for index in (1, 2):
        analyses['dc' + str(index)] = {'kind': 'dc', 'columns': 6, 'start': 0, 'end': 1.8,
                                        'points': 19, 'scale': 'linear'}
        analyses['ac' + str(index)] = {'kind': 'ac', 'columns': 5, 'start': 10, 'end': 1e9,
                                        'points': 161, 'scale': 'log'}
        analyses['tran' + str(index)] = {'kind': 'transient', 'columns': 7, 'start': 0, 'end': 4e-6,
            'required_windows': [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}
    specifications = []
    for branch, current_ratio in [(1, 1), (2, ratio)]:
        for name in ('nominal_current_relative_error', 'sampled_compliance_max_relative_error'):
            specifications.append({'name': f'branch{branch}_{name}', 'unit': '1', 'max': .05})
        specifications.append({'name': f'branch{branch}_output_resistance_ohm', 'unit': 'ohm',
                               'min': 300000 / current_ratio})
    specifications.append({'name': 'max_settled_relative_current_error_vs_DC', 'unit': '1', 'max': .001})
    return {'configuration_id': identifier, 'domain_role': 'anchor' if (k, ratio) == (4, 2) else 'development',
        'parameters': {'K': k, 'R': ratio, 'top_cell': identifier, 'sizing': sizing},
        'reference_file': 'references/' + identifier + '.spice',
        'contract': {'task_id': 'train_ratio_current_source_array_v1', 'configuration_id': identifier,
            'reference_id': identifier + '_independent_perfinger', 'status': 'DRAFT_UNMEASURED_PRIOR_SPECIFICATION',
            'required_corners': ['tt', 'ss', 'ff'], 'ports': list(PORTS),
            'nominal_operating_point': {'reference_supply_V': 1.8, 'temperature_C': 27,
                'reference_current_A': 5e-6, 'output_clamps_V': [.9, .9],
                'expected_output_currents_A': [5e-6, ratio * 5e-6],
                'DC_output_sweep_V': [0, 1.8, .1], 'AC_output_excitation_V': 1,
                'transient_output_levels_V': [.875, .925], 'transient_period_s': 2e-6,
                'other_output_during_single_port_analysis_V': .9},
            'specifications': specifications, 'analysis_contracts': analyses,
            'sampled_compliance_grid_V': [.7, .8, .9, 1.0],
            'output_resistance_difference_interval_V': [.8, 1.0],
            'settling_definition': 'Both branch currents during each single-output step are compared with that same port DC sweep, using linear interpolation between declared0.1V samples; error normalized by each branch target current.',
            'power_definition': 'DUT has noVDDpin. Report diode-input port work plus each output-clamp port work; report external1.8V/5uA reference-source work separately.',
            'specification_rationale': '5% current transfer/regulation over the declared sampled application band; Iout*ro>=1.5V for either current ratio;0.1% settled current error relative to corresponding DC controls. Thresholds fixed before any ideal or physical measurement.',
            'objective': {'id': 'ratio_cs_area_min', 'metric': 'area', 'unit': 'um2',
                          'direction': 'min', 'corner_aggregation': 'worst'},
            'numerical_controls': {'integration_method': 'trap', 'reltol': 1e-6, 'abstol': 1e-14,
                                   'vntol': 1e-8, 'chgtol': 1e-16},
            'scope': 'DRAFT_NEW_TRAIN_LINEAGE_QUALIFICATION_NOT_FORMAL_DATA'}}


def reference_spice(configuration):
    """Literal independent fingers; no call to any layout generator or compiler."""
    sizes = configuration['parameters']['sizing']; top = configuration['parameters']['top_cell']
    lines = ['.subckt ' + top + ' ' + ' '.join(PORTS)]
    for name, nets in DEVICES:
        size = sizes[name]
        for finger in range(size['nf']):
            lines.append(f"X{name}_f{finger} {' '.join(nets)} sky130_fd_pr__nfet_01v8 "
                         f"w={size['w']/size['nf']:g} l={size['l']:g}")
    return '\n'.join(lines + ['.ends ' + top, ''])
