"""Draft complete C05/C08 initial programs from actually executed T0 sources."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import source_identity
from src.candidate_executor import apply_source_patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);a=p.parse_args()
    prep=json.loads(a.preparation.read_text());cid=prep['circuit_id'];path='textbook_sharing/layout.py'
    raw=json.loads((ROOT/'results/derived/corpus_C05_C08_T0_isolated_development_yield.json').read_text())['circuits'][cid]
    pool_path=(Path(raw['raw_summary'])/('model_pool_'+cid+'.json'));pool=json.loads(pool_path.read_text())
    capsule=Path(prep['source_pack']);original=(capsule/path).read_text()
    if pool['editable_source']!=original:raise ValueError('Actual observed proposal parent differs from the frozen compiler')
    states=[{'initial_state_id':cid.lower()+'_original_compiler_source_teacher','task_id':'train_collection_'+cid.lower(),
        'parent_lineage':prep['parent_lineage'],'origin':'natural','editable_paths':[path],'base_source':{path:original},
        'ancestry':{'kind':'unmodified_public_compiler','source_revision':prep['source_revision'],'source_pack':str(capsule)}}]
    # The change in sharing mode and the genuine generation failure are the
    # natural observed states. Known overwritten assignments are excluded.
    seeds=[101,379 if cid=='C05' else 241]
    for seed in seeds:
        proposal=next(row for row in pool['candidates'] if row['seed']==seed)
        executed=next(row for row in raw['candidates'] if row['candidate_id']==proposal['candidate_id'])
        run=Path(executed['run_directory']);manifest=json.loads((run/'manifest.json').read_text())
        if not(manifest['phase'].startswith('development') and manifest['context']['candidate_id']==proposal['candidate_id']):raise ValueError('Expected actual observed development execution')
        actual=(run/'source'/path).read_text()
        with tempfile.TemporaryDirectory(prefix='iscas-natural-state-') as name:
            directory=Path(name);target=directory/path;target.parent.mkdir(parents=True);target.write_text(original)
            apply_source_patch(directory,proposal['patch'],[path])
            if target.read_text()!=actual:raise ValueError('The recorded proposal does not produce its actually executed source')
        if source_identity({path:actual},True) in [source_identity(state['base_source'],True) for state in states]:raise ValueError('Natural states must represent distinct source ASTs or distinct unparseable text')
        states.append({'initial_state_id':cid.lower()+'_observed_T0_seed_'+str(seed)+'_source_teacher','task_id':'train_collection_'+cid.lower(),
            'parent_lineage':prep['parent_lineage'],'origin':'natural','editable_paths':[path],'base_source':{path:actual},
            'ancestry':{'kind':'actual_naturally_generated_model_intermediate_not_injected_fault','source_revision':prep['source_revision'],
                'parent_source_pack':str(capsule),'parent_proposal_pool':str(pool_path),'parent_proposal_id':proposal['candidate_id'],
                'parent_patch':proposal['patch'],'actual_observed_development_run':str(run),'producer_inference_id':proposal['inference_id'],
                'producer_seed':seed,'producer_model':proposal['model'],'producer_sampling':proposal['sampling'],
                'selection':'Observed sharing-mode change and actual generation failure; overwritten assignments and AST noops excluded.',
                'physical_outcomes_reused_as_training_labels':False}})
    out=ROOT/'runtime/collection_preparation'/(cid.lower()+'_observed_states_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
    target=out/'initial_states.jsonl';target.write_text(''.join(json.dumps(state,ensure_ascii=False)+'\n' for state in states))
    metadata={'status':'DRAFT_NEW_INITIAL_STATES_NOT_FROZEN','circuit_id':cid,'capsule_preparation':str(a.preparation.resolve()),
        'initial_states_path':str(target),'initial_state_count':len(states),'complete_editable_paths':[path],
        'old_evidence_labels_admitted':False,'fresh_baselines_and_new_proposals_required':True,
        'source_counting':'One universal compiler lineage. Identical source ASTs across topologies/teachers are the same program, even when task contexts differ.',
        'inverse_injection_note':'Each intermediate is byte-exact actual T0 output, bound by its raw diff and real executed source; no artificial fault or hand-written repair supplied.'}
    (out/'preparation.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'preparation':str(out/'preparation.json'),'initial_states':len(states),'state':'DRAFT_NOT_LAUNCHED'}))


if __name__=='__main__':main()
