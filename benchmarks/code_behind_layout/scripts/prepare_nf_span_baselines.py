"""Freeze only the two NF-domain fresh18 baseline controls; zero model/EDA calls."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from src.train_span_proposer import teacher_request, proposal_prompt, mapping_proof
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from src.training import frozen_train_registry

CODE = ['scripts/prepare_nf_span_baselines.py', 'scripts/run_nf_span_baselines.py',
    'scripts/train_pair_nf_physical_qualification.py', 'scripts/audit_train_pair_nf_rc.py',
    *['src/'+name+'.py' for name in ['candidate_executor', 'domain_runner', 'training',
        'measurement', 'report_parsers', 'device_intent', 'spice_validation', 'model_adapter',
        'local_model_adapter', 'policy_state', 'student_interface', 'train_span_proposer']]]
SOURCES = ['textbook_sharing/layout.py', 'glayout/sharing/enumeration.py']


def read(path): return json.loads(Path(path).read_text())
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n'); temporary.replace(path)


def packet(collection, state, points, summaries, preview=False):
    circuit = points[0]['parameters']['circuit']; order = [d['name'] for d in circuit['devices']]
    first = points[0]['contract']
    contract = {'family': first['task_id'], 'topology': circuit['circuit_id']+' '+circuit['name'],
        'ports': circuit['ports'], 'devices': [{'name': d['name'], 'kind': d['kind'], 'nets_D_G_S_B': d['nets']} for d in circuit['devices']],
        'objective': first['objective'], 'constraints': first['specifications'], 'corners': first['required_corners'],
        'analysis_contracts': first['analysis_contracts'], 'nominal_bench': first['nominal_operating_point'],
        'power_definition': first['power_definition'], 'numerical_controls': first['numerical_controls'],
        'geometry_domain': {'device_order': order, 'columns': ['w_total_um','l_um','nf'],
            'points': [{'id': p['configuration_id'], 'role': p['domain_role'], 'device_values': [
                [p['parameters']['sizing'][name][key] for key in ('w','l','nf')] for name in order]} for p in points]},
        'immutable': 'All nine independent N(z), device graphs/sizes/ports, bias/load, PDK, testbenches, physical contracts and common libraries are fixed. Both complete provided modules may be edited.'}
    ordinary = {'task_packet': {'task_id': collection['collection_id']+'__'+state['initial_state_id'],
        'goal': 'Improve real GDS area while satisfying every predeclared physical constraint across the complete domain. Make only minimal necessary planning/layout changes; preserve APIs and unaffected source.',
        'contract': contract, 'allowed_paths': list(state['base_source']), 'visible_sources': state['base_source'],
        'documents': collection['documents'], 'visible_configurations': [p['configuration_id'] for p in points],
        'budget': {'decisions': 1, 'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}},
        'visible_history': [{'observation': {'status': 'development_preview_only' if preview else 'begin',
            'qualification_preview' if preview else 'actual_new_baseline': summaries}}]}
    teacher = teacher_request(ordinary); proof = mapping_proof(ordinary, teacher)
    return ordinary, teacher, proof


def preflight(tokenizer, ordinary, teacher):
    proof = mapping_proof(ordinary, teacher); student = proof.pop('ordinary_request')
    flights = {'teacher': prompt_token_budget(tokenizer, proposal_prompt(teacher), {'max_new_tokens': 3072, 'max_context_tokens': 16384}),
        'student': prompt_token_budget(tokenizer, decision_prompt(student), {'max_new_tokens': 1024, 'max_context_tokens': 16384})}
    if not all(item['fits_with_full_output_reserve'] for item in flights.values()):
        raise ValueError('Complete source/API/contract/feedback does not fit; no truncation or model request allowed')
    return {'token_counts': flights, 'mapping': proof, 'model_calls': 0, 'source_or_contract_truncated': False}


def prepare(output):
    from transformers import AutoTokenizer
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    cache = read(ROOT/'configs/training/backbone_cache.json')
    tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned Qwen tokenizer')
    hypothesis = read(ROOT/'results/derived/train_matched_nf_span_next16_DRAFT.json')['predeclared_identification_hypothesis']
    save(output/'hypothesis.json', hypothesis)
    collections = []
    for cid in ('C02','C07'):
        development = ROOT/'runtime/collection_preparation'/(cid.lower()+'_matched_pair_nf_after_full9_v1')
        qualified = read(development/'preparation.json')
        if (qualified['status'] != 'DRAFT_AFTER_ACTUAL_NINE_POINT_CURRENT_GATE_QUALIFICATION'
                or len(qualified['configurations']) != 9 or len(qualified['qualification_device_and_analysis_audits']) != 9
                or not all(r['S2'] for r in qualified['qualification_device_and_analysis_audits'])
                or qualified['full_RC_device_graph_audits']['matching_points'] != 9
                or qualified['full_RC_device_graph_audits']['quarantined_points']):
            raise ValueError('The entire unchanged development grid must already qualify; do not select a subset')
        qualification = read(Path(qualified['qualification_path']))
        old_plan = read(Path(qualification['preparation'])/'plan.json')
        parent_registry = read(old_plan['parent_frozen_registry'])
        lineage, = [r for r in parent_registry['lineages'] if r['lineage_id'] == qualified['parent_lineage']]
        if lineage['split'] != 'train' or lineage['editable_paths'] != SOURCES:
            raise ValueError('Keep the original train-only compiler assignment and two complete editable modules')
        source = Path(qualified['source_pack']); names = qualified['source_files']
        old_source = Path(qualification['records'][0]['result']['run_directory'])/'source'
        if set(names) != set(lineage['frozen_source_files'])|set(SOURCES) or any((source/name).read_bytes() != (old_source/name).read_bytes() for name in names):
            raise ValueError('Current full source capsule differs from actual qualified development source')
        folder = output/cid; folder.mkdir(); trusted = folder/'trusted'
        shutil.copytree(qualified['trusted_bundle'], trusted)
        files = {str(p.relative_to(trusted)): p.read_text() for p in trusted.rglob('*') if p.is_file()}
        points = []
        for original in qualified['configurations']:
            point = {'configuration_id': original['configuration_id'], 'parent_lineage': qualified['parent_lineage'],
                'split': 'train', 'role': 'train_development', 'domain_role': original['role'],
                'reference_id': original['contract']['reference_id'], 'parameters': original['parameters'],
                'contract': original['contract'], 'trusted_evaluator_files': files}
            if read(trusted/'contracts'/(point['configuration_id']+'.json')) != point['contract']:
                raise ValueError('Independent qualified contracts changed')
            points.append(point)
        registry = {**parent_registry, 'status': 'frozen', 'freeze_scope': 'same_source_assignment_and_exact_NF_baseline_contracts_only',
            'configurations': points, 'new_global_registry_revision': False}
        frozen_train_registry(registry); save(folder/'registry.json', registry)
        state = {'initial_state_id': cid.lower()+'_nf_original_compiler_v1', 'parent_lineage': qualified['parent_lineage'],
            'task_id': points[0]['contract']['task_id'], 'origin': 'natural', 'editable_paths': SOURCES,
            'base_source': {name: (source/name).read_text() for name in SOURCES},
            'ancestry': qualified['initial_states'][0]['ancestry']}
        save(folder/'initial_state.json', state)
        template = read(ROOT/'runtime/train_collections'/(cid.lower()+'_planning_trajectories_context_v2/interface/teacher_packet_template.json'))
        documents = copy.deepcopy(template['documents'])
        if 'frozen_layout_consumer' in documents:
            documents['frozen_layout_consumer'] = 'Both complete layout.py and enumeration.py are editable. Preserve their public build and planning APIs, return types and physical device intent. All external compiler/assembly/PDK libraries remain frozen.'
        collection = {'status': 'DRAFT_WAITING_FRESH_FORMAL18_AND_NF_TEACHER_FREEZE', 'role': 'prospective_nf_span_train_collection',
            'collection_id': cid.lower()+'_matched_nf_span_v1', 'circuit_id': cid, 'source_pack': str(source),
            'source_files': names, 'trusted_bundle': str(trusted), 'registry_path': str(folder/'registry.json'),
            'initial_state_path': str(folder/'initial_state.json'), 'documents': documents,
            'pdk_revision': old_plan['pdk_revision'], 'container_image': old_plan['container_image'], 'magic_runtime': old_plan['magic_runtime'],
            'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'seed': None,
                'trials': list(range(1,9)), 'max_context_tokens': 16384, 'max_new_tokens': 3072, 'timeout_seconds': 240},
            'student': {'max_context_tokens': 16384, 'max_new_tokens': 1024},
            'new_independent_ASTs': 0, 'new_lineages': 0, 'historical_contract_scope_retained_verbatim': True,
            'teacher_dispatch': 'Forbidden until all18 fresh baselines/current gate and exact actual-feedback preflight pass, new NF-specific bundle freezes, and root drains the existing8122. This is not accepted by the existing fixed old16 loader.'}
        parent_labels = read(ROOT/'runtime/train_collections'/(cid.lower()+'_planning_trajectories_context_v2/label_rule.json'))
        save(folder/'parent_label_rule.json', parent_labels); save(folder/'collection.json', collection)
        summaries = [{'configuration_id': point['configuration_id'], 'S0': row['S0'], 'S1': row['S1'], 'S2': row['S2'],
            'objective': row['objective'], 'failure_class': row.get('failure_class'), 'reason': row.get('reason')}
            for point, row in zip(points, qualified['qualification_device_and_analysis_audits'])]
        ordinary, teacher, _ = packet(collection, state, points, summaries, True)
        save(folder/'preview_ordinary_request.json', ordinary); save(folder/'preview_teacher_request.json', teacher)
        flight = preflight(tokenizer, ordinary, teacher)
        flight.update(feedback_scope='Actual development qualification summaries only for preview sizing; never formal baseline labels or teacher requests', actual_formal_feedback_recount_required=True)
        save(folder/'preview_token_preflight.json', flight)
        collections.append({'circuit_id': cid, 'folder': str(folder), 'configuration_ids': [p['configuration_id'] for p in points]})
    for name in CODE:
        target = output/'code'/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, target)
    plan = {'status': 'FROZEN_NF_FRESH18_BASELINE_ONLY', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'collections': collections, 'CODE': CODE, 'phase': 'formal_train', 'workers': 1, 'CPUs': 2, 'memory_GiB': 8,
        'dispatch_horizon_seconds': 14400, 'maximum_new_full_points': 18, 'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720,
        'resource_gate': {'busy_plus_2_max': 24, 'RAM_used_GiB_max': 190, 'root_free_GiB_min': 4},
        'new_model_calls': 0, 'development_evidence_relabelled': False, 'automatic_retry': False,
        'output_root': str(ROOT/'runs/train_collection/nf_span_fresh18_v1'), 'teacher_collections_status': 'DRAFT',
        'new_ASTs': 0, 'new_lineages': 0, 'hypothesis_path': str(output/'hypothesis.json')}
    save(output/'baseline_plan.json', plan)
    save(output/'freeze_identity.json', {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(output.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': plan['status'], 'plan': str(output/'baseline_plan.json'), 'collections': collections,
        'preview_preflights': {c['circuit_id']: read(Path(c['folder'])/'preview_token_preflight.json')['token_counts'] for c in collections},
        'model_calls': 0, 'new_physical_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(p.parse_args().output), indent=2), flush=True)
