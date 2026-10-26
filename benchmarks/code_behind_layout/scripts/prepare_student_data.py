"""Derive budget-checked ordinary-action supervision without rewriting teacher raw."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.student_interface import VERSION,CONTEXT_VERSION,derive_matched_samples,interface_definition
from src.training import TrustedPhysicalStore,admit_candidates,build_matched_samples,sample_identity
from scripts.run_frozen_training_collection import load_definition as load


def re_admit(root,registry,labels,initial_state_ids=None):
    """Reopen raw physical evidence with the current gate; old T1--T4 are unused."""
    candidates=[json.loads(line) for line in (root/'candidates.jsonl').read_text().splitlines() if line.strip()]
    if initial_state_ids is not None:candidates=[row for row in candidates if row['initial_state_id'] in initial_state_ids]
    store=TrustedPhysicalStore(root,registry);admitted=[];rejections=[]
    for row in candidates:
        try:admitted.extend(admit_candidates([row],registry,store))
        except (ValueError,OSError,KeyError) as exc:rejections.append({'candidate_id':row.get('candidate_id'),'error':str(exc)})
    report={'status':'QUARANTINED' if rejections else 'RE_ADMITTED_FROM_RAW',
        'gate':'current_TrustedPhysicalStore_including_per_finger_device_and_terminal_graph',
        'raw_candidates':len(candidates),'admitted_candidates':len(admitted),'rejections':rejections,
        'old_derived_T1_T4_used':False,'quarantined_candidates_are_negative_labels':False}
    if rejections:return None,report
    if admitted:groups,selection=build_matched_samples(admitted,labels)
    else:groups={method:[] for method in ['T1','T2','T3','T4']};selection={'initial_states':0,'samples':{key:0 for key in groups}}
    report['physical_selection']=selection
    return groups,report


def bound_registry(frozen,effective):
    """Permit only real control references appended by the collection backend."""
    expected=json.loads(json.dumps(frozen));actual={p['configuration_id']:p for p in effective['configurations']}
    if len(actual)!=len(expected['configurations']):raise ValueError('Effective registry configuration IDs changed')
    for point in expected['configurations']:
        row=actual.get(point['configuration_id'])
        if row is None:raise ValueError('Effective registry configuration IDs changed')
        if 'gold_control' not in point and 'gold_control' in row:
            control=row['gold_control']
            if set(control)!={'run_directory'} or not isinstance(control['run_directory'],str):raise ValueError('Invalid backend control reference')
            point['gold_control']=control
    if effective!=expected:raise ValueError('Effective registry changed more than permitted actual gold-control references')
    return effective


def interrupted_context_overflow(root,manifest,evidence_path):
    """Bind the observed old8k exit without manufacturing its missing terminal."""
    evidence=json.loads(evidence_path.read_text())
    matches=[row for row in evidence.get('collections',[]) if row.get('collection')==manifest['collection_id']
        and Path(row.get('output_root','')).resolve()==root.resolve()]
    if evidence.get('status')!='READ_ONLY_TRAIN_COLLECTION_EVIDENCE' or len(matches)!=1:
        raise ValueError('The host evidence does not identify this actual interrupted collection')
    observed=matches[0]
    if (root/'completion.json').exists() or observed['raw_paths']['completion.json']['exists']:
        raise ValueError('Use the actual existing completion record instead of an interrupted scope')
    # This explicit path is for the actually observed uncaught context guard,
    # not arbitrary orphaned or still-running collections.
    if not any('RuntimeError: Full source/contract exceeds frozen context; no proposal requested and no truncation allowed'
               in log.get('last_120_lines','') for log in observed.get('logs',[])):
        raise ValueError('Host evidence does not establish the actual context-overflow exit')
    manifest_path=str((ROOT/'runtime/train_collections'/manifest['collection_id']/'collection.json').resolve())
    records=list(evidence.get('actual_processes',[]))
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:records.append({'argv':[part.decode() for part in path.read_bytes().split(b'\0') if part]})
        except (OSError,UnicodeDecodeError):continue
    if any(manifest_path in record.get('argv',[]) for record in records):
        raise ValueError('The selected interrupted collection still has an active owner')
    return {'host_evidence_path':str(evidence_path.resolve()),'observed_exit':'uncaught_context_overflow',
            'actual_completion_record_exists':False,'collector_active':False}


def completed_state_scope(root,manifest,registry,selected,completion,interruption=None):
    """Allow only an entire returned eight-proposal state from a paused pool."""
    if not selected:
        if completion.get('status')!='COMPLETED_INITIAL_BATCH':
            raise ValueError('Wait for collection completion or explicitly select a fully returned initial state')
        return None,{'scope':'complete_collection','raw_collection_status':completion['status']}
    if completion.get('status')!='PAUSED_ADMISSION_UNCERTAINTY' and interruption is None:
        raise ValueError('Partial derivation is only for an admission-paused collection, never a running pool')
    states=[json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
    known={state['initial_state_id']:state for state in states};selected=set(selected)
    if not selected or not selected.issubset(known):raise ValueError('Selected completed states are not in the frozen initial-state list')
    attempts=json.loads((root/'attempts.json').read_text())
    candidates=[json.loads(line) for line in (root/'candidates.jsonl').read_text().splitlines() if line.strip()]
    sampling=manifest['sampling'];gpt=sampling['mode'] in ['train_collection_source_gpt','train_collection_action_gpt']
    rule=sampling['mode']=='train_collection_rules'
    identifier='rule_id' if rule else 'trial_id' if gpt else 'seed';expected=set(sampling['rule_ids' if rule else 'trials' if gpt else 'seeds'])
    for name in selected:
        state=known[name];returned=[row for row in attempts if row['initial_state_id']==name]
        if len(returned)!=8 or {row.get(identifier) for row in returned}!=expected:
            raise ValueError('Every one of the eight frozen proposal attempts must have returned')
        if any(row['status']=='PHYSICAL_QUEUED' for row in returned):
            raise ValueError('A selected state still has queued physical evidence')
        points={point['configuration_id'] for point in registry['configurations'] if point['parent_lineage']==state['parent_lineage']
                and (not state.get('task_id') or point['contract']['task_id']==state['task_id'])}
        if len(points)!=9 or set(json.loads((root/name/'baseline_results.json').read_text()))!=points:
            raise ValueError('The selected state needs all nine actual baseline records')
        rows=[row for row in candidates if row['initial_state_id']==name]
        done={row['candidate_id'] for row in returned if row['status']=='DECLARED_DOMAIN_ATTEMPTS_COMPLETE'}
        if {row['candidate_id'] for row in rows}!=done:
            raise ValueError('Raw candidates must cover the entire physically attempted state pool')
        for row in rows:
            if len(row['outcomes'])!=9 or {point['configuration_id'] for point in row['outcomes']}!=points:
                raise ValueError('Every physically attempted candidate needs every one of the nine point records')
    return selected,{'scope':'explicit_completed_initial_states_from_interrupted_context_overflow' if interruption else 'explicit_completed_initial_states_from_admission_paused_collection',
        'selected_initial_state_ids':sorted(selected),'raw_collection_status':completion.get('status'),
        'original_planned_initial_states':len(states),'original_planned_proposals':len(states)*8,
        'selected_returned_proposals':len(selected)*8,'whole_collection_claimed_complete':False,
        'original_remaining_unrun_or_unselected_proposals':len(states)*8-len(selected)*8,
        'raw_completion_changed':False,**({'interruption':interruption} if interruption else {})}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output-root',type=Path,required=True);p.add_argument('--completed-initial-state-id',action='append',help='Explicitly derive a whole eight-proposal/nine-point state from an admission-paused collection without claiming its remaining plan completed')
    p.add_argument('--student-interface',choices=[VERSION,CONTEXT_VERSION],default=VERSION)
    p.add_argument('--max-context-tokens',type=int,default=8192)
    p.add_argument('--interrupted-collection-evidence',type=Path,help='Actual host read-only evidence for a context-overflow exit without completion; requires explicitly selected complete eight-proposal states')
    a=p.parse_args();definition=interface_definition(a.student_interface,a.max_context_tokens)
    completion_path=a.input_root/'completion.json'
    completed=json.loads(completion_path.read_text()) if completion_path.exists() else {}
    if a.output_root.exists():raise ValueError('Do not overwrite an existing derived dataset')
    raw_manifest=json.loads((a.input_root/'collection_manifest.json').read_text())
    manifest_path=ROOT/'runtime/train_collections'/raw_manifest['collection_id']/'collection.json'
    manifest,frozen,_,_=load(manifest_path)
    if manifest!=raw_manifest:raise ValueError('Raw collection manifest differs from its actual frozen identity')
    registry=bound_registry(frozen,json.loads((a.input_root/'effective_registry.json').read_text()))
    labels=json.loads(Path(manifest['label_rule_path']).read_text())
    interruption=interrupted_context_overflow(a.input_root,manifest,a.interrupted_collection_evidence) if a.interrupted_collection_evidence else None
    if interruption and not a.completed_initial_state_id:raise ValueError('Select actual completed initial states explicitly; never claim the interrupted collection completed')
    selected,scope=completed_state_scope(a.input_root,manifest,registry,a.completed_initial_state_id,completed,interruption)
    groups,admission=re_admit(a.input_root,registry,labels,selected)
    admission.update(collection_scope=scope,classifier_source_snapshot='admission_training_source.py',device_graph_source_snapshot='admission_device_intent_source.py')
    a.output_root.mkdir(parents=True)
    shutil.copyfile(ROOT/'src/training.py',a.output_root/'admission_training_source.py')
    shutil.copyfile(ROOT/'src/device_intent.py',a.output_root/'admission_device_intent_source.py')
    (a.output_root/'physical_readmission.json').write_text(json.dumps(admission,indent=2)+'\n')
    if groups is None:raise ValueError('Raw evidence admission unresolved; derived dataset quarantined without creating negative labels')
    from transformers import AutoTokenizer
    cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())
    tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    datasets,report=derive_matched_samples(groups,tokenizer,a.max_context_tokens,interface_version=a.student_interface)
    for method,rows in datasets.items():(a.output_root/(method+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
    from scripts.train_policy import file_identity
    evidence={'status':'admitted','role':'formal_train','readmission_report':'physical_readmission.json',
        'registry_sha256':file_identity(a.input_root/'effective_registry.json'),
        'admitted_sample_ids':[row['sample_id'] for rows in groups.values() for row in rows],
        'sample_sha256':{row['sample_id']:sample_identity(row) for rows in groups.values() for row in rows}}
    (a.output_root/'trusted_evidence_manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
    report.update(status='DERIVED_REQUIRES_TRAINING_MANIFEST_FREEZE',derived_at_utc=datetime.now(timezone.utc).isoformat(),
        raw_collection_root=str(a.input_root.resolve()),student_interface_source_version=definition['version'],
        tokenizer_revision=cache['revision'],formal_training_started=False,raw_evidence_re_admitted=True,
        physical_readmission_report='physical_readmission.json',collection_scope=scope,effective_registry_path=str((a.input_root/'effective_registry.json').resolve()))
    (a.output_root/'student_selection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='paired_exclusions'},indent=2))


if __name__=='__main__':main()
