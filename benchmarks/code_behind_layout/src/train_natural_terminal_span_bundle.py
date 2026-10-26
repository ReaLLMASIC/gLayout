"""Only the two fixed new natural-terminal TRAIN contexts; no old-pool IDs."""
import copy
import hashlib
import json
from pathlib import Path

from src.train_span_proposer import MODE, ROLE, VERSION, mapping_proof

BUNDLE_VERSION='natural_terminal_c01_c02_span16_v1'
CONTEXTS=[('natural_terminal_c01_seed101_area_v1','natural_terminal_c01_seed101_area_v1'),
          ('natural_terminal_c02_span1_area_v1','natural_terminal_c02_span1_area_v1')]
POINTS=[['train_c01_anchor','train_c01_dev_nf1_l030','train_c01_dev_nf2_l060','train_c01_dev_nf3_l045',
    'train_c01_dev_nf6_l060','train_c01_dev_nf8_l090','train_c01_dev_w075_l045','train_c01_dev_w100_l060','train_c01_dev_l120'],
    ['t2a','t2b','t2c','t2d','t2e','t2f','t2g','t2h','t2i']]
MODULES=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']


def read(path):return json.loads(Path(path).read_text())


def validate_tokenizer(directory,bundle):
    for name,digest in read(Path(bundle)/'tokenizer_inventory.json')['files_sha256'].items():
        if hashlib.sha256((Path(directory)/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Pinned natural-terminal tokenizer bytes differ: '+name)


def canonical_immutable_registries(registries):
    """Use one immutable capsule only after exact bytes prove these two aliases.

    Each new initial keeps its own full source/physical context. The Store binds
    editable modules from that context, while its78 immutable members are equal.
    Original/private baseline registry files are never rewritten.
    """
    if len(registries)!=2:raise ValueError('Exactly the fixed two contexts are required')
    result=copy.deepcopy(registries);lineage='textbook_universal_compiler_cropped'
    assignments=[next(row for row in r['lineages'] if row['lineage_id']==lineage) for r in result]
    first=assignments[0];names=first['frozen_source_files'];canonical=first['frozen_source_pack']
    aliases=[row['frozen_source_pack'] for row in assignments]
    if len(names)!=78 or first['editable_paths']!=MODULES or first['split']!='train':
        raise ValueError('Keep the exact cropped compiler train/source scope')
    without_path=lambda row:{k:v for k,v in row.items() if k!='frozen_source_pack'}
    if any(without_path(row)!=without_path(first) for row in assignments):
        raise ValueError('Source aliases cannot change the shared lineage assignment')
    for row in assignments:
        for name in names:
            if (Path(row['frozen_source_pack'])/name).read_bytes()!=(Path(canonical)/name).read_bytes():
                raise ValueError('Immutable source aliases are not byte-equivalent: '+name)
        row['frozen_source_pack']=canonical
    return result,{'scope':'two prospective private registry Store views only',
        'canonical_immutable_source_pack':canonical,'source_pack_aliases':aliases,'immutable_files_compared':len(names),
        'all_immutable_bytes_equal':True,'editable_modules_bound_individually':MODULES,
        'original_registry_files_changed':False,'new_source_lineages':0}


def load_bundle(path):
    path=Path(path).resolve();root=path.parent;manifest=read(path);identity=read(root/'freeze_identity.json')
    if 'collection.json' not in identity:raise ValueError('Natural-terminal collection is not frozen')
    for file in [root,*root.rglob('*')]:
        if file.is_symlink() or file.stat().st_mode&0o222:raise ValueError('Natural-terminal freeze is writable or linked')
    for name,digest in identity.items():
        file=root/name
        if not file.resolve().is_relative_to(root) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen natural-terminal bytes differ: '+name)
    sampling={'backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','mode':MODE,
        'trials':list(range(1,9)),'seed':None,'proposal_workers':2,'max_new_tokens':3072,
        'max_context_tokens':16384,'timeout_seconds':240}
    if (manifest.get('status')!='frozen' or manifest.get('role')!='train_proposal_collection'
            or manifest.get('bundle_version')!=BUNDLE_VERSION or manifest.get('source_role')!=ROLE
            or manifest.get('teacher_interface_version')!=VERSION or manifest.get('sampling')!=sampling
            or manifest.get('planned_proposals')!=16 or manifest.get('new_initial_source_ASTs')!=2
            or manifest.get('new_lineages')!=0 or manifest.get('new_physical_domain_contexts')!=0
            or manifest.get('endpoint')!='http://127.0.0.1:8116/spans/decision'
            or manifest.get('student_preselection')!={'interface_version':'ordinary_policy_action_context_v2',
                'max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'}):
        raise ValueError('Only the fixed two-natural-terminal/sixteen-proposal pilot is supported')
    if [(c['parent_collection_id'],c['initial_state_id']) for c in manifest.get('contexts',[])]!=CONTEXTS:
        raise ValueError('Do not substitute an old context or select a source subset')
    required=['baseline_audit.json','tokenizer_inventory.json','teacher_context_preflight.json']
    for context,expected_points in zip(manifest['contexts'],POINTS):
        required.extend(context[key] for key in ('original_request','teacher_request','student_request','mapping_proof',
            'readonly_entrypoint','initial_state','baseline_results','effective_registry','parent_collection','label_rule'))
        original=read(root/context['original_request']);teacher=read(root/context['teacher_request'])
        proof=mapping_proof(original,teacher);student=proof.pop('ordinary_request')
        if proof!=read(root/context['mapping_proof']) or student!=read(root/context['student_request']):
            raise ValueError('The actual teacher/ordinary mapping changed')
        source=(root/context['readonly_entrypoint']).read_text();initial=read(root/context['initial_state'])
        for request in (original,teacher,student):
            packet=request['task_packet']
            if (packet['documents'].get('readonly_generator_py')!=source or packet['allowed_paths']!=MODULES
                    or packet['visible_sources']!=initial['base_source']):
                raise ValueError('Complete readonly caller and both source modules must be equally visible')
        registry=read(root/context['effective_registry'])
        if [p['configuration_id'] for p in registry['configurations']]!=expected_points:
            raise ValueError('Keep the entire original nine-point domain and registry order')
    if any(name not in identity for name in required):raise ValueError('Natural-terminal context/evidence input is not frozen')
    audit=read(root/'baseline_audit.json')
    if (audit.get('phase')!='formal_train' or not audit.get('all_eighteen_points_complete')
            or len(audit.get('records',[]))!=18
            or any(not r.get('S2') or not r.get('full_RC_device_graph_clean') for r in audit['records'])):
        raise ValueError('All eighteen fresh formal controls and actual fullRC graph proofs are required')
    flights=read(root/'teacher_context_preflight.json')
    if len(flights)!=2 or any(not f.get('actual_fresh_formal_feedback') or f.get('source_or_contract_truncated') is not False
            or any(not f['token_counts'][k]['fits_with_full_output_reserve'] for k in ['teacher','student']) for f in flights):
        raise ValueError('Both complete contexts with actual fresh feedback must fit')
    return manifest
