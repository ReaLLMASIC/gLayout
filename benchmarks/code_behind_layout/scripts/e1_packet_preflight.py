#!/usr/bin/env python3
"""Exact initial shared-policy token preflight; performs no inference or EDA."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.local_model_adapter import decision_prompt
from src.model_adapter import PACKET_FIELDS,prompt_token_budget
from src.policy_state import current_state_request


def preflight(preparation,output):
    from transformers import AutoTokenizer
    began=time.monotonic();cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text());tokenizer_path=Path(cache['snapshot'])
    tokenizer=AutoTokenizer.from_pretrained(tokenizer_path,local_files_only=True,trust_remote_code=False)
    results=[]
    for path in sorted((preparation/'public').glob('draft_E1_*/*.json')):
        packet=json.loads(path.read_text())
        if set(packet)!=PACKET_FIELDS:raise ValueError('Non-whitelisted packet')
        request=current_state_request(packet,[{'observation':{'status':'initial'}}],packet['visible_sources'])
        budget=prompt_token_budget(tokenizer,decision_prompt(request),{'max_context_tokens':8192,'max_new_tokens':1024})
        results.append({'task_id':packet['task_id'],'method':path.stem,'packet':str(path.relative_to(preparation)),**budget})
    report={'scope':'development_exact_initial_packet_preflight_no_inference','preparation':str(preparation),
        'packets':len(results),'all_fit':len(results)==72 and all(r['fits_with_full_output_reserve'] for r in results),
        'tokenizer':str(tokenizer_path),'tokenizer_revision':cache['revision'],'visible_history_policy':'current_source_and_feedback_v1',
        'output_reserve':1024,'context_limit':8192,'wall_seconds':time.monotonic()-began,'formal_trials':0,'training_examples':0,'results':results}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    raise SystemExit(0 if preflight(a.preparation,a.output)['all_fit'] else 2)
