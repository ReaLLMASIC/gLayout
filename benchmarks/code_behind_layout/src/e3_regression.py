"""Join original and sealed-source measurements without treating unknown as failure."""


def summarize(points, original, selected):
    expected = {point['configuration_id']: point for point in points}
    if len(expected) != len(points):
        raise ValueError('The declared domain has duplicate configuration identities')

    def index(rows):
        result = {}
        for row in rows:
            ident = row['configuration_id']
            if ident not in expected or ident in result:
                raise ValueError('Outcome outside the declared domain or duplicate observation')
            result[ident] = row
        return result

    before, after = index(original), index(selected)
    groups = {}
    for role in ('anchor', 'development', 'hidden', 'all'):
        identifiers = [ident for ident, point in expected.items() if role == 'all' or point['role'] == role]
        known_original_passes = regressions = preserved = unknown_selected = unknown_original = 0
        for ident in identifiers:
            old, new = before.get(ident), after.get(ident)
            if old is None or old['checked']['execution_integrity'] != 'valid':
                unknown_original += 1
                continue
            if old['checked']['S2'] is not True:
                continue
            known_original_passes += 1
            if new is None or new['checked']['execution_integrity'] != 'valid':
                unknown_selected += 1
            elif new['checked']['S2'] is True:
                preserved += 1
            else:
                regressions += 1
        groups[role] = {'declared_configurations': len(identifiers),
            'original_verified_S2': known_original_passes, 'original_unknown': unknown_original,
            'preserved_original_S2': preserved, 'verified_regressions': regressions,
            'selected_unknown_on_original_passes': unknown_selected,
            'regression_rate': regressions/known_original_passes if known_original_passes and not unknown_selected and not unknown_original else None,
            'conditional_on_known_original_passes_identification_bounds':
                [regressions/known_original_passes, (regressions+unknown_selected)/known_original_passes]
                if known_original_passes else None}
    return {'status': 'COMPLETE' if not groups['all']['original_unknown'] and not groups['all']['selected_unknown_on_original_passes'] else 'INCOMPLETE_UNKNOWN',
        'groups': groups, 'hidden_point_records_exported': False,
        'scope': 'Regression requires a verified original S2 pass and an actual valid selected-source failure. Unknown and NOT_RUN never become failures; bounds are conditional, not confidence intervals.'}
