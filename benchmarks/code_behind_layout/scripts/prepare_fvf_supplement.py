"""Prospective FVF full-module editing packet; CPU/source preparation only.

No registry change, freeze, model/GPU load, signal or physical dispatch exists in
this entrypoint. Private25-point inputs stay on the execution host.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
SERVER=Path('/srv/code-behind-layout')
QUALIFIED=SERVER/'runs/development/ota_domain_qualification/fvf_20261019T025803566287Z_d7cf8287'
ORIGINAL=SERVER/'runtime/task_preparation/otas_20261019T022816023029Z/private/fvf/original_current_ota.py'
EDITABLE='glayout/cells/composite/fvf_based_ota/ota.py'
TASK='supplement_fvf15p_full_module_v1'
GENERATOR='''import argparse,json
from pathlib import Path
from component_build import build
p=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()
value=json.loads(Path(a.configuration).read_text())
if set(value)!={'parameters'}:raise ValueError('Expected the immutable parameters envelope')
build(value['parameters'],Path(a.output))
'''
TEACHER_INSTRUCTIONS=(
    'Generate one prospective development EVALUATION candidate, never training data. '
    'Return JSON edits, an array of {path,old,new} literal strings. Each nonempty old '
    'must occur exactly once in its complete original editable source; edits are disjoint. '
    'Preserve every unaffected line and every immutable circuit constraint. '
    'Do not return a whole source_text module, markdown, native tool call or partial source. '
    'Only the supplied visible packet/history belong to this proposal. The resulting '
    'ordinary action must still fit the tested1024-token output budget.\n')


def read(path):return json.loads(Path(path).read_text())
def sha(text):return hashlib.sha256(text.encode()).hexdigest()


def source_closure(pack):
    """Match the existing source capsule's exact bytecode-cache exclusions."""
    pack=Path(pack)
    return sorted(str(p.relative_to(pack)) for p in pack.rglob('*') if p.is_file()
        and '__pycache__' not in p.relative_to(pack).parts and not p.name.endswith('.pyc'))


def full_module_proof(original,hoisted,face):
    tree=ast.parse(hoisted)
    constructor=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='super_class_AB_OTA')
    helper=next(n for n in ast.parse(face).body if isinstance(n,ast.FunctionDef) and n.name=='place_and_route_local_bias')
    sites=[i for i,n in enumerate(constructor.body) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call)
           and isinstance(n.value.func,ast.Name) and n.value.func.id==helper.name]
    if len(sites)!=1 or not isinstance(helper.body[-1],ast.Return):
        raise ValueError('The qualified local-bias extraction no longer has one exact call/return')
    call=constructor.body[sites[0]]
    if (len(call.targets)!=1 or ast.unparse(call.targets[0])!=ast.unparse(helper.body[-1].value) or
            call.value.keywords or [a.arg for a in helper.args.args]!=[ast.unparse(a) for a in call.value.args]):
        raise ValueError('Qualified helper input/output dataflow differs from the complete constructor')
    imports=lambda t:[ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    if imports(ast.parse(face))!=imports(tree):
        raise ValueError('Injected helper imports differ from the complete original namespace')
    constructor.body[sites[0]:sites[0]+1]=copy.deepcopy(helper.body[:-1])
    if ast.dump(tree,include_attributes=False)!=ast.dump(ast.parse(original),include_attributes=False):
        raise ValueError('Restoring the full original module changes the qualified assembly algorithm')
    return {'entire_original_module_AST_reconstructed':True,'inlined_helper_statements':len(helper.body)-1,
            'full_original_source_bytes':len(original.encode()),'full_original_source_lines':len(original.splitlines()),
            'full_original_source_sha256':sha(original),'qualified_hoisted_module_sha256':sha(hoisted),
            'qualified_face_sha256':sha(face),'geometric_equivalence_measured':False}


def complete_module_caller(before):
    """Drop only the now-unused face injection; preserve the full OTA/export call."""
    tree=ast.parse(before);function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build')
    indices=[i for i,n in enumerate(function.body) if isinstance(n,ast.Assign)
             and any(isinstance(t,ast.Name) and t.id=='face' for t in n.targets)]
    if len(indices)!=1:raise ValueError('Expected one frozen face assignment')
    i=indices[0];following=function.body[i+1]
    if not (isinstance(following,ast.Expr) and isinstance(following.value,ast.Call)
            and isinstance(following.value.func,ast.Name) and following.value.func.id=='exec'):
        raise ValueError('Face assignment is not followed by the exact injection')
    expected=copy.deepcopy(tree);expected_fn=next(n for n in expected.body if isinstance(n,ast.FunctionDef) and n.name=='build')
    del expected_fn.body[i:i+2]
    lines=before.splitlines(keepends=True);first=function.body[i].lineno-1
    while first and lines[first-1].lstrip().startswith('#'):first-=1
    after=''.join(lines[:first])+"    # The complete original OTA module supplies all assembly statements.\n"+''.join(lines[following.end_lineno:])
    if ast.dump(ast.parse(after),include_attributes=False)!=ast.dump(expected,include_attributes=False):
        raise ValueError('Frozen caller changed beyond removal of the unused face injection')
    return after


def packet(original_packet,source,caller):
    value=copy.deepcopy(original_packet)
    value.update(task_id=TASK,allowed_paths=[EDITABLE],visible_sources={EDITABLE:source},
        goal='Minimize the actual complete OTA GDS bounding-box area with one shared complete-module layout edit, while preserving all immutable devices, connectivity and every15pF three-corner electrical constraint.')
    value['contract'].update(task_id=TASK,objective={'id':TASK+'_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'})
    value['budget']={'decisions':24,'patches':8,'physical_evaluations':8,'wall_seconds':14400,
        'maximum_context_tokens':16384,'maximum_output_tokens':1024,
        'visible_history_policy':'current_source_and_feedback_v1','status':'DRAFT_NOT_FROZEN_NO_DISPATCH'}
    documents=value['documents'];documents.pop('natural_shortfall',None)
    documents['action_gateway']={'read_source_paths':[EDITABLE],
        'runtime_only_paths':'Every other source/library/configuration path is runtime-only; read_source may only request the exact listed editable path.',
        'allowed_actions':['read_source','propose_patch','request_evaluation','finish'],
        'patch_format':'Ordinary executable unified diff; do not modify configuration, library, wrapper, reference or evaluator.'}
    documents['complete_frozen_component_build.py']=caller
    documents['complete_frozen_generator.py']=GENERATOR
    documents['source_scope']='The complete335-line original OTA module is editable, including all imports, constructor and local-bias assembly. Subordinate n_block/p_block/FVF/mirror/primitives are readonly APIs. This is not a local-bias-only face.'
    documents['configuration_input']={'parameters':'Gateway-supplied immutable sizing; generator extracts this envelope before the full original OTA build.'}
    return value


def inputs():
    if ROOT!=SERVER:raise ValueError('Read the private qualified25-domain only on its execution host')
    task=read(QUALIFIED/'private/task.json');summary=read(QUALIFIED/'public/summary.json')
    points=task['configurations']
    if (len(points)!=25 or len({p['configuration_id'] for p in points})!=25 or
            len({json.dumps(p['parameters'],sort_keys=True) for p in points})!=25 or
            {role:sum(p['role']==role for p in points) for role in ('anchor','development','hidden')}!={'anchor':1,'development':8,'hidden':16}):
        raise ValueError('Keep the exact distinct25-point qualification domain and1/8/16 roles')
    if summary['status']!='COMPLETE25' or not summary['complete25_domain'] or any(
            summary['groups'][role]!={'evaluated':count,'S1':count,'S2':count,'unknown':0}
            for role,count in [('anchor',1),('development',8),('hidden',16)]):
        raise ValueError('The existing development qualification is not actually complete25/S2')
    pack=Path(task['source_pack']);original=ORIGINAL.read_text()
    proof=full_module_proof(original,(pack/EDITABLE).read_text(),(pack/'fvf_layout_face.py').read_text())
    caller=complete_module_caller((pack/'component_build.py').read_text())
    return task,summary,proof,original,caller,packet(read(QUALIFIED/'public/task_packet.json'),original,caller)


def preflight(value,tokenizer,anchor_feedback=None):
    from src.local_model_adapter import decision_prompt
    from src.model_adapter import prompt_token_budget
    from src.policy_state import current_state_request
    histories={'initial':[]}
    if anchor_feedback is not None:
        histories['one_actual_public_development_anchor_payload']=[{'observation':{
            'capacity_probe_only_not_trial_feedback':True,'actual_public_anchor_feedback':anchor_feedback}}]
    result={}
    for label,history in histories.items():
        request=current_state_request(value,history,value['visible_sources'])
        teacher=copy.deepcopy(request);teacher['task_packet']['budget']['maximum_output_tokens']=3072
        result[label]={'ordinary':prompt_token_budget(tokenizer,decision_prompt(request),{'max_context_tokens':16384,'max_new_tokens':1024}),
            'evaluation_literal_span_teacher':prompt_token_budget(tokenizer,TEACHER_INSTRUCTIONS+json.dumps(teacher),{'max_context_tokens':16384,'max_new_tokens':3072})}
    source=next(iter(value['visible_sources'].values()))
    output=len(tokenizer(json.dumps({'source_text':source}),add_special_tokens=False)['input_ids'])+1
    return {'cases':result,'complete_source_JSON_output_tokens_including_EOS':output,
        'complete_source_teacher3072_usable':output<=3072,
        'teacher_role':'development_EVALUATION_proposal_only_never_training_data',
        'teacher_compile_gate':'Prospective literal edits must compile to an ordinary ACTION no larger than1024 tokens; no model call or successful proposal is claimed',
        'source_history_truncated':False,'whole_episode_context_guaranteed':False}


def prepare(output):
    task,summary,proof,source,caller,value=inputs()
    output=output.resolve();output.relative_to(ROOT/'runtime/task_preparation')
    if output.exists():raise ValueError('Use one unused DRAFT preparation directory')
    private=output/'private';private.mkdir(parents=True,mode=0o700);(output/'public').mkdir()
    for name,text in [('source/'+EDITABLE,source),('frozen/component_build.py',caller),('frozen/generator.py',GENERATOR)]:
        path=private/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    points=copy.deepcopy(task['configurations'])
    for point in points:
        point['contract'].update(task_id=TASK,objective=copy.deepcopy(value['contract']['objective']))
    record={'status':'DRAFT_FVF_FULL_MODULE_NOT_FROZEN','task_id':TASK,'target':'fvf',
        'parent_lineage':'glayout_fvf_ota','source_group':'vendor_glayout_connected','merged_source_group':'vendor_glayout_connected',
        'topology_family':'fvf_feedback','topology_holdout_wrt_project_training':True,'additional_ancestry_cluster':False,
        'source_pack_base':task['source_pack'],'source_files':source_closure(task['source_pack']),
        'source_inventory_policy':'Existing e3_task_prepare.capsule excludes only __pycache__ and *.pyc; retain all actual source/data files',
        'source_overrides':{EDITABLE:str(private/'source'/EDITABLE)},
        'frozen_source_overrides':{name:str(private/'frozen'/name) for name in ['generator.py','component_build.py']},
        'editable_paths':[EDITABLE],'entrypoint':'generator.py','representation':'G2','top_cell':task['cell_name'],
        'configuration_input':{'parameters':'Exact immutable sizing dictionary'},'configurations':points,
        'qualified_domain_origin':str(QUALIFIED),'trusted_template':str(QUALIFIED/'private/trusted_common'),
        'original_N_bench_and_electrical_thresholds_changed':False,'objective_changed_prospectively_to_actual_GDS_area':True,
        'source_equivalence':proof,'existing_development_qualification':summary,
        'formal_admission':False,'formal_dispatch_allowed':False,
        'remaining_gate':'Actual isolated new source capsule GDS equivalence/fullRC-intent/complete bench control, dedicated supplement method/release freeze; no old development result relabelled formal',
        'main24_1730_registry_and_seven_cluster_primary_changed':False}
    for path,obj in [(private/'task.json',record),(output/'public/task_packet.json',value)]:
        path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='Optional new DRAFT preparation; omission is read-only preflight')
    args=parser.parse_args();start,cpu=time.monotonic(),time.process_time()
    task,summary,proof,source,caller,value=inputs()
    from transformers import AutoTokenizer
    cache=read(ROOT/'configs/training/backbone_cache.json')
    tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
    anchor_path=ROOT/'results/derived/fvf_load15_10nm_anchor_qualification.json'
    budgets=preflight(value,tokenizer,read(anchor_path) if anchor_path.is_file() else None)
    report={'status':'DRAFT_FVF_SOURCE_AND_CPU_BUDGET_PREFLIGHT','source_equivalence':proof,
        'source_family':'glayout_fvf_ota','topology_family':'fvf_feedback','source_group':'vendor_glayout_connected',
        'existing_qualification_public':summary,'budget':budgets,'tokenizer_revision':cache['revision'],
        'public_anchor_history_available':anchor_path.is_file(),'new_model_calls':0,'new_EDA_calls':0,
        'formal_hidden_results_read':False,'registry_or_main_freeze_changed':False}
    if args.output:
        if not all(row['fits_with_full_output_reserve'] for case in budgets['cases'].values() for row in case.values()):
            raise ValueError('Complete source/caller/actual public history does not fit prospective budget')
        prepare(args.output);report['draft_preparation']=str(args.output)
    report.update(wall_seconds=time.monotonic()-start,parent_CPU_seconds=time.process_time()-cpu)
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':main()
