#!/usr/bin/env python3
"""Read-only exact-action replay; never alter a frozen E3 trial or repair its patch."""
import argparse
import difflib
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.model_adapter import validate_action

COMMAND = ['git', 'apply', '--check', '--whitespace=nowarn', '-']


def read(path):
    return json.loads(Path(path).read_text())


def hunk_counts(patch):
    result = []
    for line_number, line in enumerate(patch.splitlines(), 1):
        header = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if header:
            result.append({'header_line': line_number, 'declared_old': int(header[2] or 1),
                'declared_new': int(header[4] or 1), 'observed_old': 0, 'observed_new': 0, 'context_lines': 0})
        elif result and line.startswith((' ', '+', '-')):
            row = result[-1]
            row['observed_old'] += line[0] in ' -'
            row['observed_new'] += line[0] in ' +'
            row['context_lines'] += line[0] == ' '
    return result


def replay(sources, patch, target):
    if target not in sources:
        raise ValueError('The exact action target must be in the complete current source packet')
    with tempfile.TemporaryDirectory(prefix='e3_exact_patch_diagnosis_') as temporary:
        work = Path(temporary)
        for name, text in sources.items():
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name or not isinstance(text, str):
                raise ValueError('Current visible source paths must be canonical relative ordinary files')
            output = work/path;output.parent.mkdir(parents=True, exist_ok=True);output.write_text(text)
        run = subprocess.run(COMMAND, cwd=work, input=patch, text=True, capture_output=True)
        # This separate generated diff checks only whether this Git can read the
        # same complete source/path. It is never applied or offered to a policy.
        original = sources[target]
        control = ''.join(difflib.unified_diff(original.splitlines(keepends=True),
            (original+'\n# independent read-only Git availability control\n').splitlines(keepends=True),
            fromfile='a/'+target, tofile='b/'+target))
        positive = subprocess.run(COMMAND, cwd=work, input=control, text=True, capture_output=True)
        unchanged = all((work/name).read_text() == text for name, text in sources.items())
    if not unchanged:
        raise ValueError('A --check replay unexpectedly changed the temporary source')
    return {'command': COMMAND, 'returncode': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr,
        'source_unchanged': unchanged, 'known_valid_same_source_control': {
            'returncode': positive.returncode, 'stdout': positive.stdout, 'stderr': positive.stderr,
            'scope': 'Generated diagnostic diff checked, never applied; not a repaired candidate or policy result'},
        'hunks': hunk_counts(patch)}


def classify(result, recorded_exit, target):
    established = (result['known_valid_same_source_control']['returncode'] == 0 and
        result['source_unchanged'] and result['returncode'] == recorded_exit)
    if established and result['returncode'] == 128 and re.fullmatch(
            r'error: corrupt patch at line \d+\n', result['stderr']):
        return 'candidate_corrupt_unified_diff'
    if established and result['returncode'] == 1 and re.fullmatch(
            r'error: patch failed: '+re.escape(target)+r':\d+\nerror: '+re.escape(target)+
            r': patch does not apply\n', result['stderr']):
        return 'candidate_patch_not_applicable_to_current_source'
    return 'UNRESOLVED_NO_CANDIDATE_CLASSIFICATION'


def diagnose(directory):
    directory = Path(directory);search = read(directory/'search.json');error = read(directory/'error.json')
    if search['phase'] != 'formal_E3' or search['status'] != 'INCOMPLETE_UNKNOWN':
        raise ValueError('This diagnostic reads the actual unresolved frozen E3 search records')
    recorded = re.search(r"Command '\['git', 'apply', '--check', '--whitespace=nowarn', '-'\]' returned non-zero exit status (\d+)\.", error['error'])
    if not recorded:
        raise ValueError('The original error must explicitly identify the frozen git --check invocation')
    decisions = sorted(directory.glob('decisions/*/decision_*/request.json'))
    if not decisions:
        raise ValueError('No actual decision request exists')
    request_path = decisions[-1];request = read(request_path);action_path = request_path.parent/'action.json'
    action = read(action_path)
    if action['action'] != 'propose_patch':
        raise ValueError('The final actual action must be the reported rejected patch')
    validate_action(action, request['task_packet'])
    sources = request['task_packet']['visible_sources']
    result = replay(sources, action['patch'], action['path'])
    return {'episode_directory': str(directory), 'task_id': search['task_id'], 'method': search['method'],
        'trial_id': search['trial_id'], 'original_search_status': search['status'], 'original_error': error,
        'request': str(request_path), 'action': str(action_path), 'exact_patch_unmodified': True,
        'current_source_scope': 'Complete visible_sources from the exact final decision request',
        'source_bytes': {name: len(text.encode('utf-8')) for name, text in sources.items()},
        'recorded_git_exit': int(recorded[1]), 'replay': result,
        'derived_classification': classify(result, int(recorded[1]), action['path']),
        'new_model_calls': 0, 'new_physical_calls': 0, 'original_status_or_source_changed': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episode', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = {'status': 'READ_ONLY_EXACT_PATCH_DIAGNOSIS',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'git_version': subprocess.run(['git', '--version'], text=True, capture_output=True, check=True).stdout.strip(),
        'episodes': [diagnose(path) for path in a.episode],
        'scope': 'Local exact-input check and same-source Git control. Original statuses/raw/actions remain unchanged; derived classifications are not automatic regrading or policy feedback.'}
    a.output.parent.mkdir(parents=True, exist_ok=True);a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'output': str(a.output), 'classifications': [r['derived_classification'] for r in result['episodes']]}))
