#!/usr/bin/env python3
"""Search-stage summary of the Claude editing cohort (E3-C), same row schema as the GPT summary.

Reads the local suite states and search reports, fetches anchor objectives and visible S2 sets of
the search stage from the server episode records in one read-only SSH call per suite, and writes
results/derived/E3C_visible_stage_summary_<stamp>.json. Hidden-stage records are never read.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.e1_matched_runner import REMOTE  # noqa: E402
from scripts.e1_scope_runner import SSH  # noqa: E402

SCOPE_LABEL = None
REMOTE_CODE = '''import json,sys
out={}
for ep in json.loads(sys.argv[1]):
    try:
        st=json.load(open(ep+'/private/state.json'))
    except Exception as e:
        out[ep]={'error':str(e)}; continue
    sel=st.get('selection') or {}; rev=sel.get('revision')
    events=[e for e in (st.get('physical_events') or []) if e.get('stage')=='search']
    def objective(cfg, r):
        for e in events:
            if e.get('configuration_id')==cfg and e.get('revision')==r and e.get('status')=='RETURNED':
                try:
                    p=json.load(open(e['point_record'])); return p.get('objective'), bool((p.get('checked') or {}).get('S2'))
                except Exception: return None, None
        return None, None
    a0,_=objective('anchor',0); a1,_=objective('anchor',rev) if rev not in (None,0) else (a0,None)
    vis=[]
    if rev is not None:
        for e in events:
            if e.get('revision')==rev and e.get('status')=='RETURNED':
                try:
                    p=json.load(open(e['point_record']))
                    if (p.get('checked') or {}).get('S2') and e['configuration_id'] not in vis: vis.append(e['configuration_id'])
                except Exception: pass
    out[ep]={'anchor_objective_rev0':a0,'anchor_objective_selected':a1,'visible_S2_at_selected':vis,'patches':st.get('patch_attempts'),
             'eval_requests_configs':len(events),'physical_calls':len(events),'selected_revision':rev,'retained':sel.get('retained_checks_established'),
             'required_visible_checks':sel.get('required_visible_checks'),'decisions':st.get('decisions'),'status':st.get('status')}
print(json.dumps(out))
'''


def direction(task):
    return 'max' if ('five_t' in task or 'compact_miller' in task) else 'min'


def classify(status, selected, imp):
    if selected and imp is not None and imp > 1e-9:
        return 'improving patch selected'
    if status == 'SEARCH_FINISHED' or (selected and imp is not None):
        return 'finished, no improvement'
    if status == 'INCOMPLETE_UNKNOWN':
        return 'last patch not applicable'
    if status == 'MODEL_FAILED':
        return 'model failure / over budget'
    if status == 'DECISION_BUDGET_EXHAUSTED':
        return 'finished, no improvement'
    return 'budget exhausted'


def remote_records(episodes):
    if not episodes:
        return {}
    cmd = 'cd ' + shlex.quote(REMOTE) + ' && python3 -c ' + shlex.quote(REMOTE_CODE) + ' ' + shlex.quote(json.dumps(episodes))
    result = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=600, check=True)
    return json.loads(result.stdout)


def parameter_records(local_dir, selected_rev):
    actions_path = Path(local_dir) / 'actions.json'
    a0 = a1 = None; vis = []; n = 0
    if actions_path.is_file():
        for act in json.loads(actions_path.read_text()):
            ob = act.get('observation_after') or {}
            if ob.get('configuration_id') is None or ob.get('checked') is None:
                continue
            n += 1
            if ob.get('configuration_id') == 'anchor' and ob.get('revision') == 0 and a0 is None:
                a0 = ob.get('objective')
            if ob.get('revision') == selected_rev:
                if ob.get('configuration_id') == 'anchor':
                    a1 = ob.get('objective')
                if (ob.get('checked') or {}).get('S2') and ob['configuration_id'] not in vis:
                    vis.append(ob['configuration_id'])
    if selected_rev in (None, 0):
        a1 = a0
    return {'anchor_objective_rev0': a0, 'anchor_objective_selected': a1, 'visible_S2_at_selected': vis, 'eval_requests_configs': n, 'physical_calls': n}


def summarize(state_paths):
    suites = {}
    for path in state_paths:
        state = json.loads(Path(path).read_text())
        part = state['plan_identity']['part']
        jobs = [j for j in state['jobs'] if j['status'] == 'RECORDED' and j.get('search_json')]
        remote = remote_records([j['episode_directory'] for j in jobs]) if part != 'parameter' else {}
        rows = []
        for j in jobs:
            r = json.loads(Path(j['search_json']).read_text())
            sel = r.get('selection') or {}
            rev = sel.get('revision', r.get('selected_revision'))
            if part == 'parameter':
                rec = parameter_records(j['local_output_directory'], rev)
                rec.update(patches=None, retained=sel.get('retained_checks_established', True), required_visible_checks=sel.get('required_visible_checks'))
            else:
                rec = remote.get(j['episode_directory'], {})
            selected = bool(rec.get('retained')) and rev not in (None, 0)
            a, b = rec.get('anchor_objective_rev0'), rec.get('anchor_objective_selected')
            imp = None
            if selected and a and b:
                imp = (a - b) / a if direction(j['task_id']) == 'min' else (b - a) / a
            cls = classify(r.get('status'), selected, imp)
            if part == 'gpt':
                group = j['method']
            elif part == 'signals':
                group = 'C-dist' if j.get('selector_variant') == 'without_distance' else 'C-margin'
            elif part == 'fidelity':
                group = 'C+F3'
            else:
                group = 'P-GPT' if j['method'] == 'P_gpt_feedback' else 'P-rand'
            costs = (r.get('costs_by_stage') or {}).get('search', {})
            rows.append({'task_id': j['task_id'], 'method': j['method'], 'group': group, 'variant': j.get('policy_variant'), 'selector': j.get('selector_variant', 'main'),
                         'trial_id': j['trial_id'], 'status': r.get('status'), 'selected_revision': rev, 'retained_checks_established': rec.get('retained'),
                         'required_visible_checks': rec.get('required_visible_checks'), 'visible_S2_at_selected': rec.get('visible_S2_at_selected'),
                         'visible_verified': len(rec.get('required_visible_checks') or []) if selected else 0,
                         'anchor_objective_rev0': a, 'anchor_objective_selected': b, 'anchor_improvement': imp, 'class': cls,
                         'full_evaluations': r.get('full_evaluations'), 'decisions': r.get('decisions'), 'patches': rec.get('patches'),
                         'eval_requests_configs': rec.get('eval_requests_configs'), 'physical_calls': rec.get('physical_calls'),
                         'stage_wall_s': costs.get('stage_wall_seconds'), 'child_cpu_s': costs.get('waited_child_CPU_seconds'),
                         'model_cli_invocations': (r.get('policy_statistics') or {}).get('model_cli_invocations'),
                         'policy_model_identity': r.get('policy_model_identity'), 'source_group': r.get('source_group'), 'search_json': j['search_json']})
        suites[part] = rows
    return {'scope': (SCOPE_LABEL or 'E3-C (Claude Opus 5.5)') + ' search-stage visible outcomes only; hidden stage sealed and unread; schema matches the GPT visible-stage summary',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'suites': suites}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite-state', nargs='+', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--label', default=None, help='cohort label for the scope field, e.g. "E3 (GPT-6.1)"')
    a = p.parse_args()
    SCOPE_LABEL = a.label
    summary = summarize(a.suite_state)
    Path(a.out).write_text(json.dumps(summary, indent=1) + '\n')
    for part, rows in summary['suites'].items():
        import collections
        print(part, len(rows), dict(collections.Counter(r['class'] for r in rows)))
    print('written', a.out)
