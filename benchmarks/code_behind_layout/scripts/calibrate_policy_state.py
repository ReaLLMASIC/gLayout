"""Replay only actually applied source patches to size the prospective visible state."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.validation_budget_pilot import INITIAL
from src.candidate_executor import apply_source_patch
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from src.policy_state import VERSION,current_state_request


def calibrate(batch,tokenizer):
    rows=[]
    for path in sorted(batch.glob('*/decisions/*/decision_*/request.json')):
        old=json.loads(path.read_text());history=old['visible_history']
        with tempfile.TemporaryDirectory(prefix='iscas-visible-state-') as temp:
            source=Path(temp);target=source/'generator.py';target.write_text(INITIAL)
            for index,event in enumerate(history[:-1]):
                action=event.get('action',{});following=history[index+1]['observation']
                if action.get('action')=='propose_patch' and following.get('patch_applied') is True:
                    apply_source_patch(source,action['patch'],['generator.py'])
            request=current_state_request(old['task_packet'],history,{'generator.py':target.read_text()})
            counts=prompt_token_budget(tokenizer,decision_prompt(request),{'max_context_tokens':8192,'max_new_tokens':1024})
            rows.append({'decision':str(path.parent.relative_to(batch)),**counts})
    return {'scope':'Prospective visible-state sizing with exact applied-patch replay; no old trial regrading',
        'visible_history_policy':VERSION,'batch':str(batch),'new_model_requests':0,'new_physical_calls':0,
        'all_physical_observations_retained':True,'all_errors_and_actions_retained':True,
        'obsolete_source_and_action_patch_payloads':'Replaced by complete current source; raw historical payloads remain in the trial log',
        'rows':rows,'decisions':len(rows),'maximum_input_tokens':max((r['prompt_tokens'] for r in rows),default=None),
        'fits_all_actual_decisions':all(r['fits_with_full_output_reserve'] for r in rows)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    report=calibrate(a.batch,tokenizer);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))
