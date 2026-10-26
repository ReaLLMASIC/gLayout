"""Literal-span training proposals; ordinary tested policy actions are unchanged."""
import ast
import copy
import difflib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

from src.model_adapter import PACKET_FIELDS

VERSION = 'literal_span_teacher_v1'
MODE = 'train_collection_spans_gpt'
ROLE = 'isolated_GPT_formal_train_literal_span_teacher'
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['edits'],
    'properties': {'edits': {'type': 'array', 'minItems': 1, 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['path', 'old', 'new'],
        'properties': {name: {'type': 'string', **({'minLength': 1} if name == 'old' else {})}
                       for name in ('path', 'old', 'new')}}}}}

INSTRUCTIONS = (
    'Generate one train-only analog-layout proposal. Return JSON with exactly edits, an array of '
    '{path,old,new} strings. Each old must be nonempty and occur exactly once in the ORIGINAL full '
    'source of its allowed path, including whitespace. All old intervals must be disjoint. '
    'Use a unique surrounding anchor for insertions; new may be empty for deletion. '
    'Change only what is necessary for the declared objective and constraints. Preserve all unaffected '
    'lines, comments, docstrings, imports, names, formatting and ordering. Do not return a diff, '
    'ACTION, whole replacement module or markdown fences. No shell, filesystem, web, connectors, '
    'delegation or other native capabilities are available. Only the supplied complete packet and '
    'visible feedback belong to this fresh proposal. This producer format grants no new policy capability.\n')


def validate_proposal(value, allowed_paths):
    if not isinstance(value, dict) or set(value) != {'edits'} or not isinstance(value['edits'], list) or not value['edits']:
        raise ValueError('Expected one nonempty edits array')
    for edit in value['edits']:
        if (not isinstance(edit, dict) or set(edit) != {'path', 'old', 'new'}
                or any(not isinstance(edit[k], str) for k in ('path', 'old', 'new'))
                or edit['path'] not in allowed_paths or not edit['old'] or edit['old'] == edit['new']):
            raise ValueError('Unauthorized, empty, unchanged or malformed literal edit')
    return value


def teacher_request(original):
    if set(original) != {'task_packet', 'visible_history'} or set(original['task_packet']) != PACKET_FIELDS:
        raise ValueError('Use the exact visible packet/history boundary')
    request = copy.deepcopy(original); packet = request['task_packet']
    if set(packet['allowed_paths']) != set(packet['visible_sources']):
        raise ValueError('Every allowed module must be supplied in full')
    packet['goal'] = ('Produce minimal literal-span edits for the declared physical objective while satisfying '
                      'every frozen constraint across the complete visible domain. Preserve all source APIs, '
                      'circuit devices, dimensions, ports, references and the immutable physical contract.')
    packet['documents']['patch_format'] = INSTRUCTIONS.strip()
    if 'source_edit_policy' in packet['documents']:
        packet['documents']['source_edit_policy'] = INSTRUCTIONS.strip()
    packet['budget']['maximum_output_tokens'] = 3072
    packet['budget']['maximum_context_tokens'] = 16384
    return request


def proposal_prompt(request):
    packet = request.get('task_packet', {})
    if (set(request) != {'task_packet', 'visible_history'} or set(packet) != PACKET_FIELDS
            or packet['budget'].get('maximum_output_tokens') != 3072
            or packet['budget'].get('maximum_context_tokens') != 16384
            or set(packet['allowed_paths']) != set(packet['visible_sources'])):
        raise ValueError('A complete frozen 16k/3072 span teacher request is required')
    return INSTRUCTIONS + json.dumps(request)


def source_identity(source):
    result = []
    for name, text in sorted(source.items()):
        try: key = ('AST', ast.dump(ast.parse(text), include_attributes=False))
        except (SyntaxError, ValueError): key = ('unparsed_exact_text', text)
        result.append((name, key))
    return tuple(result)


def _diff(before, after, name):
    # difflib omits GNU's EOF marker; adding it records both missing-newline sides.
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile='a/' + name, tofile='b/' + name, n=3, lineterm='\n')
    return ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in lines)


def compile_proposal(base_source, proposal):
    """Match against original text, atomically edit, then prove exact git application."""
    if not base_source or any(not isinstance(v, str) for v in base_source.values()):
        raise ValueError('Complete editable source text maps are required')
    for name in base_source:
        path = PurePosixPath(name)
        if (str(path) != name or path.is_absolute() or '..' in path.parts
                or any(c in name for c in '\\ \t\r\n') or not path.parts):
            raise ValueError('Unsupported source path')
    validate_proposal(proposal, base_source)
    by_path = {}; matches = []
    for index, edit in enumerate(proposal['edits']):
        text = base_source[edit['path']]; start = text.find(edit['old'])
        if start < 0 or text.find(edit['old'], start + 1) >= 0:
            raise ValueError('old must occur exactly once in the original source: edit ' + str(index))
        end = start + len(edit['old'])
        if any(start < previous[1] and previous[0] < end for previous in by_path.get(edit['path'], [])):
            raise ValueError('Original source edit intervals overlap')
        by_path.setdefault(edit['path'], []).append((start, end, edit['new']))
        matches.append({'edit_index': index, 'path': edit['path'], 'start_character': start,
            'end_character': end, 'start_utf8_byte': len(text[:start].encode('utf-8')),
            'end_utf8_byte': len(text[:end].encode('utf-8')), 'original_occurrences': 1})
    changed = dict(base_source)
    for name, intervals in by_path.items():
        for start, end, new in sorted(intervals, reverse=True):
            changed[name] = changed[name][:start] + new + changed[name][end:]
    patch = ''.join(_diff(base_source[name], changed[name], name) for name in sorted(base_source) if base_source[name] != changed[name])
    if not patch: raise ValueError('Proposal has no source change')
    with tempfile.TemporaryDirectory(prefix='iscas-literal-span-') as temporary:
        directory = Path(temporary)
        for name, text in base_source.items():
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(text.encode('utf-8'))
        patch_file = directory / '.literal-span.patch'; patch_file.write_bytes(patch.encode('utf-8'))
        invocations = []
        for options in (['--check'], []):
            argv = ['git', 'apply', *options, '--whitespace=nowarn', '--', str(patch_file)]
            done = subprocess.run(argv, cwd=directory, capture_output=True, text=True)
            invocations.append({'argv': ['git', 'apply', *options, '--whitespace=nowarn', '--', '<compiled.patch>'],
                                'returncode': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
            if done.returncode: raise RuntimeError('Deterministic compiler/git mismatch: ' + done.stderr)
        if any((directory / name).read_bytes() != text.encode('utf-8') for name, text in changed.items()):
            raise RuntimeError('Applied patch bytes differ from the exact literal edit result')
    return {'patch': patch, 'candidate_source': changed,
        'compiler_proof': {'version': VERSION, 'matches': matches, 'git_invocations': invocations,
            'full_editable_source_byte_equal': True, 'context_lines': 3,
            'matching_scope': 'original_source_only', 'old_patch_input_or_repair': False}}


def mapped_student_request(request):
    from src.student_interface import student_request, CONTEXT_VERSION
    return student_request({'base_source': request['task_packet']['visible_sources'],
        'visible_contract': request['task_packet'], 'visible_feedback': request['visible_history']}, CONTEXT_VERSION, 16384)


def mapping_proof(original, teacher):
    ordinary = mapped_student_request(original); mapped = mapped_student_request(teacher)
    if ordinary != mapped:
        raise ValueError('Teacher-only output instructions leaked into the ordinary student context')
    for key in ('contract', 'allowed_paths', 'visible_sources', 'visible_configurations'):
        if teacher['task_packet'][key] != original['task_packet'][key]:
            raise ValueError('Teacher changed a physical/source field')
    if teacher['visible_history'] != original['visible_history']:
        raise ValueError('Teacher changed its actual feedback')
    return {'student_interface_version': 'ordinary_policy_action_context_v2',
            'teacher_and_original_map_to_identical_ordinary_request': True,
            'source_physical_fields_feedback_unchanged': True,
            'teacher_instruction_fields_replaced': ['goal', 'documents.patch_format', 'budget.maximum_output_tokens'],
            'ordinary_request': mapped}
