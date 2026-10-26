"""Analyze the full frozen E1 episode matrix without dropping undispatched trials."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.e1_analysis import analyze_episodes


def analyze(manifest,index,development=False):
    if not development and manifest['status']!='FROZEN_E1':
        raise ValueError('Formal analysis requires the actual E1 freeze')
    tasks={row['task_id']:row for row in manifest['tasks']}
    if set(tasks)!=set(manifest['task_ids']):raise ValueError('The frozen task matrix is inconsistent')
    loaded={}
    for entry in index:
        key=(entry['task_id'],entry['method'],str(entry['trial_id']))
        if key in loaded:raise ValueError('Two result paths claim the same frozen episode')
        row=json.loads(Path(entry['episode_json']).read_text())
        if (row['task_id'],row['method'],str(row['trial_id']))!=key:raise ValueError('Result identity differs from the trusted dispatch index')
        if not development and row['phase']!='formal_E1':raise ValueError('Development episodes cannot enter formal results')
        row['status']=row.get('analysis_search_status',row['status']);loaded[key]=row
    rows=[]
    for task_id,task in tasks.items():
        for method in manifest['methods']:
            for trial in range(1,manifest['trials']+1):
                key=(task_id,method,str(trial))
                row=loaded.pop(key,None)
                if row is None:
                    row={'task_id':task_id,'method':method,'trial_id':str(trial),'stratum':task['stratum'],
                        'source_group':task['source_group'],'merged_source_group':task['merged_source_group'],
                        'status':'NOT_RUN','search_budget_seconds':manifest['budget']['wall_seconds'],
                        'observed_search_wall_seconds':None,'first_verified_times_seconds':dict.fromkeys(['S0','S1','S2']),
                        'final_anchor':{'complete':False,'S0':False,'S1':False,'S2':False},
                        'hidden':{'declared':16,'known':0,'S2_passed':0},'costs_by_stage':None}
                if any(row[key]!=task[key] for key in ('stratum','source_group','merged_source_group')):
                    raise ValueError('Result ancestry differs from the frozen task binding')
                rows.append(row)
    if loaded:raise ValueError('A dispatch result is outside the frozen episode matrix')
    report=analyze_episodes(rows,expected_trials=manifest['trials'])
    report.update(formal_results=not development,freeze_id=manifest.get('freeze_id'),
        planned_episodes=len(tasks)*len(manifest['methods'])*manifest['trials'],
        observed_status_counts=dict(Counter(row['status'] for row in rows)),
        cost_source='Trusted per-episode costs_by_stage; search, post-freeze diagnostic and hidden acquisition remain separate')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--episode-index',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--development',action='store_true');a=p.parse_args()
    manifest=json.loads(a.manifest.read_text());index=[json.loads(line) for line in a.episode_index.read_text().splitlines() if line.strip()]
    report=analyze(manifest,index,a.development);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps({k:report[k] for k in ('formal_results','planned_episodes','observed_status_counts')}))


if __name__=='__main__':main()
