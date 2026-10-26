#!/usr/bin/env python3
"""Analyze only the new scope cohort's own index; reject all mixed old trials."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.analyze_e1 import analyze
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT


def scoped(manifest, rows):
    if manifest.get('cohort_id') != COHORT or manifest['budget'] != BUDGET:raise ValueError('Wrong analysis cohort')
    for row in rows:
        result = json.loads(Path(row['episode_json']).read_text())
        if (row.get('cohort_id') != COHORT or result.get('cohort_id') != COHORT
                or result.get('freeze_id') != manifest['freeze_id']):raise ValueError('Old/different trials cannot enter the new paired360 analysis')
    result = analyze(manifest, rows)
    result.update(cohort_id=COHORT, old_interface_cohort_included=False,
        limitation='A separate prospective16k documentation-qualified cohort; old partial8k interface runs are not silently pooled or replaced.')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--episode-index', type=Path, required=True);p.add_argument('--output', type=Path, required=True);a = p.parse_args()
    manifest = json.loads(a.manifest.read_text());rows = [json.loads(line) for line in a.episode_index.read_text().splitlines() if line.strip()]
    report = scoped(manifest, rows);a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'cohort_id': COHORT, 'planned': report['planned_episodes'], 'observed_status_counts': report['observed_status_counts']}))
