"""Inventory real program trajectories across five frozen train circuit domains.

This is a prospective collection matrix, never a dataset or useful-example count.
Different scopes and copied terminal programs do not create source diversity.
"""
from collections import defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.training_pilot_status import MODULES,program
from src.candidate_executor import apply_source_patch

ARCHIVES=['train_domain_freezes_20261019T0207Z.tar.gz','minimal_teacher_freezes_20261019T0215Z.tar.gz','train_trajectory_c02_nf_checkpoint_20261019T0400Z.tar.gz',
 'c01_collection_v1_freeze.tar.gz','c01_collection_v2_freeze.tar.gz','c01_action_teacher_first_state_20261019T0345Z.tar.gz','c05_minimal_first_state_partial_20261019T0326Z.tar.gz',
 'c01_gpt_teacher_v1_early_terminated_remote.tar.gz','c01_completed_source_repairs_readmission.tar.gz']


def main():
    files={};pools=[];source={}
    for name in ARCHIVES:
        archive=ROOT/'results/raw'/name
        if not archive.exists():continue
        with tarfile.open(archive) as stream:
            for member in stream:
                if not member.isfile():continue
                path=member.name;parts=Path(path).parts
                if parts[0].endswith('_v1') and not path.startswith(('runtime/','runs/')):path='runtime/train_collections/'+path
                leaf=Path(path).name
                if leaf=='candidates.jsonl':
                    for line in stream.extractfile(member).read().decode().splitlines():
                        if line.strip():pools.append((name,member.name,json.loads(line)))
                elif leaf in ['collection.json','registry.json','initial_states.jsonl']:
                    files[path]=stream.extractfile(member).read().decode()
                else:
                    for module in MODULES:
                        if path=='runtime/train_collections/c01_collection_v1/source_pack/'+module:
                            text=stream.extractfile(member).read().decode()
                            if module in source and source[module]!=text:raise ValueError('Original capsule source differs across verified backups')
                            source[module]=text
    if set(source)!=set(MODULES):raise ValueError('Two complete original compiler modules are required')
    for path in (ROOT/'runtime/train_collections').glob('*/collection.json'):
        for leaf in ['collection.json','registry.json','initial_states.jsonl']:
            p=path.parent/leaf
            if p.exists():files[str(p.relative_to(ROOT))]=p.read_text()
    catalog={}
    for name,text in files.items():
        if not name.endswith('/collection.json'):continue
        manifest=json.loads(text)
        if manifest.get('role')!='train_collection' or manifest.get('status')!='frozen':continue
        folder=str(Path(name).parent);reg=json.loads(files[folder+'/registry.json']);states=[json.loads(v) for v in files[folder+'/initial_states.jsonl'].splitlines() if v.strip()]
        catalog[manifest['collection_id']]={'manifest':manifest,'registry':reg,'states':states,'relative_manifest':name}
    selected={'C01':'c01_planning_action_gpt_teacher_v1','C02':'c02_action_v1','C05':'c05_rules_v1','C07':'c07_action_v1','C08':'c08_rules_v1'}
    domains={}
    for cid,name in selected.items():
        row=catalog[name];points=row['registry']['configurations']
        if len(points)!=9 or {p['parameters']['circuit']['circuit_id'] for p in points}!={cid}:raise ValueError('Keep the complete fixed circuit domain')
        domains[cid]={'frozen_manifest':row['relative_manifest'],'source_lineage':'textbook_universal_compiler_cropped','configuration_ids':[p['configuration_id'] for p in points],
            'independent_reference_ids':[p['reference_id'] for p in points],'objective':points[0]['contract']['objective'],'specifications':points[0]['contract']['specifications'],'all_nine_points_required':True}
    programs={}
    def add(sources,origin):
        identity=program(sources,source)
        if identity not in programs:programs[identity]={'complete_source':{**source,**sources},'origins':[]}
        if origin not in programs[identity]['origins']:programs[identity]['origins'].append(origin)
        return identity
    add(source,{'kind':'original_public_compiler_capsule'})
    candidate_origins={};known_inferences=set()
    for archive,member,row in pools:
        if row.get('source_role')!='formal_train':continue
        cid=row['candidate_id'];identity=add(row['candidate_source'],{'kind':'actual_model_program','candidate_id':cid,'parent_initial_state_id':row['initial_state_id'],'parent_lineage':row['parent_lineage'],'source_role':row['source_role'],'not_an_admitted_example':True})
        candidate_origins.setdefault(cid,{'archives':[],'member':member})['archives'].append(archive)
        programs[identity].setdefault('actual_candidate_ids',set()).add(cid)
        if row.get('proposal_generation',{}).get('inference_id'):known_inferences.add(row['proposal_generation']['inference_id'])
    broker_extra=[];broker_rejected=[]
    broker=ROOT/'runs/development/gpt_action_teacher_service/20261019T025406200999Z'
    for request_path in sorted(broker.glob('sessions/*/teacher_request.json')):
        invocation=request_path.parent/'teacher_invocation.json'
        if not invocation.exists():continue
        envelope=json.loads(invocation.read_text());response=envelope.get('response',{})
        inference=response.get('inference_id')
        if not inference or inference in known_inferences:continue
        request=json.loads(request_path.read_text());packet=request['request']['task_packet']
        if envelope.get('status')!='COMPLETED' or response.get('model',{}).get('source_role')!='isolated_GPT_formal_train_action_teacher':continue
        if response.get('usage',{}).get('policy_token_budget',{}).get('output_within_budget') is not True:continue
        action=response.get('action') or {}
        if action.get('action')!='propose_patch':continue
        if not set(packet['allowed_paths'])<=set(MODULES) or not set(packet['visible_sources'])<=set(MODULES):raise ValueError('Unexpected broker source scope')
        try:
            with tempfile.TemporaryDirectory(prefix='iscas-matrix-patch-',dir='/private/tmp') as temp:
                for name,text in packet['visible_sources'].items():
                    path=Path(temp)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                apply_source_patch(temp,action['patch'],packet['allowed_paths'])
                terminal={name:(Path(temp)/name).read_text() for name in packet['visible_sources']}
        except (ValueError,subprocess.CalledProcessError) as error:
            broker_rejected.append({'inference_id':inference,'task_id':packet['task_id'],'status':'No terminal source; rejected actual patch','error':str(error)});continue
        origin={'kind':'actual_isolated_GPT_ACTION_proposal','inference_id':inference,'task_id':packet['task_id'],
            'trial_id':request['trial_id'],'request_path':str(request_path),'invocation_path':str(invocation),
            'physical_outcome':'UNKNOWN_NOT_ADMITTED_BY_THIS_LOCAL_INVENTORY','not_manually_injected_or_reverse_patched':True}
        identity=add(terminal,origin);programs[identity].setdefault('actual_proposal_inference_ids',set()).add(inference)
        broker_extra.append(origin);known_inferences.add(inference)
    existing=set()
    for name,row in catalog.items():
        points=row['registry']['configurations'];circuit=points[0]['parameters']['circuit']['circuit_id']
        for state in row['states']:
            identity=add(state['base_source'],{'kind':'previously_frozen_initial_state','collection':name,'initial_state_id':state['initial_state_id'],'not_an_admitted_example':True})
            existing.add((circuit,identity))
    # New broker UUIDs sort between older sessions. Keep the already published
    # program IDs used by concrete DRAFT source bindings instead of renumbering.
    previous={};prior=ROOT/'results/derived/train_program_inventory.jsonl'
    if prior.exists():
        for line in prior.read_text().splitlines():
            if line.strip():
                old=json.loads(line);previous[program(old['complete_source'],source)]=old['program_id']
    next_id=max((int(name.removeprefix('program_')) for name in previous.values()),default=-1)+1
    inventory=[];ids={}
    for identity,row in programs.items():
        identifier=previous.get(identity)
        if identifier is None:identifier='program_'+str(next_id).zfill(3);next_id+=1
        ids[identity]=identifier
        inventory.append({'program_id':identifier,'parent_lineage':'textbook_universal_compiler_cropped','complete_source':row['complete_source'],
            'changed_modules_vs_original':[n for n in MODULES if row['complete_source'][n]!=source[n]],'parseable':all(item[1][0]=='AST' for item in identity),
            'origins':row['origins'],'actual_candidate_ids':sorted(row.get('actual_candidate_ids',[])),
            'actual_local_proposal_inference_ids':sorted(row.get('actual_proposal_inference_ids',[])),
            'identity':'Exact ast.dump(include_attributes=False), preserving literals/identifiers/docstrings; invalid Python retains exact original text. Complete two-module programs are compared.'})
    matrix=[]
    for circuit,domain in domains.items():
        for identity,row in programs.items():
            if (circuit,identity) in existing:continue
            matrix.append({'circuit_id':circuit,'program_id':ids[identity],'frozen_domain_manifest':domain['frozen_manifest'],'source_lineage':'textbook_universal_compiler_cropped',
                'status':'POTENTIAL_NOT_FROZEN_NOT_RUN_NOT_ADMITTED','fresh_proposals_planned':8,'fresh_baseline_points_required':9,'candidate_domain_points_required':9,
                'current_program_already_generated_by_model_or_frozen_initial_state':True,'full_context_API_and_fresh_feedback_preflight_required':True,
                'unknown_baseline_is_not_assumed_candidate_failure':True,'no_old_physical_outcome_relabelled':True})
    useful,pairs=set(),set();verified=[]
    for path in (ROOT/'runs/train_collection').glob('*_student_readmission_v1/physical_readmission.json'):
        admission=json.loads(path.read_text());name=path.parent.name.removesuffix('_student_readmission_v1')
        if admission.get('status')!='RE_ADMITTED_FROM_RAW' or name not in catalog or not (path.parent/'student_selection.json').exists():continue
        context=catalog[name];cid=context['registry']['configurations'][0]['parameters']['circuit']['circuit_id'];state_map={s['initial_state_id']:s for s in context['states']};verified.append(str(path.relative_to(ROOT)))
        for method in ['T1','T2','T3','T4']:
            for line in (path.parent/(method+'.jsonl')).read_text().splitlines():
                if not line.strip():continue
                raw_sample=json.loads(line)['raw_sample'];state=state_map[raw_sample['initial_state_id']];key=(cid,program(state['base_source'],source))
                if method in ['T1','T2']:useful.add(key)
                else:pairs.add((key,raw_sample.get('chosen'),raw_sample.get('rejected')))
    out=ROOT/'results/derived';out.mkdir(exist_ok=True)
    (out/'train_program_inventory.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in sorted(inventory,key=lambda r:r['program_id'])))
    report={'status':'DRAFT_SYSTEMATIC_COLLECTION_MATRIX_NOT_TRAINING_DATA','generated_at_utc':datetime.now(timezone.utc).isoformat(),'source_lineages':1,'whole_programs_in_inventory':len(inventory),
        'actual_model_candidate_origins':len(candidate_origins),'distinct_whole_candidate_terminal_programs':sum(bool(p.get('actual_candidate_ids')) for p in programs.values()),
        'additional_actual_local_broker_proposals':broker_extra,'rejected_local_broker_patches_without_program':broker_rejected,
        'distinct_whole_model_terminal_programs_including_unadmitted_local_proposals':sum(bool(p.get('actual_candidate_ids') or p.get('actual_proposal_inference_ids')) for p in programs.values()),
        'distinct_whole_frozen_initial_programs':sum(any(o['kind']=='previously_frozen_initial_state' for o in p['origins']) for p in programs.values()),
        'frozen_circuit_domains':domains,'program_inventory':'results/derived/train_program_inventory.jsonl',
        'already_frozen_distinct_program_circuit_contexts':len(existing),'potential_new_program_circuit_contexts':len(matrix),'all_possible_program_circuit_contexts_in_current_inventory':len(programs)*len(domains),
        'distinct_useful_SFT_initial_contexts_current_verified':len(useful),'usable_matched_DPO_pairs_current_verified':len(pairs),'independent_DPO_initial_contexts_current_verified':len({pair[0] for pair in pairs}),
        'verified_current_readmission_records':verified,
        'useful_yield_of_new_matrix_unknown':True,'1000_useful_context_goal_is_not_met':True,'target1000_shortfall_even_if_every_inventory_context_were_useful':max(0,1000-len(programs)*len(domains)),
        'proposal_envelope_if_entire_matrix_is_frozen':len(matrix)*8,'physical_point_upper_work_envelope':len(matrix)*9*9,
        'matrix':matrix,'candidate_raw_backup_locations':candidate_origins,
        'dispatch_conditions':'Each future context needs its own prospective interface/source/contract/budget freeze, exact tokenizer preflight and fresh baseline9; only actual trusted outcomes admit labels. Reuse actual programs, not copied repairs counted as new programs. Sampling and physical work remain on the unique shared2/resource-gated coordinator.',
        'excluded':'Original narrow-nf off-diagonals already fail independent ideal simulation and are not layout-repair labels. Wide-nf complete ideal9 has only1qualified point, so its full domain is also excluded. Long-channel DRAFT awaits the declared completeideal9 and is absent. Held-out evaluation sources, engineering patches and rule-injected reverse faults are not added.'}
    (out/'training_collection_matrix_draft.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['status','whole_programs_in_inventory','actual_model_candidate_origins','already_frozen_distinct_program_circuit_contexts','potential_new_program_circuit_contexts','proposal_envelope_if_entire_matrix_is_frozen','target1000_shortfall_even_if_every_inventory_context_were_useful']}))


if __name__=='__main__':main()
