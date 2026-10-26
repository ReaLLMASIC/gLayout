"""Summarize actual completed textbook train-domain qualification (E4 stage 1); never formal labels."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
batches = sorted((ROOT / 'runs/development/textbook_train_domain_qualification').glob('*/batch.json'))
states = [json.loads(batch.read_text()) for batch in batches]
jobs = [job for state in states for job in state['jobs'] if job.get('status') != 'RUNNING']
CIRCUITS = sorted({job['circuit_id'] for job in jobs})
result = {'scope': 'development_textbook_train_qualification_not_formal', 'batches': [{'path': str(path), 'status': state['status']} for path, state in zip(batches, states)],
          'circuits': {}, 'source_lineages': 1, 'formal_training_rows': 0}
for cid in CIRCUITS:
    controls = []; points = []
    for job in jobs:
        if job['circuit_id'] != cid: continue
        path = Path(job['run_directory']) / 'bench_result.json'
        if not path.exists(): path = Path(job['run_directory']) / 'evaluation/physical.json'
        raw = json.loads(path.read_text()) if path.exists() else {}
        row = {'configuration_id': job['configuration_id'], 'run_directory': job['run_directory'], 'returncode': job['returncode'],
               'analysis_complete': raw.get('all_analyses_complete', False), 'operating_points_valid': raw.get('all_operating_points_valid', False),
               'corners': {name: item['metrics'] for name, item in raw.get('corners', {}).items()}}
        if job['prelayout']: controls.append(row)
        else:
            row.update(full_physical_analysis_complete=raw.get('full_physical_analysis_complete', False), area_um2=raw.get('area_um2'),
                       DRC_clean=(raw.get('DRC') or {}).get('is_clean', False), LVS_clean=(raw.get('LVS') or {}).get('is_clean', False),
                       device_intent_clean=(raw.get('DeviceIntent') or {}).get('is_clean', False), positive_RC=(raw.get('RC') or {}).get('has_real_RC', False))
            row['qualified'] = all(row[key] for key in ['analysis_complete', 'operating_points_valid', 'full_physical_analysis_complete', 'DRC_clean', 'LVS_clean', 'positive_RC'])
            points.append(row)
    metrics = {name for point in points for values in point['corners'].values() for name, value in values.items() if type(value) in [int, float]}
    ranges = {name: {'min': min(values), 'max': max(values)} for name in sorted(metrics)
              if (values := [values[name] for point in points for values in point['corners'].values() if type(values.get(name)) in [int, float]])}
    qualified_ids = {point['configuration_id'] for point in points if point['qualified']}
    result['circuits'][cid] = {'schematic_controls': controls, 'actual_postlayout_attempts_completed': len(points), 'qualified_attempts': sum(point['qualified'] for point in points),
                               'unique_configurations_qualified': len(qualified_ids), 'all_nine_points_ready': len(qualified_ids) == 9,
                               'actual_metric_ranges': ranges, 'points': points, 'prospective_specs_frozen': False}
out = ROOT / 'results/derived/textbook_train_domain_development_qualification.json'; out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({cid: {key: value for key, value in result['circuits'][cid].items() if key not in ['points', 'schematic_controls', 'actual_metric_ranges']} for cid in result['circuits']}, indent=1))
