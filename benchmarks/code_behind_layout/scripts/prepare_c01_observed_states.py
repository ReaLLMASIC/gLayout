"""Draft new initial programs from actual observed T0 intermediate sources.

No old outcome is admitted or relabelled. Each prospective state needs a new
freeze, fresh baseline evidence and newly generated proposals before training.
"""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import apply_source_patch

capsule=ROOT/'runtime/train_collections/c01_collection_v1/source_pack'
pool_path=ROOT/'runs/phase0/phase0_20261018T234700264280Z_corpus_yield_pilot/model_pool_ready.json'
pool=json.loads(pool_path.read_text())
observed={101:'executor_20261019T010712342757Z_1d1a7348',241:'executor_20261019T010813788850Z_714c046b',379:'executor_20261019T010815466461Z_f9382719'}
scope=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']
original={name:(capsule/name).read_text() for name in scope}
if pool['editable_source']!=original['textbook_sharing/layout.py']:raise ValueError('Observed model parent differs from the actual frozen original')
states=[];seen=[]
for seed,run_id in observed.items():
    proposal=next(row for row in pool['candidates'] if row['seed']==seed)
    run=ROOT/'runs/development/corpus_isolated'/run_id
    manifest=json.loads((run/'manifest.json').read_text())
    if not manifest['phase'].startswith('development') or manifest['context']['candidate_id']!=proposal['candidate_id']:
        raise ValueError('Expected the actual development source-execution binding')
    actual={name:(run/'source'/name).read_text() for name in scope}
    with tempfile.TemporaryDirectory(prefix='iscas-observed-state-') as directory:
        base=Path(directory)
        for name,text in original.items():
            path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        apply_source_patch(base,proposal['patch'],['textbook_sharing/layout.py'])
        if {name:(base/name).read_text() for name in scope}!=actual:raise ValueError('Recorded patch does not produce the actually observed source')
    if actual==original or actual in seen:raise ValueError('Only real nonnoop distinct initial programs belong in this draft')
    seen.append(actual)
    states.append({'initial_state_id':'c01_observed_T0_seed_'+str(seed)+'_source_v1',
        'parent_lineage':'textbook_universal_compiler_cropped','origin':'natural','base_source':actual,
        'ancestry':{'kind':'actual_naturally_generated_model_intermediate_not_injected_fault',
            'source_revision':'1f90e33913208e572744b7c5a144a7da8c073235','parent_source_pack':str(capsule),
            'parent_proposal_pool':str(pool_path),'parent_proposal_id':proposal['candidate_id'],
            'parent_patch':proposal['patch'],'actual_observed_development_run':str(run),
            'producer_inference_id':proposal['inference_id'],'producer_seed':seed,'producer_model':proposal['model'],
            'producer_sampling':proposal['sampling'],'selection':'all_three_distinct_nonnoop_observed_sources; no outcome-based pruning',
            'semantic_observation':{101:'Changes mode from independent to diffusion_only before named-plan selection.',
                241:'Actual model output has an unindented else body and genuinely failed generation with IndentationError.',
                379:'Added custom-plan assignment is immediately overwritten by the original unconditional plan selection; distinct text does not establish distinct behavior.'}[seed],
            'physical_outcomes_reused_as_training_labels':False}})
out=ROOT/'runtime/collection_preparation'/('c01_observed_states_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));out.mkdir()
(out/'initial_states.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in states))
(out/'preparation.json').write_text(json.dumps({'status':'DRAFT_NEW_INITIAL_STATES_NOT_FROZEN','initial_states':3,
    'complete_editable_paths':scope,'initial_states_path':str(out/'initial_states.jsonl'),
    'old_evidence_labels_admitted':False,'fresh_baselines_and_new_proposals_required':True,
    'gold_control_requirement':'Reuse only actual same frozen contract/source/tool formal original controls or produce new controls; never mutate development roles',
    'inverse_injection_note':'No rule-created faults. Ancestry preserves the original full source and actual model patch so future near-return edits can be audited separately.'},indent=2)+'\n')
print(json.dumps({'preparation':str(out/'preparation.json'),'initial_states':len(states),'status':'DRAFT_NOT_LAUNCHED'}))
