"""Drain the first already-dispatched GPT state, then seal its budget diagnostic.

This is the specifically authorized early termination of c01_gpt_teacher_v1.
No future collection uses this rule and no frozen trial denominator is changed.
"""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import load

def now():return datetime.now(timezone.utc).isoformat()
manifest_path=ROOT/'runtime/train_collections/c01_gpt_teacher_v1/collection.json'
manifest,_,states,_=load(manifest_path);output=Path(manifest['output_root']);pid=1061502
proof=json.loads((ROOT/'results/derived/student_interface_actual_token_calibration.json').read_text())
rows=[row for row in proof['candidates'] if row['candidate_id'].startswith('c01_gpt_teacher_v1__')]
assert len(rows)==8 and all(not row['fits'] and row['completion_tokens_including_EOS']>1024 for row in rows)
first=states[0]['initial_state_id'];log_path=ROOT/'logs/c01_gpt_teacher_v1.log'
started=now();deadline=time.monotonic()+7200
while True:
    if not Path('/proc/'+str(pid)).exists():raise RuntimeError('Collector exited before the authorized drain boundary; reconcile without changing raw status')
    events=[json.loads(line) for line in log_path.read_text().splitlines() if line.startswith('{')]
    completed=[row for row in events if row.get('stage')=='candidate' and first in row.get('candidate','')]
    if len(completed)>=72:
        argv=Path('/proc/'+str(pid)+'/cmdline').read_bytes().split(b'\0')
        assert str(manifest_path).encode() in argv
        os.kill(pid,signal.SIGSTOP)
        children=subprocess.run(['pgrep','-P',str(pid)],capture_output=True,text=True).stdout.strip()
        if children:
            os.kill(pid,signal.SIGCONT)
            raise RuntimeError('Next physical stage already started at the boundary; no running job was killed, manual reconciliation required')
        break
    if time.monotonic()>deadline:raise TimeoutError('First-state drain exceeded two hours; no process interrupted')
    time.sleep(.05)
attempts=json.loads((output/'attempts.json').read_text())
assert len(attempts)==8 and all(row['initial_state_id']==first for row in attempts)
outcomes=[json.loads(path.read_text()) for path in (output/first).glob('*_outcomes.json')]
assert len(outcomes)==8 and all(len(row['outcomes'])==9 for row in outcomes)
not_run=[{'initial_state_id':state['initial_state_id'],'trial_id':trial,'status':'NOT_RUN_DUE_TO_AUTHORIZED_EARLY_TERMINATION'} for state in states[1:] for trial in range(1,9)]
record={'status':'EARLY_TERMINATED_AFTER_COMPLETED_INITIAL_STATE_FOR_STUDENT_INTERFACE_BUDGET',
    'scope':'diagnostic_collection_early_termination_not_a_completed_main_benchmark',
    'authorized_by':'root explicit throughput instruction; preserve original 24 planned proposals',
    'drain_started_at_utc':started,'stopped_at_utc':now(),'collector_pid':pid,'exact_argv':[value.decode() for value in argv if value],
    'first_state':first,'first_state_completed_physical_candidate_points':len(completed),
    'original_planned_initial_states':len(states),'original_planned_attempts':len(states)*8,'actual_proposals':len(attempts),
    'remaining_not_run':len(not_run),'not_run':not_run,'student_budget_proof':rows,
    'actual_raw_proposal_usage':[{'candidate_id':row['candidate_id'],'usage':row.get('usage'),'client_wall_seconds':row.get('client_wall_seconds')} for row in attempts],
    'effective_samples_by_method':{key:0 for key in ['T1','T2','T3','T4']},
    'reason':'Every first-state mechanical ordinary student action exceeds 1024 tokens; later states were not launched',
    'raw_attempts_and_scores_mutated':False,'formal_model_training_runs':0}
(output/'early_termination.json').write_text(json.dumps(record,indent=2)+'\n')
if (output/'completion.json').exists():
    (output/'completion_before_authorized_termination.json').write_bytes((output/'completion.json').read_bytes())
os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
for _ in range(100):
    if not Path('/proc/'+str(pid)).exists() or Path('/proc/'+str(pid)+'/stat').read_text().split(') ',1)[1][0]=='Z':break
    time.sleep(.02)
else:raise RuntimeError('Collector did not terminate; no queue-release marker written')
(output/'completion.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({key:record[key] for key in ['status','collector_pid','original_planned_attempts','actual_proposals','remaining_not_run','effective_samples_by_method']}),flush=True)
