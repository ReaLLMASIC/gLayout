"""Future TRAIN context DRAFT: disclose the entire frozen actual generator caller."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_ratio_source_train_baselines import read, save, token_preflight, EDITABLE
from scripts.run_ratio_source_train_baselines import load


def add_caller(request, caller):
    if request['task_packet']['allowed_paths'] != [EDITABLE]:
        raise ValueError('The generator caller must remain frozen, outside the single editable module')
    result = json.loads(json.dumps(request))
    result['task_packet']['documents']['frozen_generator_entrypoint_source'] = caller
    result['task_packet']['documents']['caller_scope'] = (
        'The complete generator.py above is the actual immutable entrypoint in the candidate container. '
        'Its exact configuration and call chain apply to all nine points. It is documentation only and is not editable.')
    return result


def prepare(plan_path, output):
    plan_path = Path(plan_path).resolve(); plan, _, _ = load(plan_path)
    folder = plan_path.parent; actual = Path(plan['output_root']) / 'actual_formal_ordinary_request.json'
    request_path = actual if actual.is_file() else folder / 'preview_ordinary_request.json'
    request = read(request_path)
    pack = Path(plan['source_pack']); caller = (pack / 'generator.py').read_text()
    if 'generator.py' not in plan['source_files']:
        raise ValueError('The visible caller must be the declared executable source snapshot')
    request = add_caller(request, caller)
    flight, teacher = token_preflight(request)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output / 'ordinary_request_DRAFT.json', request); save(output / 'teacher_request_DRAFT.json', teacher)
    save(output / 'task_DRAFT.json', request['task_packet']); save(output / 'token_preflight.json', flight)
    manifest = {'status': 'DRAFT_FUTURE_RATIO_TRAIN_CONTEXT_NOT_COLLECTION_FREEZE',
        'baseline_plan': str(plan_path), 'feedback_source': str(request_path),
        'feedback_scope': 'fresh_formal9' if actual.is_file() else 'development_preview_only',
        'full_actual_caller_visible_to_both_interfaces': True, 'caller_source': str(pack / 'generator.py'),
        'editable_paths': [EDITABLE], 'baseline_execution_source_modified': False,
        'old_requests_modified': False, 'new_model_or_physical_calls': 0,
        'actual_formal_feedback_recount_required': not actual.is_file(),
        'ordinary_and_teacher_field_mapping': flight['mapping'], 'token_counts': flight['token_counts']}
    save(output / 'context_DRAFT.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(prepare(args.plan, args.output), indent=2), flush=True)
