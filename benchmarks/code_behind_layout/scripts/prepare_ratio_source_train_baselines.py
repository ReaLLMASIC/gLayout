"""Prepare a new ratio train task and freeze only its fresh nine baseline calls."""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src.train_generators.ratio_source_intent import LINEAGE, DEVICES, K_VALUES, R_VALUES, point, reference_spice
from src.training import frozen_train_registry
from src.candidate_executor import IMAGE

EDITABLE = 'src/train_generators/ratio_source.py'
PDK = '0fe599b2afb6708d281543108caf8310912f54af'
CODE = ['scripts/prepare_ratio_source_train_baselines.py', 'scripts/run_ratio_source_train_baselines.py',
    'scripts/ratio_source_train_evaluator.py', 'scripts/ratio_source_physical_probe.py',
    'scripts/ratio_source_physical_qualification.py',
    *['src/' + name + '.py' for name in ('candidate_executor', 'domain_runner', 'training', 'measurement',
       'report_parsers', 'device_intent', 'spice_validation', 'model_adapter', 'local_model_adapter',
       'policy_state', 'student_interface', 'train_span_proposer')]]


def read(path): return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'); pending.replace(path)


def packet(initial, points, summaries, preview=False):
    first = points[0]['contract']
    task = {'task_id': 'ratio_source_area_train_v1__natural_source_v3',
        'goal': 'Reduce real GDS bounding-box area while preserving every original physical constraint across the entire nine-point domain. Edit the complete provided assembly source using minimal necessary layout changes. Preserve public APIs and unaffected source.',
        'contract': {'family': first['task_id'], 'ports': first['ports'],
            'devices': [{'name': name, 'model': 'sky130_fd_pr__nfet_01v8', 'nets_D_G_S_B': list(nets)} for name, nets in DEVICES],
            'objective': first['objective'], 'constraints': first['specifications'],
            'branch2_output_resistance_rule_ohm': '300000/R; branch1 remains300000',
            'target_current_rule_A': {'branch1': '5e-6', 'branch2': '5e-6*R'},
            'corners': first['required_corners'], 'nominal_bench': first['nominal_operating_point'],
            'analysis_contracts': first['analysis_contracts'], 'numerical_controls': first['numerical_controls'],
            'sampled_compliance_grid_V': first['sampled_compliance_grid_V'],
            'power_definition': first['power_definition'],
            'geometry_domain': [{'id': p['configuration_id'], 'role': p['domain_role'],
                'K': p['parameters']['K'], 'R': p['parameters']['R'], 'sizing': p['parameters']['sizing']}
                for p in points],
            'immutable': 'All device graphs, per-finger dimensions/counts/body nodes, references, ports, biases, stimuli, solver, specifications, common primitive and terminal helpers are frozen. Placement, margin, route policy and width inside this one complete assembly module may change.'},
        'allowed_paths': [EDITABLE], 'visible_sources': initial['base_source'],
        'documents': {
            'frozen_terminal_access_source': initial['frozen_terminal_access_source'],
            'primitive_api': 'from glayout import sky130; from glayout.primitives.fet import nmos. Preserve per-finger width .5um,length .6um, fingers K/K/K*R,with_dummy=False,with_tie=True,with_dnwell=False. build(configuration) returns the component; write_gds(configuration,output) emits its named GDS. Existing imports and all helpers stay frozen.',
            'layout_units': 'Coordinates and widths are um; construction grid .005um. Generic met3 is physical69/20(Metal2),met4 physical70/20(Metal3),met5 physical71/20(Metal4). Keep real connected landing enclosures and independent named pins.',
            'patch_format': 'Future collection uses one ordinary propose_patch ACTION_JSON. Complete editable source is provided. No patch repair, omitted code, circuit resizing, library edits or reverse-injected faults.'},
        'visible_configurations': [p['configuration_id'] for p in points],
        'budget': {'decisions': 1, 'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}}
    return {'task_packet': task, 'visible_history': [{'observation': {
        'status': 'development_qualification_preview_only' if preview else 'begin',
        'qualification_preview' if preview else 'actual_new_baseline': summaries}}]}


def token_preflight(request):
    from transformers import AutoTokenizer
    from src.local_model_adapter import decision_prompt
    from src.model_adapter import prompt_token_budget
    from src.train_span_proposer import teacher_request, proposal_prompt, mapping_proof
    cache = read(ROOT / 'configs/training/backbone_cache.json')
    tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Pinned Qwen tokenizer differs')
    teacher = teacher_request(request); proof = mapping_proof(request, teacher)
    student = proof.pop('ordinary_request')
    flights = {
        'ordinary_student': prompt_token_budget(tokenizer, decision_prompt(student), {'max_new_tokens': 1024, 'max_context_tokens': 16384}),
        'literal_span_teacher_DRAFT': prompt_token_budget(tokenizer, proposal_prompt(teacher), {'max_new_tokens': 3072, 'max_context_tokens': 16384})}
    if not all(f['fits_with_full_output_reserve'] for f in flights.values()):
        raise ValueError('Complete source/contracts/feedback do not fit; do not truncate')
    return {'token_counts': flights, 'mapping': proof, 'model_calls': 0,
            'source_or_contract_truncated': False}, teacher


def validate_assembly(source):
    allowed = {'gdsfactory', 'glayout', 'glayout.primitives.fet', 'src.generators.terminal_access',
               'argparse', 'json', 'sys', 'pathlib'}
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    if not imports.issubset(allowed): raise ValueError('Ratio assembly imports an undeclared dependency')
    return sorted(imports)


def prepare(output, qualification, durable_receipt):
    from scripts.materialize_e1_packets import generic_pack
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    qualification, durable_receipt = Path(qualification), Path(durable_receipt)
    qualified = read(qualification); durable = read(durable_receipt)
    if (qualified['actual_complete_S2_points'] != 9 or qualified['unknown_points'] != 0
            or qualified['total_complete_raw_analysis_contracts'] != 189
            or not qualified['unchanged_N_bench_domain_spec']
            or durable['status'] != 'DURABLE_LOCAL_BACKUP_ALL_MEMBERS_VERIFIED'
            or durable['qualified_development_points'] != 9 or durable['previous_failed_points_preserved'] != 18):
        raise ValueError('Whole-domain development qualification and verified persistent backup are required')
    expected = [point(k, ratio) for k in K_VALUES for ratio in R_VALUES]
    if qualified['fixed_order'] != [p['configuration_id'] for p in expected]:
        raise ValueError('Do not select a successful subset of the nine-point domain')
    for row, p in zip(qualified['records'], expected):
        raw = Path(row['run_directory'])
        if read(raw / 'configuration.json') != p or (raw / 'independent_N.spice').read_text() != reference_spice(p):
            raise ValueError('Actual development N/configuration differs from the original domain')
        for name in [EDITABLE, 'src/train_generators/ratio_source_intent.py',
                     'src/train_generators/ratio_source_bench.py', 'src/generators/terminal_access.py']:
            if (raw / 'source_snapshot' / name).read_bytes() != (ROOT / name).read_bytes():
                raise ValueError('Actual qualified source/N/bench/common access changed: ' + name)
    pack = output / 'source_pack'; generic_pack(pack)
    (pack / 'src/generators').mkdir(parents=True); (pack / 'src/train_generators').mkdir(parents=True)
    for name in ['src/__init__.py', 'src/generators/__init__.py', 'src/generators/terminal_access.py',
                 'src/train_generators/__init__.py', EDITABLE]:
        shutil.copyfile(ROOT / name, pack / name)
    (pack / 'generator.py').write_text("import argparse,json,shutil,sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent))\nfrom src.train_generators.ratio_source import write_gds\np=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()\ntmp=Path('/tmp/ratio_generated');tmp.mkdir()\ngds=write_gds(json.loads(Path(a.configuration).read_text()),tmp)\nshutil.copyfile(gds,a.output)\n")
    source_files = sorted(str(p.relative_to(pack)) for p in pack.rglob('*') if p.is_file())
    if any('/cells/' in p or '/blocks/' in p or '/sharing/' in p or 'textbook_sharing' in p for p in source_files):
        raise ValueError('Source capsule contains a circuit assembly or training compiler')
    imports = validate_assembly((pack / EDITABLE).read_text())
    trusted = output / 'trusted'; (trusted / 'points').mkdir(parents=True); (trusted / 'references').mkdir()
    (trusted / 'src').mkdir(); (trusted / 'src/__init__.py').write_text('')
    for name in ['physical_drc.py', 'report_parsers.py', 'device_intent.py', 'measurement.py', 'spice_validation.py']:
        shutil.copyfile(ROOT / 'src' / name, trusted / 'src' / name)
    shutil.copyfile(ROOT / 'scripts/ratio_source_train_evaluator.py', trusted / 'evaluate.py')
    shutil.copyfile(ROOT / 'src/train_generators/ratio_source_bench.py', trusted / 'original_bench.py')
    physical = (ROOT / 'scripts/ratio_source_physical_probe.py').read_text(); tree = ast.parse(physical)
    names = {'contracted_rc_devices', 'physical_wrapper', 'completed_corner_summary'}
    (trusted / 'physical_helpers.py').write_text('import re\n\n' + '\n\n'.join(ast.get_source_segment(physical, node)
        for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names) + '\n')
    for p in expected:
        save(trusted / 'points' / (p['configuration_id'] + '.json'), p)
        (trusted / p['reference_file']).write_text(reference_spice(p))
    trusted_files = {str(p.relative_to(trusted)): p.read_text() for p in trusted.rglob('*') if p.is_file()}
    parent_path = ROOT / 'data/splits/registry.json'; parent = read(parent_path)
    if any(row['lineage_id'] == LINEAGE for row in parent['lineages']):
        raise ValueError('This new prospective lineage is already assigned; inspect before preparing again')
    assignment = {'lineage_id': LINEAGE, 'split': 'train', 'topology_family': 'ratio_current_source_array',
        'topology_families': ['diode_biased_two_output_ratio_current_source_array'],
        'editable_paths': [EDITABLE], 'frozen_source_pack': str(pack),
        'frozen_source_files': [p for p in source_files if p != EDITABLE],
        'source': EDITABLE, 'parent_lineages': [],
        'assignment_scope': 'Prospective train-only baseline task; global registry extension pending fresh9 and root acceptance'}
    registry = {**parent, 'status': 'frozen', 'lineages': parent['lineages'] + [assignment], 'configurations': []}
    for p in expected:
        registry['configurations'].append({**p, 'parent_lineage': LINEAGE, 'split': 'train', 'role': 'train_development',
            'reference_id': p['contract']['reference_id'], 'pdk_revision': PDK,
            'editable_paths': [EDITABLE], 'lineage_editable_paths': [EDITABLE],
            'frozen_source_files': assignment['frozen_source_files'], 'frozen_source_pack': str(pack),
            'trusted_evaluator_files': trusted_files, 'intent_reference_path': p['reference_file']})
    frozen_train_registry(registry)
    if registry['lineages'][:-1] != parent['lineages']: raise ValueError('Prior assignments changed')
    save(output / 'parent_registry_snapshot.json', parent); save(output / 'baseline_registry.json', registry)
    initial = {'initial_state_id': 'ratio_natural_source_v3', 'parent_lineage': LINEAGE,
        'task_id': expected[0]['contract']['task_id'], 'origin': 'natural', 'editable_paths': [EDITABLE],
        'base_source': {EDITABLE: (pack / EDITABLE).read_text()},
        'frozen_terminal_access_source': (pack / 'src/generators/terminal_access.py').read_text(),
        'ancestry': 'Actual sourcev3 after two documented high-level DRC repairs; no injected or reverse-derived fault. Same primitive and terminal-access library is shared with evaluation/validation, but no circuit assembly, target helper or universal compiler is imported/copied.'}
    save(output / 'initial_state.json', initial)
    ancestry = {'status': 'DRAFT_PROSPECTIVE_TRAIN_ASSIGNMENT', 'lineage_id': LINEAGE,
        'prior_assignments_preserved_exactly': True, 'new_global_registry_revision': False,
        'independent_generator_claim': 'One separately authored three-bank placement/H bias-tree logic; nine K/R configurations are one source and one circuit task.',
        'shared_common_dependencies': ['MOS/via/PDK/elementary routing utilities', 'src/generators/terminal_access.py',
            'generic_pack source-copy utility; no target code enters the package'],
        'source_imports': imports, 'source_files': source_files,
        'excluded_circuit_sources': ['all evaluation/validation assemblies', 'all glayout.cells/blocks', 'public universal compiler'],
        'frozen_common_source_overlap_disclosed': True,
        'topology_holdout_statement': 'No Miller/FVF graph/helper/data; current mirrors are already represented in other splits, so no current-mirror topology holdout is claimed.',
        'qualified_new_lineages_reported': 0, 'activation_requires': 'All fresh formal_train9 baselines plus accepted global registry amendment; future model/rule/labels collection needs its own freeze.'}
    save(output / 'source_assignment_DRAFT.json', ancestry)
    summaries = [{'configuration_id': r['configuration_id'], 'S0': r['S0'], 'S1': r['S1'], 'S2': r['S2'],
        'objective': None, 'failure_class': None, 'scope': 'development preview; not fresh formal labels'} for r in qualified['records']]
    request = packet(initial, expected, summaries, preview=True)
    flight, teacher = token_preflight(request)
    flight.update(actual_formal_feedback_recount_required=True, future_collection_frozen=False)
    save(output / 'task_DRAFT.json', request['task_packet']); save(output / 'preview_ordinary_request.json', request)
    save(output / 'preview_teacher_request_DRAFT.json', teacher); save(output / 'preview_token_preflight.json', flight)
    shutil.copyfile(qualification, output / 'development_qualification.json')
    shutil.copyfile(durable_receipt, output / 'durable_backup_receipt.json')
    plan = {'status': 'FROZEN_RATIO_FRESH9_BASELINE_ONLY', 'phase': 'formal_train', 'workers': 1,
        'CPUs': 2, 'memory_GiB': 8, 'maximum_new_full_points': 9, 'dispatch_horizon_seconds': 14400,
        'fixed_order': [p['configuration_id'] for p in expected], 'source_pack': str(pack), 'source_files': source_files,
        'trusted_bundle': str(trusted), 'trusted_files': sorted(trusted_files), 'editable_paths': [EDITABLE],
        'lineage_id': LINEAGE, 'PDK_revision': PDK, 'container_image': IMAGE, 'magic_runtime': str(ROOT / 'runtime/magic-8.3.685'),
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 900,
        'resource_gate': {'busy_plus_2_max': 24, 'RAM_used_GiB_max': 190, 'root_free_GiB_min': 4},
        'CODE': CODE, 'output_root': str(ROOT / 'runs/train_collection/ratio_source_fresh9_v1'),
        'automatic_retry': False, 'unknown_stops_future_dispatch': True, 'new_model_calls': 0,
        'development_evidence_relabelled': False, 'future_rule_GPT_labels_status': 'DRAFT_NOT_DISPATCHABLE',
        'global_registry_modified': False, 'created_at_utc': datetime.now(timezone.utc).isoformat()}
    for name in CODE:
        target = output / 'code' / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    save(output / 'baseline_plan.json', plan)
    save(output / 'freeze_identity.json', {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(output.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': plan['status'], 'plan': str(output / 'baseline_plan.json'), 'preview_preflight': flight,
        'maximum_new_full_points': 9, 'new_model_or_physical_calls': 0, 'future_collection_status': 'DRAFT'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--durable-receipt', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(prepare(args.output, args.qualification, args.durable_receipt), indent=2), flush=True)
