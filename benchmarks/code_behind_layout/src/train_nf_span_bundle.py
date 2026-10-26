"""The separate, fixed C02/C07 NF-domain span pilot; never the old sixteen slots."""
import hashlib
import copy
import json
from pathlib import Path

from src.train_span_proposer import MODE, ROLE, VERSION

NF_VERSION = 'matched_pair_nf_joint_span16_v2'
CONTEXTS = [('c02_matched_nf_span_v1', 'c02_nf_original_compiler_v1'),
            ('c07_matched_nf_span_v1', 'c07_nf_original_compiler_v1')]


def read(path): return json.loads(Path(path).read_text())


def with_readonly_entrypoint(request, source):
    """Publish only the complete actual execution input, with no repair hints."""
    result=copy.deepcopy(request);packet=result['task_packet']
    if set(packet['allowed_paths'])!={'textbook_sharing/layout.py','glayout/sharing/enumeration.py'}:
        raise ValueError('NF editable scope must remain the same two complete modules')
    document={'path':'generator.py','visibility':'complete_readonly_execution_entrypoint','editable':False,'source':source}
    old=packet['documents'].get('readonly_execution_entrypoint')
    if old is not None and old!=document:raise ValueError('Do not overwrite a different actual entrypoint')
    packet['documents']['readonly_execution_entrypoint']=document
    return result


def validate_tokenizer(directory, bundle):
    for name, digest in read(Path(bundle)/'tokenizer_inventory.json')['files_sha256'].items():
        if hashlib.sha256((Path(directory)/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Pinned NF tokenizer bytes differ: '+name)


def validate_rules_ready(ready,proposal_sha256,acceptance_path=None):
    if (ready.get('status')!='ALL16_ORIGINAL_RULE_ATTEMPTS_TERMINAL_BEFORE_GPT' or ready.get('attempts')!=16
            or ready.get('model_calls')!=0 or ready.get('proposal_collection_sha256')!=proposal_sha256
            or not isinstance(ready.get('acceptance_sha256'),str) or len(ready['acceptance_sha256'])!=64):
        raise ValueError('The fixed sixteen original-rule attempts must be ready before any GPT or physics dispatch')
    if acceptance_path is not None:
        acceptance_path=Path(acceptance_path);definition=read(acceptance_path)
        if (str(acceptance_path.resolve())!=ready.get('acceptance_path')
                or hashlib.sha256(acceptance_path.read_bytes()).hexdigest()!=ready['acceptance_sha256']
                or definition.get('status')!='frozen' or definition.get('role')!='matched_NF_joint_GPT_and_original_rules_physical_followup_train_only'
                or definition.get('proposal_collection_sha256')!=proposal_sha256):
            raise ValueError('Rule-ready receipt does not bind the actual frozen joint acceptance')
    return ready


def load_bundle(path):
    path = Path(path).resolve(); root = path.parent; manifest = read(path)
    identity = read(root/'freeze_identity.json')
    if 'collection.json' not in identity: raise ValueError('NF collection is not frozen')
    for file in [root, *root.rglob('*')]:
        if file.is_symlink() or file.stat().st_mode & 0o222:
            raise ValueError('NF freeze is writable or linked: '+str(file.relative_to(root)))
    for name, digest in identity.items():
        file = root/name
        if (not file.resolve().is_relative_to(root) or not file.is_file()
                or hashlib.sha256(file.read_bytes()).hexdigest() != digest):
            raise ValueError('NF frozen bytes differ: '+name)
    sampling = {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'mode': MODE, 'trials': list(range(1,9)), 'seed': None, 'proposal_workers': 2,
        'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240}
    if (manifest.get('status') != 'frozen' or manifest.get('role') != 'train_proposal_collection'
            or manifest.get('NF_bundle_version') != NF_VERSION or manifest.get('source_role') != ROLE
            or manifest.get('teacher_interface_version') != VERSION or manifest.get('sampling') != sampling
            or manifest.get('planned_proposals') != 16 or manifest.get('new_physical_domain_contexts') != 2
            or manifest.get('new_initial_source_ASTs') != 0 or manifest.get('new_lineages') != 0
            or not isinstance(manifest.get('rules_ready_path'),str) or not isinstance(manifest.get('joint_acceptance_plan'),str)
            or manifest.get('endpoint') != 'http://127.0.0.1:8116/spans/decision'
            or manifest.get('student_preselection') != {'interface_version':'ordinary_policy_action_context_v2',
                'max_new_tokens':1024, 'max_context_tokens':16384, 'stage':'before_physics'}):
        raise ValueError('Only the separately frozen NF two-domain/sixteen-proposal pilot is supported')
    if [(c['parent_collection_id'],c['initial_state_id']) for c in manifest.get('contexts',[])] != CONTEXTS:
        raise ValueError('Do not substitute old contexts, new states or a selected NF subset')
    required = ['baseline_audit.json','tokenizer_inventory.json','teacher_context_preflight.json','hypothesis.json']
    for context in manifest['contexts']:
        required.extend(context[key] for key in ('original_request','teacher_request','student_request','mapping_proof','readonly_entrypoint',
            'initial_state','baseline_results','effective_registry','parent_collection','label_rule'))
        if not read(root/context['mapping_proof']).get('teacher_and_original_map_to_identical_ordinary_request'):
            raise ValueError('NF teacher-to-ordinary output instruction mapping is unproven')
        source=(root/context['readonly_entrypoint']).read_text()
        for key in ['original_request','teacher_request','student_request']:
            request=read(root/context[key])
            if with_readonly_entrypoint(request,source)!=request:
                raise ValueError('Exact read-only entrypoint must be equally present for teacher and ordinary student')
    if any(name not in identity for name in required): raise ValueError('NF context/evidence input is not frozen')
    audit = read(root/'baseline_audit.json')
    if (not audit.get('all_eighteen_points_complete') or len(audit.get('records',[])) != 18
            or audit.get('phase') != 'formal_train' or any(not r.get('S2') or not r.get('full_RC_device_graph_clean') for r in audit['records'])):
        raise ValueError('All eighteen fresh formal controls and full RC graph proofs are required')
    for context,circuit in zip(manifest['contexts'],['c02','c07']):
        registry=read(root/context['effective_registry'])
        expected=[f'{circuit}_matched_nf_{a}_{b}' for a in (4,8,12) for b in (4,8,12)]
        if [p['configuration_id'] for p in registry['configurations']] != expected:
            raise ValueError('Keep the complete predeclared NF grid and order')
    flights=read(root/'teacher_context_preflight.json')
    if (len(flights)!=2 or any(not p.get('actual_fresh_formal_feedback') or p.get('source_or_contract_truncated') is not False
            or any(not p['token_counts'][key]['fits_with_full_output_reserve'] for key in ['teacher','student']) for p in flights)):
        raise ValueError('Complete actual fresh feedback must fit both teacher and ordinary student contexts')
    return manifest
