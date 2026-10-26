"""Freeze a qualified C02/C07 domain for eight new ordinary ACTION proposals."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_training import load, packet
from src.local_model_adapter import decision_prompt
from src.measurement import validate_contract
from src.model_adapter import prompt_token_budget
from src.training import frozen_train_registry
from scripts.run_frozen_training_collection import load_definition


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def freeze(preparation, calibration):
    prep = json.loads(preparation.read_text())
    smoke = json.loads(calibration.read_text())
    cid=prep['circuit_id'];c02=cid=='C02'
    if (cid not in ['C02','C07'] or prep['qualification_control'] != ('C02__trap' if c02 else 'C07__trap__independent_inputs')
            or smoke['preparation_path'] != str(preparation.resolve()) or smoke['status'] != 'EVALUATED'
            or not smoke['assessment']['S2'] or not smoke['point_evaluation_complete']):
        raise ValueError('The declared component needs actual nine-point qualification and a final isolated evaluator smoke')
    baseline_path = ROOT / 'runtime/train_collections/c01_collection_v1/collection.json'
    base, registry, _, _ = load(baseline_path)
    if prep['source_pack'] != base['source_pack']:
        raise ValueError('The same frozen compiler source assignment must be retained')
    qualification = json.loads(Path(prep['qualification_path']).read_text())['circuits'][cid]
    qualified = {row['configuration_id']: row for row in qualification['points']
                 if row['domain_id'] == cid and row['solver'] == 'trap'
                 and row['independent_transient_inputs']==(not c02) and row['qualified']}
    if len(qualified) != 9 or len(prep['configurations']) != 9:
        raise ValueError('All nine fixed points must qualify before prospective collection')
    collection_id = cid.lower()+'_action_v1'
    output = ROOT / 'runtime/train_collections' / collection_id
    output.mkdir()
    trusted = output / 'trusted'
    shutil.copytree(prep['trusted_bundle'], trusted)
    for path in trusted.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    trusted.chmod(0o755)
    points, id_map, baseline = [], {}, {}
    for index, old in enumerate(prep['configurations']):
        previous = old['configuration_id']
        identifier = ('t2' if c02 else 't7') + chr(97 + index)
        id_map[previous] = identifier
        contract = json.loads(json.dumps(old['contract']))
        # Lossless metadata factoring: the identical power statement remains at
        # top level. All numerical bench definitions and analysis fields remain.
        power = contract['nominal_operating_point'].pop('power_definition')
        if power != contract['power_definition']:
            raise ValueError('Only an identical explanatory duplicate may be factored')
        contract.update(task_id=cid.lower(), configuration_id=identifier,
                        scope='frozen_prospective_train_collection_'+collection_id)
        validate_contract(contract)
        save(trusted / 'contracts' / (identifier + '.json'), contract)
        (trusted / 'contracts' / (previous + '.json')).unlink()
        (trusted / 'references' / (previous + '.spice')).rename(trusted / 'references' / (identifier + '.spice'))
        points.append({'configuration_id': identifier, 'parent_lineage': prep['parent_lineage'],
                       'split': 'train', 'role': 'train_development', 'domain_role': old['role'],
                       'reference_id': old['reference_id'], 'contract': contract,
                       'parameters': {**old['parameters'], 'configuration_id': identifier}})
        row = qualified[previous]
        baseline[identifier] = {'checked': {'S0': True, 'S1': True, 'S2': True, 'failure_class': None},
            'result': {'physical_result': {'observation': {'corners': {corner: {'metrics': {
                'area': {'value': row['area_um2'], 'unit': 'um2'}}} for corner in row['corners']}}}}}
    trusted_files = {str(path.relative_to(trusted)): path.read_text()
                     for path in sorted(trusted.rglob('*')) if path.is_file()}
    for point in points:
        point['trusted_evaluator_files'] = trusted_files
    registry.update(configurations=points, freeze_scope='unchanged_source_assignments_and_'+collection_id,
                    frozen_at_utc=datetime.now(timezone.utc).isoformat(), main_benchmark_protocol_status='draft')
    frozen_train_registry(registry)
    paths = ['glayout/sharing/enumeration.py'] if c02 else ['textbook_sharing/layout.py', 'glayout/sharing/enumeration.py']
    state = {'initial_state_id': 's0', 'task_id': cid.lower(), 'parent_lineage': prep['parent_lineage'],
             'origin': 'natural', 'editable_paths': paths,
             'base_source': {name: (Path(prep['source_pack']) / name).read_text() for name in paths},
             'ancestry': {'kind': 'unmodified_public_compiler', 'source_revision': prep['source_revision'],
                          'source_pack': prep['source_pack'], 'circuit_input_id': cid,
                          'same_compiler_program_as_C01_C05_C08': True,
                          'development_qualification_used_only_for_prospective_feasibility': True}}
    previous_interface = ROOT / ('runtime/train_collections/c01_enumeration_action_v1/interface' if c02 else 'runtime/train_collections/c01_planning_action_gpt_teacher_v1/interface')
    if not c02 and (previous_interface / 'collector.py').read_bytes() != (ROOT / 'scripts/collect_training.py').read_bytes():
        raise ValueError('Use the exact currently frozen ACTION collector and broker; no in-flight interface mutation')
    shutil.copytree(previous_interface, output / 'interface')
    if c02:
        for path in (output/'interface').rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)
        (output/'interface').chmod(0o755)
    labels = {**prep['label_rule_draft'], 'status': 'frozen', 'version': collection_id + '_area_v1',
              'coverage_absolute_tolerance': 0.0,
              'family_quality_aggregation': 'arithmetic_mean_of_same_unit_per_configuration_worst_corner_objectives'}
    template = json.loads((previous_interface.parent / 'collection.json').read_text())
    manifest = {**base, 'collection_id': collection_id, 'frozen_at_utc': registry['frozen_at_utc'],
        'registry_path': str(output / 'registry.json'), 'label_rule_path': str(output / 'label_rule.json'),
        'initial_states_path': str(output / 'initial_states.jsonl'), 'trusted_bundle': str(trusted),
        'output_root': str(ROOT / 'runs/train_collection' / collection_id),
        'evidence_root': str(ROOT / 'runs/train_collection' / collection_id),
        'sampling': template['sampling'], 'teacher_interface_version': template['teacher_interface_version'],
        'teacher_interface_path': str(output / 'interface'), 'budget_tokenizer_revision': template['budget_tokenizer_revision'],
        'student_preselection': template['student_preselection'], 'physical': {**base['physical'], 'workers': 1},
        'budget': {**base['budget'], 'initial_batch_initial_states': 1}, 'gold_controls': {},
        'transport': template['transport'], 'isolation': template['isolation'],
        'output_budget_scope': template['output_budget_scope'], 'deduplication': template['deduplication'],
        'main_benchmark_protocol_status': 'draft', 'source_smoke_evidence': smoke['run_directory'],
        'source_scope': 'Two complete original compiler modules, not an additional compiler lineage. Frozen per-point graph, W/L/nf, ports, external bias/load, reference and analyses.',
        'prospective_metadata_factoring': {'configuration_id_map': id_map, 'task_id': cid.lower(),
            'power_definition': 'One identical copy at top level replaces the duplicate nominal_operating_point statement. No numerical or physical definition changed.'},
        'admission': 'Fresh original baseline and independent gold control at every one of the nine points; eight fresh ordinary ACTION proposals; complete-domain physical and current device-intent re-admission; unchanged student1024/context8192. Development evidence never relabelled.',
        'source_program_counting': 'Same initial compiler AST as earlier circuit contexts. Report circuit-task contexts separately from unique program AST and compiler lineages.',
        'old_development_outcomes_admitted': False, 'formal_model_training_runs': 0}
    packet_function=packet
    if c02:
        import importlib.util
        spec=importlib.util.spec_from_file_location('_c02_action_packet',output/'interface/collector.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=ROOT
        packet_function=module.packet
        visible,_=packet_function(manifest,state,points,baseline)
        enum_template=json.loads((previous_interface/'teacher_packet_template.json').read_text())
        visible['goal']=enum_template['goal']
        for key in ['frozen_api','enumeration_api','frozen_layout_consumer']:
            visible['documents'][key]=enum_template['documents'][key]
        visible['documents']['frozen_api']=visible['documents']['frozen_api'].replace('earlier C01 collections','other qualified circuit contexts')
        save(output/'interface/teacher_packet_template.json',{'goal':visible['goal'],'documents':visible['documents']})
        manifest.update(teacher_packet_version='ordinary_action_enumeration_v1',frozen_collector_entrypoint='interface/collector.py',
            teacher_packet_template=str(output/'interface/teacher_packet_template.json'),editable_paths=paths,
            source_scope='One complete11,106B enumeration module plus complete public DeviceSpec/FingerRef/GateGroup/SharingPlan/independent_plan declarations. validate_plan is explicitly a frozen signature/docstring API; the layout consumer is frozen. Same original compiler program and lineage; applicable cascode current/ro/compliance contracts unchanged.',
            prospective_context_scope_change='The initial complete two-module+assemblyAPI context was8022+1024>8192 with0inference; preserve that unfrozen preparation. This independent scope edits the entire enumeration module and keeps the full layout module frozen, without truncating an editable core or physical contract.')
    task, history = packet_function(manifest, state, points, baseline)
    request = {'mode': 'train_collection_action_gpt', 'trial_id': 1,
               'request': {'task_packet': task, 'visible_history': history}}
    from transformers import AutoTokenizer
    cache = json.loads((ROOT / 'configs/training/backbone_cache.json').read_text())
    tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
    flight = prompt_token_budget(tokenizer, decision_prompt(request['request']),
                                 {'max_new_tokens': 1024, 'max_context_tokens': 8192})
    flight.update(model_inferences_issued=0, tokenizer_revision=cache['revision'],
                  source_files={name: {'bytes': len(text.encode()), 'whole_module': True}
                                for name, text in state['base_source'].items()},
                  baseline_scope='Actual development qualification only for prompt sizing; collection obtains all new baselines and recounts exactly before any proposal')
    if not flight['fits_with_full_output_reserve'] or flight['source_or_history_truncated']:
        save(output/'oversized_context_preflight.json',flight)
        raise ValueError('Complete component source/API and contract do not fit; no model inference permitted')
    save(output / 'registry.json', registry)
    save(output / 'label_rule.json', labels)
    save(output / 'preparation.json', prep)
    save(output / 'physical_calibration.json', smoke)
    save(output / 'teacher_context_preflight.json', flight)
    save(output / 'request_example.json', request)
    (output / 'exact_prompt.txt').write_text(decision_prompt(request['request']))
    (output / 'initial_states.jsonl').write_text(json.dumps(state, ensure_ascii=False) + '\n')
    manifest.update(teacher_context_preflight=str(output / 'teacher_context_preflight.json'),
                    request_example=str(output / 'request_example.json'))
    save(output / 'collection.json', manifest)
    names = sorted(str(path.relative_to(output)) for path in output.rglob('*') if path.is_file())
    save(output / 'freeze_identity.json', {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names})
    load_definition(output / 'collection.json')
    for path in sorted(output.rglob('*'), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {'collection': str(output / 'collection.json'), 'status': 'frozen', 'initial_states': 1,
            'planned_proposals': 8, 'prompt_tokens': flight['prompt_tokens'], 'output_reserve': 1024,
            'GPT_requests_at_freeze': 0, 'physical_workers': 1, 'new_gold_control_points_required': 9}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--calibration', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.preparation, args.calibration)))
