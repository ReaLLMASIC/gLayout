"""Prepare a draft train capsule for a textbook domain only after its nine measured points pass (E4 stage 1)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.device_intent import compare_device_intent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--domain', required=True, help='declared domain id, e.g. C03 or C03_cfg1')
args = parser.parse_args(); domain = args.domain
qualification_path = ROOT / 'results/derived/textbook_train_domain_development_qualification.json'
qualification = json.loads(qualification_path.read_text())['circuits'][domain]
if not qualification.get('all_nine_points_ready'):
    raise ValueError('All nine actual points must qualify before creating the draft capsule of ' + domain)
table = json.loads((ROOT / 'configs/development' / (domain.lower() + '_family/configurations.json')).read_text())
cid = table['circuit_id']
anchor_contract = json.loads((ROOT / table['configurations'][0]['contract_file']).read_text())
constraints = anchor_contract['prospective_application_constraints']; category = table['bench_category']
# Prospective hard specifications: the textbook benchmark's qualified floors for this circuit, in this bench's metric names.
if category == 'mirror':
    specifications = [{'name': 'nominal_current_relative_error', 'unit': '1', 'max': constraints['nominal_current_relative_error_max']},
                      {'name': 'compliance_low_V', 'unit': 'V', 'max': constraints['compliance_low_V_max']}]
else:  # single and diff_r share the textbook gain / bandwidth floors
    specifications = [{'name': 'gain_lf_dB', 'unit': 'dB', 'min': constraints['gain_lf_dB_min']},
                      {'name': 'f3db_Hz', 'unit': 'Hz', 'min': constraints['f3db_Hz_min']}]
points = [point for point in qualification['points'] if point['qualified']]
audits = []
for point in points:
    run = Path(point['run_directory']); audit = compare_device_intent((run / 'evaluation/layout_lvs.spice').read_text(), (run / 'target.spice').read_text())
    audits.append({'configuration_id': point['configuration_id'], 'run_directory': str(run), 'audit': audit})
    if not audit['is_clean']: raise ValueError('Independent per-finger/terminal-graph qualification failed: ' + point['configuration_id'])
    for corner, metrics in point['corners'].items():
        for spec in specifications:
            value = metrics.get(spec['name'])
            if value is None or ('min' in spec and value < spec['min']) or ('max' in spec and value > spec['max']):
                raise ValueError('Draft application constraint is not feasible at ' + point['configuration_id'] + '/' + corner + '/' + spec['name'] + ' = ' + str(value))
descriptor = json.loads((ROOT / table['circuit_input_file']).read_text())
source = Path(json.loads((ROOT / 'runtime/train_collections/c01_collection_v1/collection.json').read_text())['source_pack'])
out = ROOT / 'runtime/collection_preparation' / (domain.lower() + '_collection_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
trusted = out / 'trusted'; (trusted / 'contracts').mkdir(parents=True); (trusted / 'references').mkdir()
shutil.copyfile(ROOT / 'scripts/corpus_textbook_collection_evaluator.py', trusted / 'evaluate.py')
shutil.copyfile(ROOT / 'src/corpus_textbook_benches.py', trusted / 'textbook_physical.py')
shutil.copyfile(ROOT / 'vendor/glayout/src/glayout/verification/run_pex.sh', trusted / 'run_pex.sh')
for name in ['physical_drc.py', 'report_parsers.py', 'spice_validation.py', 'measurement.py', 'corpus_metrics.py', 'device_intent.py']:
    target = trusted / 'src' / name; target.parent.mkdir(exist_ok=True); shutil.copyfile(ROOT / 'src' / name, target)
(trusted / 'src/__init__.py').write_text('')
configurations = []
for point in table['configurations']:
    identifier = point['configuration_id']; contract = json.loads((ROOT / point['contract_file']).read_text())
    contract.update(task_id='train_collection_' + domain.lower(), scope='DRAFT_AFTER_ACTUAL_NINE_POINT_QUALIFICATION', specifications=specifications,
                    numerical_controls={'integration_method': 'trap', 'tight_tolerances_unchanged': True},
                    power_definition=contract['nominal_operating_point']['power_definition'])
    contract.pop('pending_before_freeze', None)
    (trusted / 'contracts' / (identifier + '.json')).write_text(json.dumps(contract, indent=2) + '\n')
    shutil.copyfile(ROOT / point['reference_file'], trusted / 'references' / (identifier + '.spice'))
    configurations.append({'configuration_id': identifier, 'role': point['role'], 'reference_id': contract['reference_id'], 'contract': contract,
                           'parameters': {'configuration_id': identifier, 'circuit': descriptor, 'sizing': point['parameters']['sizing'], 'top_cell': 'corpus_' + cid.lower()}})
objective = configurations[0]['contract']['objective']
metadata = {'status': 'DRAFT_READONLY_COLLECTION_CAPSULE_NOT_FROZEN', 'circuit_id': domain, 'base_circuit_id': cid, 'development_domain_id': domain, 'bench_category': category,
            'source_revision': table['source_revision'], 'parent_lineage': table['parent_lineage'], 'source_pack': str(source),
            'source_files': sorted(str(path.relative_to(source)) for path in source.rglob('*') if path.is_file()), 'editable_paths': ['textbook_sharing/layout.py'],
            'trusted_bundle': str(trusted), 'trusted_files': sorted(str(path.relative_to(trusted)) for path in trusted.rglob('*') if path.is_file()),
            'configurations': configurations, 'qualification_path': str(qualification_path), 'qualification_device_intent_audits': audits,
            'prospective_hard_specifications': specifications, 'objective': objective,
            'label_rule_draft': {'objectives': {objective['id']: {'metric': 'area', 'unit': 'um2', 'direction': 'min', 'quality_absolute_tolerance': 1e-8, 'quality_relative_tolerance': 1e-6, 'quality_minimum_relative_effect': .01}}},
            'source_scope_note': 'Identical cropped universal compiler source; only full layout.py editable. Descriptor and sizing are backend configuration. These are not extra independent generator lineages.',
            'formal_collection_started': False, 'old_development_evidence_relabelled': False, 'requires_real_isolated_evaluator_smoke': True}
(out / 'preparation.json').write_text(json.dumps(metadata, indent=2) + '\n')
for path in sorted(out.rglob('*'), reverse=True): path.chmod(0o555 if path.is_dir() else 0o444)
out.chmod(0o555)
print(json.dumps({'preparation': str(out / 'preparation.json'), 'domain': domain, 'source_files': len(metadata['source_files']), 'trusted_files': len(metadata['trusted_files']), 'status': metadata['status']}))
