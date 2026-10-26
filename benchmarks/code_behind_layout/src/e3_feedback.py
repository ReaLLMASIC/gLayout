"""Lossless table encoding of repeated corner metric names and physical units."""
import copy


def public_checked(checked):
    """Keep verification outcomes; raw report inventories remain on the backend.

    Electrical measurements, units and corners belong to physical_feedback.
    Repeated host filenames and per-analysis parser inventories do not add a
    measurement and are retained in the complete private point record.
    """
    names = ('S0', 'S1', 'S2', 'execution_integrity', 'failure_class', 'reason',
             'analysis_complete', 'numerical_failure_established')
    return {name: copy.deepcopy(checked[name]) for name in names if name in checked}


def compact(feedback):
    result = copy.deepcopy(feedback)
    corners = result.get('corners', {})
    if not corners:
        return result
    names = sorted(next(iter(corners.values())).get('metrics', {}))
    if not names:
        return result
    units = None
    rows = {}
    for corner, values in corners.items():
        metrics = values.get('metrics', {})
        if sorted(metrics) != names or any(set(metrics[name]) != {'value', 'unit'} for name in names):
            return copy.deepcopy(feedback)
        current = [metrics[name]['unit'] for name in names]
        if units is not None and current != units:
            return copy.deepcopy(feedback)
        units = current
        rows[corner] = {'state': {key: value for key, value in values.items() if key != 'metrics'},
            'values': [metrics[name]['value'] for name in names]}
    result.pop('corners')
    result['corner_metric_table'] = {'metric_names': names, 'metric_units': units, 'corners': rows,
        'encoding': 'lossless_all_metrics_all_corners_v1'}
    return result


def expand(feedback):
    result = copy.deepcopy(feedback)
    table = result.pop('corner_metric_table', None)
    if table is None:
        return result
    if table['encoding'] != 'lossless_all_metrics_all_corners_v1':
        raise ValueError('Unknown physical-feedback table encoding')
    result['corners'] = {}
    for corner, row in table['corners'].items():
        if len(row['values']) != len(table['metric_names']) or len(row['values']) != len(table['metric_units']):
            raise ValueError('Metric names, units and measurements differ in length')
        result['corners'][corner] = {**row['state'], 'metrics': {
            name: {'value': value, 'unit': unit} for name, unit, value in
            zip(table['metric_names'], table['metric_units'], row['values'])}}
    return result
