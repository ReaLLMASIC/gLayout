"""Revision-bound verification and source selection for the E3 experiment.

This state has no model or physical oracle. The trusted episode gateway records
only actual completed measurements, and never carries a result across edits.
"""
import math
from src.regression_selector import RegressionSelector


def visible_features(points):
    """Use the public sizing values, excluding IDs and constant coordinates."""
    values = {p['configuration_id']: p['parameters'] for p in points}
    keys = sorted(set.intersection(*(set(row) for row in values.values())))
    numeric = [key for key in keys if all(type(row[key]) in (int, float)
        and math.isfinite(row[key]) for row in values.values())]
    bounds = {key: (min(row[key] for row in values.values()),
                    max(row[key] for row in values.values())) for key in numeric}
    bounds = {key: pair for key, pair in bounds.items() if pair[0] < pair[1]}
    if not bounds:
        raise ValueError('The visible domain needs a varying numeric sizing coordinate')
    return {name: {key: row[key] for key in bounds} for name, row in values.items()}, bounds


class EpisodeState:
    def __init__(self, method, points, seed, direction, weights=None):
        if direction not in ('min', 'max'):
            raise ValueError('Unknown objective direction')
        if any(p['role'] not in ('anchor', 'development') for p in points):
            raise ValueError('Hidden configurations cannot enter the search selector')
        anchors = [p['configuration_id'] for p in points if p['role'] == 'anchor']
        if len(anchors) != 1 or len({p['configuration_id'] for p in points}) != len(points):
            raise ValueError('Exactly one anchor and unique public configurations required')
        features, bounds = visible_features(points)
        # Check the actual selected method up front, including C's frozen weights.
        RegressionSelector(method, features, bounds, seed, weights)
        self.value = {'method': method, 'anchor': anchors[0], 'seed': seed,
            'features': features, 'bounds': bounds, 'weights': weights, 'direction': direction,
            'revision': 0, 'sealed': False, 'required_passes': [], 'counterexamples': [],
            'revisions': [{'revision': 0, 'results': {}}], 'selection_events': []}

    @classmethod
    def restore(cls, value):
        result = cls.__new__(cls)
        result.value = value
        return result

    def current(self):
        return self.value['revisions'][self.value['revision']]

    def new_revision(self):
        if self.value['sealed']:
            raise ValueError('The selected source is already sealed')
        self.value['revision'] += 1
        self.value['revisions'].append({'revision': self.value['revision'], 'results': {}})

    def next_configuration(self, predictions=None, excluded=()):
        if self.value['sealed']:
            raise ValueError('Sealed search cannot select more points')
        excluded = set(excluded)
        if not excluded <= set(self.value['features']):
            raise ValueError('Only public configurations may be deferred')
        results = self.current()['results']
        anchor = self.value['anchor']
        if anchor not in results:
            return anchor
        if self.value['method'] == 'A':
            return None
        # Recheck every previously exposed failure or passing regression anchor
        # after each edit. This conservative policy needs no guessed impact map.
        retained = set(self.value['counterexamples']) | set(self.value['required_passes'])
        pending = sorted(retained - set(results))
        if pending:
            return pending[0]
        # Seed depends only on this trial and revision, and the number of actual
        # current-revision measurements. Repeated status reads cannot spend RNG.
        seed = self.value['seed'] + 1009*self.value['revision'] + 9176*len(results)
        selector = RegressionSelector(self.value['method'], self.value['features'],
            self.value['bounds'], seed, self.value['weights'])
        # F3 may defer a new development point on its current source revision.
        # Deferral is neither a measured result nor permission to skip the
        # anchor or a retained check. Main F0 passes the empty set.
        return selector.choose(sorted(set(results) | excluded), predictions)

    def observe(self, point):
        if self.value['sealed']:
            raise ValueError('A sealed source cannot acquire search feedback')
        ident = point['configuration_id']
        if ident not in self.value['features']:
            raise ValueError('Hidden or unknown configuration in search feedback')
        if ident in self.current()['results']:
            raise ValueError('A revision/configuration measurement is never silently repeated')
        checked = point['checked']
        valid = checked['execution_integrity'] == 'valid'
        if not valid:
            # Incomplete transport/simulation/budget is not a reusable circuit
            # failure label, nor a reason to retry this point without reconciliation.
            raise ValueError('Incomplete physical execution requires explicit reconciliation')
        objective = point.get('objective')
        if checked['S2'] and (type(objective) not in (int, float) or not math.isfinite(objective)):
            raise ValueError('S2 needs the actual finite declared objective')
        self.current()['results'][ident] = point
        target = 'required_passes' if checked['S2'] else 'counterexamples'
        if ident not in self.value[target]:
            self.value[target].append(ident)

    def select_source(self):
        """Freeze a measured source, with explicit unverified fallback if none fit."""
        if self.value['sealed']:
            return self.value['selection']
        anchor = self.value['anchor']
        required = set(self.value['required_passes']) | set(self.value['counterexamples']) | {anchor}
        candidates = []
        for revision in self.value['revisions']:
            results = revision['results']
            if not all(name in results and results[name]['checked']['S2'] for name in required):
                continue
            # An empirical lower bound on visible coverage: untested points do
            # not become successes. Compare the same retained configuration set.
            count = sum(row['checked']['S2'] for row in results.values())
            measured = [results[name]['objective'] for name in required]
            quality = min(measured) if self.value['direction'] == 'max' else -max(measured)
            candidates.append((count, quality, -revision['revision'], revision['revision']))
        if candidates:
            chosen = max(candidates)[-1]
            established = True
        else:
            # The original complete source remains a reproducible fallback;
            # lack of budget is never called a verified reusable patch.
            chosen = 0
            established = False
        self.value['sealed'] = True
        self.value['selection'] = {'revision': chosen, 'retained_checks_established': established,
            'required_visible_checks': sorted(required), 'visible_domain_size': len(self.value['features']),
            'rule': 'all_retained_S2_then_verified_visible_count_then_worst_retained_objective_then_earliest_revision',
            'fallback': None if established else 'original_source_no_verified_patch'}
        return self.value['selection']
