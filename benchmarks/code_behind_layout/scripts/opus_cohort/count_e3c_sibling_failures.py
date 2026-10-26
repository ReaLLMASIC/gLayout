#!/usr/bin/env python3
"""Count sibling failures in the Claude editing cohort (E3-C), search stage only.

A sibling failure is a post-edit revision whose anchor evaluation passed every check (S2) while at least
one development configuration evaluated at the same revision failed. Counts are reported under three
sibling rules so the paper can quote the one matching the GPT definition (full-rule DRC failure):
  drc  : the sibling's physical result has S1 false and a DRC reason;
  s1   : the sibling failed DRC, LVS or device intent (S1 false);
  any  : the sibling failed any check (S2 false).
Reads the local Claude suite states for the episode directories and the server episode records in one
read-only SSH call per suite; hidden-stage records are never read; nothing is written on the server.
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

REMOTE_CODE = '''import json,sys
out={}
for ep in json.loads(sys.argv[1]):
    try:
        st=json.load(open(ep+'/private/state.json'))
    except Exception as e:
        out[ep]={'error':str(e)}; continue
    events=[e for e in (st.get('physical_events') or []) if e.get('stage')=='search' and e.get('status')=='RETURNED']
    rows=[]
    for e in events:
        try:
            p=json.load(open(e['point_record'])); c=p.get('checked') or {}
        except Exception as x:
            rows.append({'configuration_id':e.get('configuration_id'),'revision':str(e.get('revision')),'unreadable':str(x)}); continue
        reasons=' '.join(str(r) for r in (c.get('reasons') or [])+[c.get('reason') or ''])
        rows.append({'configuration_id':e.get('configuration_id'),'revision':str(e.get('revision')),'S1':bool(c.get('S1')),'S2':bool(c.get('S2')),
                     'status':c.get('status'),'failure_class':c.get('failure_class'),'drc_reason':('DRC' in reasons.upper())})
    out[ep]={'status':st.get('status'),'rows':rows}
print(json.dumps(out))
'''


def remote(episodes):
    cmd = 'cd ' + shlex.quote(REMOTE) + ' && python3 -c ' + shlex.quote(REMOTE_CODE) + ' ' + shlex.quote(json.dumps(episodes))
    result = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=900, check=True)
    return json.loads(result.stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suites', nargs='+', default=['E3_primary_v2_claude_gpt', 'E3_primary_v2_claude_signals'])
    p.add_argument('--output', type=Path, default=None)
    p.add_argument('--root', default='runs/formal/E3_suite_claude', help='suite root holding <suite>/state.json')
    p.add_argument('--prefix', default='E3C', help='output file prefix (E3C for the Claude cohort, E3 for GPT)')
    a = p.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%MZ')
    report = {'scope': a.prefix + ' search stage, read-only; hidden never read', 'root': a.root, 'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'suites': {}}
    totals = {'post_edit_measurements': 0, 'post_edit_revisions': 0}
    for rule in ('drc', 's1', 'any'):
        totals[rule] = {'revisions': 0, 'episodes': 0}
    for suite in a.suites:
        state = json.loads((ROOT / a.root / suite / 'state.json').read_text())
        jobs = {j['episode_directory']: j for j in state['jobs'] if j.get('status') == 'RECORDED' and j.get('episode_directory')}
        records = remote(sorted(jobs))
        summary = {'episodes': len(jobs), 'unreadable_episodes': 0, 'post_edit_measurements': 0, 'post_edit_revisions': 0,
                   'rules': {r: {'revisions': 0, 'episodes': 0, 'by_task': {}} for r in ('drc', 's1', 'any')}, 'episodes_detail': []}
        for ep, rec in records.items():
            if 'error' in rec:
                summary['unreadable_episodes'] += 1; continue
            job = jobs[ep]
            by_rev = {}
            for row in rec['rows']:
                if row['revision'] in ('0', 'None'):
                    continue
                by_rev.setdefault(row['revision'], []).append(row)
            summary['post_edit_measurements'] += sum(len(v) for v in by_rev.values())
            summary['post_edit_revisions'] += len(by_rev)
            hits = {r: [] for r in ('drc', 's1', 'any')}
            for rev, rows in by_rev.items():
                anchor = [r for r in rows if r['configuration_id'] == 'anchor' and not r.get('unreadable')]
                if not anchor or not anchor[-1]['S2']:
                    continue
                sib = [r for r in rows if r['configuration_id'] != 'anchor' and not r.get('unreadable')]
                if any((not r['S1']) and r['drc_reason'] for r in sib):
                    hits['drc'].append(rev)
                if any(not r['S1'] for r in sib):
                    hits['s1'].append(rev)
                if any(not r['S2'] for r in sib):
                    hits['any'].append(rev)
            for r in ('drc', 's1', 'any'):
                if hits[r]:
                    summary['rules'][r]['revisions'] += len(hits[r]); summary['rules'][r]['episodes'] += 1
                    summary['rules'][r]['by_task'][job['task_id']] = summary['rules'][r]['by_task'].get(job['task_id'], 0) + len(hits[r])
            if any(hits.values()):
                summary['episodes_detail'].append({'episode_directory': ep, 'task_id': job['task_id'], 'method': job['method'], 'trial_id': job['trial_id'], 'hits': hits})
        report['suites'][suite] = summary
        totals['post_edit_measurements'] += summary['post_edit_measurements']; totals['post_edit_revisions'] += summary['post_edit_revisions']
        for r in ('drc', 's1', 'any'):
            totals[r]['revisions'] += summary['rules'][r]['revisions']; totals[r]['episodes'] += summary['rules'][r]['episodes']
    report['totals'] = totals
    out = a.output or ROOT / f'results/derived/{a.prefix}_sibling_failures_{stamp}.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'totals': totals}, indent=1))


if __name__ == '__main__':
    main()
