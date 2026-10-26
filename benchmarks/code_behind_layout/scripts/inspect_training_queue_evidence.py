"""Read the five named paused/finished train collectors; never resume or rerun."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COLLECTIONS=('c05_collection_v1','c08_minimal_gpt_teacher_v1','c07_action_v1',
             'c05_minimal_gpt_teacher_v1','c01_planning_action_gpt_teacher_v1')


def json_read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError) as exc:return {'unreadable':type(exc).__name__+': '+str(exc)}


def inspect():
    """Bounded project logs plus exact raw-pool paths for subsequent admission."""
    queues=[]
    for path in (ROOT/'runs/train_collection_queues').glob('*/queue.json'):
        record=json_read(path)
        jobs=[j for j in record.get('jobs',[]) if j.get('collection') in COLLECTIONS]
        if not jobs:continue
        queues.append({'path':str(path),'status':record.get('status'),'pid':record.get('pid'),
            'jobs':jobs,'last_events':record.get('events',[])[-25:]})
    report={'status':'READ_ONLY_TRAIN_COLLECTION_EVIDENCE','at_utc':datetime.now(timezone.utc).isoformat(),
            'new_model_calls':0,'new_physical_calls':0,'queues':queues,'collections':[]}
    for name in COLLECTIONS:
        manifest_path=ROOT/'runtime/train_collections'/name/'collection.json'
        manifest=json_read(manifest_path);out=Path(manifest.get('output_root',str(ROOT/'runs/train_collection'/name)))
        record={'collection':name,'manifest':str(manifest_path),'output_root':str(out),'output_exists':out.exists(),
                'frozen_sampling':manifest.get('sampling'),'frozen_physical':manifest.get('physical'),
                'raw_paths':{},'logs':[]}
        for file in ('completion.json','attempts.json','candidates.jsonl','effective_registry.json','gold_controls.json','state.json'):
            path=out/file
            record['raw_paths'][file]={'path':str(path),'exists':path.is_file(),'bytes':path.stat().st_size if path.is_file() else None}
            if path.is_file() and file in ('completion.json','state.json'):record[file]=json_read(path)
        attempts=json_read(out/'attempts.json')
        if isinstance(attempts,list):
            record['attempt_count']=len(attempts)
            record['attempts_status_only']=[{k:a.get(k) for k in ('candidate_id','initial_state_id','trial_id','inference_id','error','status','student_preselection')} for a in attempts]
        candidates=out/'candidates.jsonl'
        if candidates.is_file():
            rows=[json.loads(line) for line in candidates.read_text().splitlines() if line.strip()]
            record['candidate_count']=len(rows)
            record['candidate_schema']={r.get('candidate_id','row_'+str(i)):sorted(r) for i,r in enumerate(rows)}
        for queue in queues:
            for job in queue['jobs']:
                if job.get('collection')!=name:continue
                log=Path(job.get('log',''))
                if log.is_file():record['logs'].append({'path':str(log),'last_120_lines':'\n'.join(log.read_text(errors='replace').splitlines()[-120:])})
        report['collections'].append(record)
    # Only these known training collectors and their queue process identities.
    report['actual_processes']=[]
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:argv=[p.decode() for p in path.read_bytes().split(b'\0') if p]
        except (OSError,UnicodeDecodeError):continue
        if len(argv)<2 or Path(argv[1]).name not in ('train_collection_queue.py','run_frozen_training_collection.py','collect_training.py'):continue
        if Path(argv[1]).name!='train_collection_queue.py' and not any(str(ROOT/'runtime/train_collections'/name/'collection.json') in argv for name in COLLECTIONS):continue
        status=path.parent/'status'
        state=next((line for line in status.read_text().splitlines() if line.startswith('State:')),None) if status.is_file() else None
        report['actual_processes'].append({'pid':int(path.parent.name),'argv':argv,'state':state})
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=inspect();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'report':str(args.output),'status':report['status'],'new_model_calls':0,'new_physical_calls':0}))
