"""Finite all9point ideal qualification only; never generate GDS or model data."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, '/work')
from src.train_generators.ratio_source_intent import K_VALUES, R_VALUES, point, reference_spice
from src.train_generators.ratio_source_bench import simulate


def main():
    inputs = Path(os.environ['PROBE_INPUT']); output = Path.cwd()
    declaration = json.loads((inputs / 'domain.json').read_text())
    expected = [point(k, ratio) for k in K_VALUES for ratio in R_VALUES]
    if declaration['configurations'] != expected:
        raise ValueError('Keep the exact prior nine-point domain/contract; no successful-subset selection or threshold changes')
    for row in expected:
        reference = inputs / row['reference_file']
        if reference.read_text() != reference_spice(row):
            raise ValueError('An independently bound per-finger reference changed')
    result = {'status': 'RUNNING_FIXED_NINE_POINT_IDEAL_ATTEMPTS',
        'scope': 'development_new_train_source_ideal_only_not_S0_S1_S2_or_training_examples',
        'declared_points': 9, 'points': [], 'model_calls': 0, 'layout_runs': 0,
        'qualified_independent_source_lineages_added': 0, 'old_frozen_collections_modified': False}
    shutil.copyfile(inputs / 'domain.json', output / 'domain_snapshot.json')
    shutil.copyfile(inputs / 'lineage_declaration.json', output / 'lineage_snapshot.json')
    def save():
        (output / 'ideal_qualification.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    save()
    for row in expected:
        work = output / row['configuration_id']; work.mkdir()
        reference = work / 'independent_N.spice'
        shutil.copyfile(inputs / row['reference_file'], reference); reference.chmod(0o444)
        record = {'configuration_id': row['configuration_id'], 'configuration': row}
        try:
            corners = simulate(row, reference, work / 'analyses')
            record.update(status='RETURNED_IDEAL_ANALYSES', corners=corners,
                all_corners_complete=all(c['complete'] for c in corners.values()),
                all_corners_ideal_specs_pass=all(c['ideal_application_constraints_pass'] for c in corners.values()))
        except Exception as error:
            record.update(status='IDEAL_QUALIFICATION_UNESTABLISHED', error=type(error).__name__ + ': ' + str(error),
                          all_corners_complete=False, all_corners_ideal_specs_pass=False)
        result['points'].append(record); save()
    result.update(status='COMPLETED_FIXED_NINE_POINT_IDEAL_ATTEMPTS',
        qualified_points=sum(row['all_corners_ideal_specs_pass'] for row in result['points']),
        all_nine_ideal_qualified=all(row['all_corners_ideal_specs_pass'] for row in result['points']))
    save(); print(json.dumps({key: value for key, value in result.items() if key != 'points'}))


if __name__ == '__main__':
    main()
