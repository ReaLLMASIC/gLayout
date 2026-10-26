"""Observed resource accounting and finite, quality-matched reuse comparison."""
import math


def observed(values):
    values = list(values)
    known = [value for value in values if value is not None]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in known):
        raise ValueError('Observed costs must be finite nonnegative measurements or null')
    return {'observed_sum': sum(known), 'known_records': len(known), 'unknown_records': len(values)-len(known),
        'complete_total': sum(known) if len(known) == len(values) else None}


def physical_stages(costs):
    """The stage CPU and its enclosing capsule preparation are distinct.

    Primitive generation is already included in capsule preparation. Wall sums
    are stage observations, never elapsed study wall time or allocated CPU time.
    """
    result = {}
    for name, row in costs.items():
        if 'physical_calls' not in row:
            continue
        missing = row.get('missing_CPU_records')
        cpu = row.get('waited_child_CPU_seconds')
        unresolved = row.get('unresolved_calls', 0)
        result[name] = {'physical_calls': row['physical_calls'],
            'observed_child_CPU_seconds': cpu, 'missing_CPU_records': missing,
            'unresolved_calls': unresolved,
            'complete_child_CPU_seconds': cpu if missing == 0 and unresolved == 0 else None,
            'stage_wall_seconds': row.get('stage_wall_seconds'),
            'capsule_preparation_CPU_seconds': row.get('capsule_preparation_CPU_seconds'),
            'capsule_preparation_wall_seconds': row.get('capsule_preparation_wall_seconds'),
            'primitive_CPU_seconds_already_in_capsule': row.get('primitive_geometry_CPU_seconds'),
            'primitive_not_added_again': row.get('primitive_geometry_is_subset_of_capsule_preparation') is True}
        if row.get('primitive_geometry_CPU_seconds', 0) and not result[name]['primitive_not_added_again']:
            raise ValueError('Primitive/capsule cost overlap must be explicit before summing CPU')
    return result


def quality_matched_reuse(comparison):
    """Consume an actual deployment-stream join, never a hidden-transfer vector.

    A row serves one arrived configuration and includes failed work/fallback in
    its cost. This computes an observed crossing only; it makes no stationary
    extrapolation and never exchanges CPU, GPU, wall or token units.
    """
    if comparison['protocol'] != 'deployment_stream':
        raise ValueError('Frozen-patch hidden transfer is not a deployment cost stream')
    measure = comparison['cost_measure']
    if measure not in ('CPU_seconds', 'GPU_allocated_seconds', 'end_to_end_wall_seconds'):
        raise ValueError('Use one measured resource axis without token or dollar conversion')
    quality = comparison['quality_contract']
    if quality.get('require_S2') is not True:
        raise ValueError('Deployment comparison requires the same actual S2 threshold')
    if 'objective_limit' in quality:
        definition = quality['objective'];limit = quality['objective_limit']
        if (definition['direction'] not in ('min', 'max') or not definition['metric'] or not definition['unit'] or
                type(limit) not in (float, int) or not math.isfinite(limit)):
            raise ValueError('Comparable quality needs a finite frozen objective threshold and direction/unit')
    upfront = comparison['shared_upfront']
    if set(upfront) != {'data_generation_filtering', 'training', 'patch_search'}:
        raise ValueError('Shared upfront costs must retain data, training and patch search separately')
    upfront_cost = observed(upfront.values())
    shared, instance = comparison['shared_arrivals'], comparison['instance_arrivals']
    if len(shared) != len(instance):
        raise ValueError('Cost comparison requires the same observed arrival prefix')
    rows = [];shared_total = upfront_cost['complete_total'];instance_total = 0
    shared_successes = instance_successes = 0;all_matched = True;crossing = None
    for ordinal, (left, right) in enumerate(zip(shared, instance)):
        if (left['arrival_ordinal'] != ordinal or right['arrival_ordinal'] != ordinal or
                left['configuration_binding'] != right['configuration_binding']):
            raise ValueError('Arrived N(z)/PDK/deck/configuration binding or order differs')
        def acceptable(row):
            if row['complete'] is not True:
                return None
            if type(row['S2']) is not bool:
                raise ValueError('A completed deployment requires an actual boolean S2 result')
            if row['S2'] is not True:
                return False
            if 'objective_limit' not in quality:
                return True
            definition = quality['objective'];value = row['objective']
            if row['objective_definition'] != definition or type(value) not in (float, int) or not math.isfinite(value):
                return None
            return value >= quality['objective_limit'] if definition['direction'] == 'max' else value <= quality['objective_limit']
        lquality, rquality = acceptable(left), acceptable(right)
        matched = lquality is not None and rquality is not None and lquality == rquality
        all_matched = all_matched and matched
        shared_successes += lquality is True;instance_successes += rquality is True
        lcost, rcost = left['cost'], right['cost']
        observed([lcost, rcost])
        shared_total = shared_total+lcost if shared_total is not None and lcost is not None else None
        instance_total = instance_total+rcost if instance_total is not None and rcost is not None else None
        saving = instance_total-shared_total if all_matched and shared_total is not None and instance_total is not None else None
        if crossing is None and saving is not None and saving > 0 and shared_successes > 0:
            crossing = ordinal+1
        rows.append({'arrivals': ordinal+1, 'quality_matched_prefix': all_matched,
            'shared_verified_successes': shared_successes, 'instance_verified_successes': instance_successes,
            'shared_cumulative_cost': shared_total, 'instance_cumulative_cost': instance_total,
            'positive_shared_saving': saving,
            'shared_cost_per_verified_success': shared_total/shared_successes if shared_total is not None and shared_successes else None,
            'instance_cost_per_verified_success': instance_total/instance_successes if instance_total is not None and instance_successes else None})
    if not rows:
        status = 'NO_OBSERVED_DEPLOYMENT_STREAM'
    elif not all_matched:
        status = 'QUALITY_NOT_MATCHED_OR_UNKNOWN'
    elif shared_total is None or instance_total is None:
        status = 'COST_INCOMPLETE'
    elif not shared_successes:
        status = 'NO_VERIFIED_SUCCESSES'
    else:
        status = 'OBSERVED_CROSSING' if crossing is not None else 'NO_OBSERVED_BREAK_EVEN'
    return {'status': status, 'cost_measure': measure, 'observed_arrivals': len(rows),
        'shared_upfront': upfront, 'observed_prefix_crossing_arrivals': crossing if all_matched else None,
        'future_break_even_estimate': None, 'stationarity_assumed': False, 'dollar_cost': None,
        'prefixes': rows, 'scope': 'Observed finite arrival-prefix comparison only; failed work and fallback remain charged. No success has undefined cost/success. No extrapolation or precise billing inferred.'}
