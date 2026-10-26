"""Transparent visible-data selector signals; no learned failure probabilities.

The present train collection contains whole-program failures, not identifiable
configuration-dependent failure labels. Unavailable channels are zero-valued
placeholders and must have zero selection weight. Their values are not risk
probabilities. The remaining channels are declared heuristics, not calibration.
"""
import json
import math
from pathlib import Path


VERSION = 'visible_margin_distance_rule_v1'
DISABLED = ('failure_probability', 'changed_call_coverage')
STATUS_PREDICATES = ('original_development_predicate',)


def normalized_margin(contract, observation):
    """Worst signed relative distance to an actual frozen electrical limit.

    None means the complete required metric/corner set is unavailable. A zero
    bound needs an explicit positive margin_scale (or a finite two-sided span).
    Measurements and limits must use the same units; objectives are not limits.
    The explicitly named original_development_predicate is a required boolean
    feasibility gate, not a continuous electrical distance. Equal numeric bounds
    on every other metric still contribute their measured (possibly zero) margin.
    """
    corners = contract.get('required_corners', [])
    specifications = contract.get('specifications', [])
    if not corners or not specifications:
        return None
    margins = []
    for corner in corners:
        measured = observation.get('corners', {}).get(corner, {})
        if measured.get('converged') is not True or measured.get('operating_point_valid') is not True:
            return None
        for spec in specifications:
            metric = measured.get('metrics', {}).get(spec['name'], {})
            value = metric.get('value')
            if metric.get('unit') != spec['unit'] or type(value) not in (int, float) or not math.isfinite(value):
                return None
            if spec['name'] in STATUS_PREDICATES:
                if spec.get('unit')!='1' or spec.get('min')!=1 or spec.get('max')!=1 or value!=1:
                    return None
                continue
            bounds = [(key, spec[key]) for key in ('min', 'max') if key in spec]
            if not bounds:
                return None
            for key, bound in bounds:
                scale = spec.get('margin_scale', abs(bound))
                if not scale and 'min' in spec and 'max' in spec:
                    scale = spec['max'] - spec['min']
                if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
                    return None
                margins.append((value-bound)/scale if key == 'min' else (bound-value)/scale)
    return min(margins) if margins else None


class VisibleMarginDistanceRule:
    def __init__(self, artifact):
        if artifact.get('version') != VERSION or artifact.get('status') != 'TRANSPARENT_HEURISTIC_NOT_CALIBRATED_FAILURE_MODEL':
            raise ValueError('A reviewed transparent-rule artifact is required')
        if artifact.get('evaluation_outcomes_used') is not False or artifact.get('disabled_channels') != list(DISABLED):
            raise ValueError('Rule provenance or disabled channels differ')
        if artifact.get('continuous_margin_excluded_status_predicates') != list(STATUS_PREDICATES):
            raise ValueError('The exact frozen status-predicate margin declaration is required')
        self.artifact = artifact

    def predict(self, current_sources, episode_state, visible_configuration_parameters):
        # The interface receives sources for parity with future predictors. This
        # rule does not infer execution coverage or risk from source spelling.
        if not isinstance(current_sources, dict) or any(not isinstance(v, str) for v in current_sources.values()):
            raise ValueError('Complete visible sources must be a text map')
        weights = episode_state.get('weights') or {}
        if any(weights.get(key, 0) != 0 for key in DISABLED):
            raise ValueError('Unavailable probability/coverage channels must have zero weight')
        features = episode_state['features']
        if set(features) != set(visible_configuration_parameters):
            raise ValueError('Only the exact visible configuration pool may enter the rule')
        bounds = episode_state['bounds']
        if not bounds:
            raise ValueError('A declared visible numeric domain is required')
        vectors = {}
        for name, values in features.items():
            vector = []
            for key, (low, high) in bounds.items():
                value = values[key]
                if visible_configuration_parameters[name].get(key) != value or not low < high or not low <= value <= high:
                    raise ValueError('Visible features and parameters differ')
                vector.append((value-low)/(high-low))
            vectors[name] = vector
        def distance(a, b):
            return math.sqrt(sum((x-y)**2 for x,y in zip(vectors[a], vectors[b]))/len(bounds))
        revisions = episode_state['revisions']
        current = next(row for row in revisions if row['revision'] == episode_state['revision'])
        tested = list(current['results'])
        if not set(tested) <= set(vectors):
            raise ValueError('Hidden measurements cannot enter visible prediction')
        contract = episode_state.get('contract')
        contracts = episode_state.get('contracts_by_configuration')
        if contracts is not None and set(contracts) != set(vectors):
            raise ValueError('Per-point contracts must cover exactly the public configuration pool')
        margins = {}
        # Old measurements are explicit priors, never carried across an edit as
        # verification. Most recent valid actual measurement wins for each ID.
        if contract or contracts is not None:
            for revision in revisions:
                for name, point in revision['results'].items():
                    if name not in vectors:
                        raise ValueError('Hidden measurements cannot enter margin priors')
                    checked = point.get('checked', {})
                    if checked.get('execution_integrity') != 'valid' or checked.get('S1') is not True:
                        continue
                    point_contract = contracts[name] if contracts is not None else contract
                    value = normalized_margin(point_contract, point.get('physical_feedback', {}))
                    if value is not None:
                        margins[name] = value
        result = {}
        for name in sorted(vectors):
            novelty = min((distance(name, old) for old in tested), default=1.0)
            if margins:
                nearest = min(margins, key=lambda old: (distance(name, old), old))
                low_margin = 1/(1+max(0, margins[nearest]))
            else:
                low_margin = 0.0
            result[name] = {'failure_probability': 0.0, 'uncertainty': novelty,
                'changed_call_coverage': 0.0, 'low_margin': low_margin}
        return result


def load_frozen_predictor(path):
    return VisibleMarginDistanceRule(json.loads(Path(path).read_text()))
