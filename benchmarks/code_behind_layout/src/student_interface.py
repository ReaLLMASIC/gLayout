"""Pure teacher-to-student action mapping; physical evidence remains unchanged."""
from collections.abc import Mapping
import copy
import json

from src.local_model_adapter import decision_prompt
from src.model_adapter import validate_action
from src.policy_state import VERSION as HISTORY_VERSION,current_state_request
from src.training import EncodedPatch

VERSION='ordinary_policy_action_v1'
CONTEXT_VERSION='ordinary_policy_action_context_v2'
MAX_NEW_TOKENS=1024
MAX_CONTEXT_TOKENS=8192
PACKET_ORDER=('task_id','goal','contract','allowed_paths','visible_sources','documents','visible_configurations','budget')


def interface_definition(version=VERSION,max_context_tokens=None,max_new_tokens=MAX_NEW_TOKENS):
    """Only an explicit new version may use a larger, prospectively frozen window."""
    length=MAX_CONTEXT_TOKENS if max_context_tokens is None else max_context_tokens
    if max_new_tokens!=MAX_NEW_TOKENS or type(length) is not int:
        raise ValueError('Ordinary policy output budget must remain 1024 tokens')
    if version==VERSION and length==MAX_CONTEXT_TOKENS:
        return {'version':version,'max_context_tokens':length,'max_new_tokens':max_new_tokens}
    if version==CONTEXT_VERSION and length in (12288,16384):
        return {'version':version,'max_context_tokens':length,'max_new_tokens':max_new_tokens,
                'history_policy':HISTORY_VERSION}
    raise ValueError('Unknown student interface or context window')


class PolicyBudgetError(ValueError):
    def __init__(self,reason,prompt_tokens,completion_tokens,max_length,max_new_tokens):
        self.details={'reason':reason,'prompt_tokens':prompt_tokens,'completion_tokens_including_EOS':completion_tokens,
                      'max_context_tokens':max_length,'max_new_tokens':max_new_tokens}
        super().__init__(json.dumps(self.details))


def student_request(context,interface_version=VERSION,max_context_tokens=None):
    """Keep complete source/physical contract/history, replacing output instructions."""
    definition=interface_definition(interface_version,max_context_tokens)
    value=json.loads(context) if isinstance(context,str) else copy.deepcopy(context)
    if set(value)!={'base_source','visible_contract','visible_feedback'}:raise ValueError('Expected the admitted full patch context')
    base=value['base_source'];visible=value['visible_contract']
    if not base or not all(isinstance(text,str) for text in base.values()):raise ValueError('Student source must retain every complete editable text')
    if set(visible['allowed_paths'])!=set(base):raise ValueError('Editable source scope differs from its physical context')
    task={key:copy.deepcopy(base if key=='visible_sources' else visible[key]) for key in PACKET_ORDER}
    task['goal']='Improve the declared physical objective while satisfying every frozen constraint across the visible configuration domain. Return one propose_patch ACTION_JSON with an executable ordinary unified diff. Preserve the complete declared source APIs and immutable physical contract.'
    task['documents']['patch_format']='Return the ordinary policy ACTION_JSON fields action, path, patch, configuration_ids, fidelity and summary. Use action="propose_patch", the exact ordinary unified diff in patch, and empty strings/lists for irrelevant fields. Do not return source_text, a whole replacement module or markdown fences.'
    if 'source_edit_policy' in task['documents']:
        task['documents']['source_edit_policy']='Make only the smallest necessary executable layout/planning changes. Preserve every unaffected source line, comment, docstring, import, name, format and ordering exactly. Return the ordinary propose_patch ACTION_JSON with its minimal unified diff; preserve all frozen physical constraints and APIs.'
    task['budget']['maximum_output_tokens']=MAX_NEW_TOKENS
    request={'task_packet':task,'visible_history':copy.deepcopy(value['visible_feedback'])}
    if interface_version==CONTEXT_VERSION:
        task['budget']['maximum_context_tokens']=definition['max_context_tokens']
        request=current_state_request(task,request['visible_history'],base)
    decision_prompt(request)
    return request


def canonical_action(patch,request):
    action={'action':'propose_patch','path':'','patch':patch,'configuration_ids':[],'fidelity':'','summary':''}
    validate_action(action,request['task_packet'])
    return json.dumps(action,ensure_ascii=False,separators=(',',':'))


def encode_policy_action(tokenizer,request,patch,max_length=MAX_CONTEXT_TOKENS,max_new_tokens=MAX_NEW_TOKENS):
    """Use precisely ordinary serving's single-user prompt; mask all prompt tokens."""
    rendered=tokenizer.apply_chat_template([{'role':'user','content':decision_prompt(request)}],tokenize=True,add_generation_prompt=True)
    prompt=list(rendered['input_ids'] if isinstance(rendered,Mapping) else rendered)
    if not prompt or any(type(token) is not int for token in prompt):raise ValueError('Expected one complete ordinary chat-template token sequence')
    completion=list(tokenizer(canonical_action(patch,request),add_special_tokens=False)['input_ids'])
    if tokenizer.eos_token_id is None:raise ValueError('Tokenizer has no EOS token')
    completion.append(tokenizer.eos_token_id)
    if len(completion)>max_new_tokens:raise PolicyBudgetError('ordinary_action_output_budget',len(prompt),len(completion),max_length,max_new_tokens)
    if len(prompt)+len(completion)>max_length:raise PolicyBudgetError('complete_source_contract_action_context_budget',len(prompt),len(completion),max_length,max_new_tokens)
    return EncodedPatch(prompt+completion,[-100]*len(prompt)+completion,len(prompt),len(completion))


def mapped_record(row,tokenizer,max_length=MAX_CONTEXT_TOKENS,max_new_tokens=MAX_NEW_TOKENS,*,interface_version=VERSION):
    interface_definition(interface_version,max_length,max_new_tokens)
    request=student_request(row['context'],interface_version,max_length);names=('chosen','rejected') if 'chosen' in row else ('patch',)
    encoded={name:encode_policy_action(tokenizer,request,row[name],max_length,max_new_tokens) for name in names}
    return {'raw_sample':copy.deepcopy(row),'student_interface_version':interface_version,'student_request':request,
            'target_actions':{name:canonical_action(row[name],request) for name in names},
            'token_counts':{name:{'prompt_tokens':value.prompt_tokens,'completion_tokens_including_EOS':value.completion_tokens,
                                  'total_tokens':len(value.input_ids)} for name,value in encoded.items()}}


def validate_mapped_record(record):
    if set(record)!={'raw_sample','student_interface_version','student_request','target_actions','token_counts'}:
        raise ValueError('Unknown or incomplete student mapping record')
    version=record['student_interface_version']
    length=record['student_request']['task_packet']['budget'].get('maximum_context_tokens') if version==CONTEXT_VERSION else None
    definition=interface_definition(version,length)
    row=record['raw_sample'];request=student_request(row['context'],version,length)
    if json.dumps(record['student_request'])!=json.dumps(request):raise ValueError('Derived student context/order differs from the declared pure mapping')
    names=('chosen','rejected') if 'chosen' in row else ('patch',)
    if record['target_actions']!={name:canonical_action(row[name],request) for name in names}:raise ValueError('Derived policy action changed its admitted raw patch')
    if set(record['token_counts'])!=set(names):raise ValueError('Student token preflight is incomplete')
    for counts in record['token_counts'].values():
        if (counts['completion_tokens_including_EOS']>MAX_NEW_TOKENS or counts['total_tokens']>definition['max_context_tokens'] or
            counts['prompt_tokens']+counts['completion_tokens_including_EOS']!=counts['total_tokens']):raise ValueError('Oversize student example entered a usable dataset')
    return row


def derive_matched_samples(groups,tokenizer,max_length=MAX_CONTEXT_TOKENS,max_new_tokens=MAX_NEW_TOKENS,*,interface_version=VERSION):
    """Exclude a whole matched comparison when any of its student targets is oversize."""
    definition=interface_definition(interface_version,max_length,max_new_tokens)
    datasets={key:[] for key in ['T1','T2','T3','T4']};excluded=[]
    for left,right in [('T1','T2'),('T3','T4')]:
        if len(groups[left])!=len(groups[right]):raise ValueError('Matched methods have unequal source row counts')
        for first,second in zip(groups[left],groups[right]):
            if (first['initial_state_id'],first['parent_lineage'],first['context'])!=(second['initial_state_id'],second['parent_lineage'],second['context']):raise ValueError('Point/Family rows do not share exactly the same original context')
            if left=='T3' and (first['pair_id']!=second['pair_id'] or sorted([first['chosen'],first['rejected']])!=sorted([second['chosen'],second['rejected']])):raise ValueError('DPO methods do not label the same candidate pair')
            records={};failures=[]
            for method,row in [(left,first),(right,second)]:
                try:records[method]=mapped_record(row,tokenizer,max_length,max_new_tokens,interface_version=interface_version)
                except PolicyBudgetError as exc:failures.append({'method':method,**exc.details})
            if failures:excluded.append({'methods':[left,right],'initial_state_id':first['initial_state_id'],'pair_id':first.get('pair_id'),
                                          'sample_ids':[first['sample_id'],second['sample_id']],'failures':failures})
            else:
                for method,record in records.items():datasets[method].append(record)
    report={'student_interface_version':interface_version,'max_context_tokens':max_length,'max_new_tokens':max_new_tokens,
            'input_samples_by_method':{key:len(rows) for key,rows in groups.items()},
            'usable_samples_by_method':{key:len(rows) for key,rows in datasets.items()},'paired_exclusions':excluded,
            'raw_samples_mutated':False,'source_or_contract_truncated':False}
    if 'history_policy' in definition:report['history_policy']=definition['history_policy']
    return datasets,report
