"""Sealed supplementary QoR, conditional on common feasibility.

No primary endpoint is changed. Pure arithmetic accepts only explicit point
states; the server reader opens private measurements only after shared release
and the complete public evaluation/baseline gates.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
from statistics import mean
import tarfile
import tempfile

from src.e1_analysis import _quantile

METHODS = ('A', 'R', 'B', 'C')
PASS, FAIL, UNKNOWN = 'actual_S2_positive_finite_Q', 'known_infeasible', 'unknown_or_NOT_RUN'


def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def declaration(path, manifest_path):
    path, manifest_path = Path(path), Path(manifest_path)
    rule, manifest = read(path), read(manifest_path)
    if (rule.get('status') != 'FROZEN_E3_HIDDEN_QOR_SUPPLEMENT' or path.stat().st_mode & 0o222
            or manifest.get('status') != 'FROZEN_E3'
            or rule['applies_to_freeze_id'] != manifest['freeze_id']
            or rule['execution_manifest_sha256'] != digest(manifest_path)):
        raise ValueError('Actual readonly supplementary declaration and original freeze must match')
    binding_path = path.parent/'binding.json'; binding = read(binding_path)
    if (binding_path.stat().st_mode & 0o222 or binding.get('status') != 'SEALED_INDEPENDENT_E3_QOR_ANALYSIS_DECLARATION'
            or binding['declaration_sha256'] != digest(path)
            or binding['execution_manifest_sha256'] != digest(manifest_path)
            or binding['sealed_at_utc'] != rule['sealed_at_utc']):
        raise ValueError('Supplement differs from its actual independent seal metadata')
    if (rule['uncertainty']['replicates'] != manifest['analysis']['cluster_bootstrap_replicates']
            or rule['uncertainty']['seed'] != manifest['analysis']['bootstrap_seed']):
        raise ValueError('Supplement must preserve the original bootstrap draw count/seed')
    return rule, manifest


def point_state(row):
    if row is None or row.get('checked', {}).get('execution_integrity') != 'valid': return UNKNOWN
    if row['checked'].get('S2') is not True: return FAIL
    value = row.get('objective')
    return PASS if type(value) in (int, float) and math.isfinite(value) and value > 0 else UNKNOWN


def log_gain(old, new, direction):
    if point_state(old) != PASS or point_state(new) != PASS: return None
    value = math.log(new['objective'])-math.log(old['objective'])
    return value if direction == 'max' else -value


def state_table(original, selected, identifiers):
    table = {a: {b: 0 for b in (PASS, FAIL, UNKNOWN)} for a in (PASS, FAIL, UNKNOWN)}
    for ident in identifiers: table[point_state(original.get(ident))][point_state(selected.get(ident))] += 1
    return {'declared_hidden': 16, 'state_count_table': table, 'eligible_count': table[PASS][PASS],
        'verified_regressions': table[PASS][FAIL], 'verified_recoveries': table[FAIL][PASS],
        'unknown_or_NOT_RUN_pairs': sum(table[a][b] for a in table for b in table[a] if UNKNOWN in (a,b))}


def interval(rows, group_key, replicates, seed):
    grouped = defaultdict(list)
    for row in rows: grouped[row[group_key]].append(row['effect'])
    if not rows: return {'actual_clusters': 0, 'task_mean_log_gain_difference': None, 'cluster_percentile_95_CI': None}
    result = {'actual_clusters': len(grouped), 'task_mean_log_gain_difference': mean(r['effect'] for r in rows),
        'cluster_percentile_95_CI': None, 'bootstrap_replicates': 0, 'bootstrap_seed': seed}
    if len(grouped) >= 2:
        rng = random.Random(seed); names = sorted(grouped); draws = []
        for _ in range(replicates):
            sampled = [rng.choice(names) for _ in names]
            draws.append(mean(value for name in sampled for value in grouped[name]))
        result.update(cluster_percentile_95_CI=[_quantile(draws,.025),_quantile(draws,.975)], bootstrap_replicates=replicates)
    return result


def analyze(manifest, tasks, originals, episodes, rule, *, complete_gate):
    """Pure software interface; input vectors never occur in the returned object."""
    metadata = {row['task_id']: row for row in manifest['tasks']}
    if len(metadata) != 24 or set(tasks) != set(metadata): raise ValueError('Exactly the actual24 frozen tasks are required')
    index = {}
    for row in episodes:
        key = row['task_id'], row['method'], str(row['trial_id'])
        if (key in index or key[0] not in metadata or key[1] not in METHODS or key[2] not in {'1','2','3','4','5'}):
            raise ValueError('Duplicate/foreign episode cannot alter the480-slot matrix')
        index[key] = row
    result = {'status': 'COMPLETE' if complete_gate and len(index)==480 else 'DESCRIPTIVE_ONLY_NOT_READY',
        'analysis_id': rule['analysis_id'], 'scope': 'SUPPLEMENTARY_CONDITIONAL_ON_COMMON_FEASIBILITY',
        'declared_tasks': 24, 'declared_episodes': 480, 'recorded_episodes': len(index),
        'NOT_RUN_episodes': 480-len(index), 'task_trial_quality': [], 'contrasts': [],
        'hidden_configuration_ids_or_vectors_exported': False, 'original_primary_unchanged': True}
    ready = result['status']=='COMPLETE'
    data_complete = True
    expected_pairs = {tuple(row) for row in rule['matched_method_contrasts']['contrasts']}
    if expected_pairs != {('C','R'),('C','B')}: raise ValueError('The supplementary contrasts changed')
    task_effects = {pair: [] for pair in sorted(expected_pairs)}
    contrast_counts = {pair: [] for pair in sorted(expected_pairs)}
    for ident, task in tasks.items():
        points = [p for p in task['configurations'] if p['role']=='hidden']
        identifiers = [p['configuration_id'] for p in points]
        if len(identifiers)!=16 or len(set(identifiers))!=16: raise ValueError('Hidden denominator must remain16 distinct points')
        definitions = [p['contract']['objective'] for p in points]
        if any(d != definitions[0] for d in definitions) or definitions[0]['direction'] not in ('min','max'):
            raise ValueError('Frozen objective definitions differ across this task')
        direction = definitions[0]['direction']; old = originals.get(ident,{})
        if not set(old).issubset(identifiers): raise ValueError('Original input includes foreign hidden identities')
        data_complete = data_complete and set(old)==set(identifiers) and all(point_state(row)!=UNKNOWN for row in old.values())
        trial_effects = {pair: [] for pair in task_effects}
        for trial in map(str,range(1,6)):
            vectors = {}
            for method in METHODS:
                record = index.get((ident,method,trial)); values = record['points'] if record else {}
                if not set(values).issubset(identifiers): raise ValueError('Selected input includes foreign hidden identities')
                vectors[method] = values
                data_complete = data_complete and set(values)==set(identifiers) and all(point_state(row)!=UNKNOWN for row in values.values())
                gains = [value for name in identifiers if (value:=log_gain(old.get(name),values.get(name),direction)) is not None]
                result['task_trial_quality'].append({'task_id':ident,'method':method,'trial_id':trial,
                    'objective_definition':definitions[0], **state_table(old,values,identifiers),
                    'mean_log_gain':mean(gains) if gains else None})
            for left,right in task_effects:
                effects = []; unknown = excluded = 0
                for name in identifiers:
                    states = [point_state(v.get(name)) for v in (old,vectors[left],vectors[right])]
                    if UNKNOWN in states: unknown += 1
                    elif states != [PASS,PASS,PASS]: excluded += 1
                    else: effects.append(log_gain(old[name],vectors[left][name],direction)-log_gain(old[name],vectors[right][name],direction))
                value = mean(effects) if effects else None; trial_effects[left,right].append(value)
                contrast_counts[left,right].append({'task_id':ident,'trial_id':trial,'declared_hidden':16,
                    'common_mask_count':len(effects),'unknown_or_NOT_RUN':unknown,'known_excluded':excluded,
                    'task_trial_effect':value})
        for pair, values in trial_effects.items():
            if all(value is not None for value in values):
                task_effects[pair].append({'task_id':ident,'effect':mean(values),
                    'source_group':metadata[ident]['source_group'],'merged_source_group':metadata[ident]['merged_source_group']})
    ready = ready and data_complete
    if not ready: result['status'] = 'DESCRIPTIVE_ONLY_NOT_READY'
    for pair, values in task_effects.items():
        result['contrasts'].append({'contrast':'-'.join(pair),'declared_tasks':24,'eligible_tasks':len(values),
            'undefined_tasks':24-len(values),'eligible_task_ids':[v['task_id'] for v in values],
            'task_trial_counts':contrast_counts[pair],
            'effect_status':'CONDITIONAL_COMPLETE' if ready and values else 'UNDEFINED_NO_ELIGIBLE_TASK' if ready else 'NOT_READY',
            'merged_cluster_analysis':interval(values,'merged_source_group',rule['uncertainty']['replicates'],rule['uncertainty']['seed']) if ready else None,
            'logical_cluster_sensitivity':interval(values,'source_group',rule['uncertainty']['replicates'],rule['uncertainty']['seed']) if ready else None})
    return result


@contextmanager
def read_only_run_view(run):
    """Decode a real compressed run in temporary space, never restore its source."""
    run = Path(run)
    if not (run/'evidence_archive.json').is_file():
        yield run; return
    from scripts.archive_e3_evidence import safe_member
    saved = read(run/'evidence_archive.json'); archive = Path(saved['archive'])
    if not archive.is_file() or archive.stat().st_size != saved['archive_bytes']:
        raise ValueError('Actual verified private evidence archive is unavailable')
    with tempfile.TemporaryDirectory(prefix='e3-qor-readonly-') as tmp:
        target = Path(tmp)
        for name in ('manifest.json','configuration.json'): shutil.copyfile(run/name,target/name)
        for name in ('source','trusted','accepted'):
            if (run/name).exists(): shutil.copytree(run/name,target/name)
        with tarfile.open(archive,'r:gz') as stream:
            for member in stream:
                if not safe_member(member): raise ValueError('Unexpected actual archive member')
                path = target/member.name
                if member.isdir(): path.mkdir(parents=True,exist_ok=True)
                else:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with stream.extractfile(member) as source,path.open('wb') as destination: shutil.copyfileobj(source,destination)
        yield target


def read_backend(manifest_path, declaration_path, baseline_output, episode_index):
    """Future server-only reader. Public completeness gates precede all vectors."""
    from scripts.e3_episode import require_release, verify
    from scripts.e3_original_baseline import load_plan, check_methods_freeze, point_inputs
    from scripts.e3_instance_episode import verify_cached
    from src.domain_runner import source_contents
    manifest_path = Path(manifest_path).resolve(); baseline_output = Path(baseline_output).resolve()
    rule, manifest = declaration(declaration_path,manifest_path); verify(manifest)
    if not Path(manifest['hidden_release_file']).is_file():
        return {'status':'NOT_READY_SHARED_RELEASE_ABSENT','private_vectors_read':False,'new_model_or_EDA_calls':0}
    release = require_release(manifest,baseline=True)
    if datetime.fromisoformat(rule['sealed_at_utc']) >= datetime.fromisoformat(release['created_at_utc']):
        raise ValueError('Supplementary declaration was not sealed before shared oracle release')
    index = read(episode_index); slots = {}; directories = {}
    expected = {(task['task_id'],method,str(trial)) for task in manifest['tasks'] for method in METHODS for trial in range(1,6)}
    for row in index:
        key = row['task_id'],row['method'],str(row['trial_id'])
        if (key not in expected or key in slots or row.get('policy_variant')!='GPT'
                or row.get('selector_variant','main')!='main' or row.get('part','gpt')!='gpt'):
            raise ValueError('Explicit main GPT index must not mix cohorts, repeats or ablations')
        slots[key] = row
        if row.get('episode_directory'):
            directory = Path(row['episode_directory']); report = directory/'public/episode.json'
            if report.is_file():
                public = read(report)
                if ((public['task_id'],public['method'],str(public['trial_id']))!=key
                        or public.get('formal_trial') is not True or public.get('policy_variant')!='GPT'):
                    raise ValueError('Actual public post-freeze identity differs from its fixed index')
                if public.get('post_freeze_complete') is True:
                    if (public.get('hidden_domain_size')!=16 or public.get('hidden_incomplete')!=0
                            or public.get('post_freeze_points_attempted')!=25 or public.get('post_freeze_points_NOT_RUN')!=0):
                        raise ValueError('Public full-domain completion contradicts its declared25/16 accounting')
                    directories[key] = directory
    summary_path = baseline_output/'public/summary.json'; summary = read(summary_path) if summary_path.is_file() else {}
    baseline_complete = (summary.get('status')=='COMPLETE' and summary.get('returned_points')==600
        and summary.get('valid_points')==600 and summary.get('unknown_points')==0)
    if set(slots)!=expected or set(directories)!=expected or not baseline_complete:
        return {'status':'DESCRIPTIVE_ONLY_NOT_READY','declared_main_episodes':480,
            'complete_public_post_episodes':len(directories),'declared_original_points':600,
            'valid_original_points':summary.get('valid_points',0),'private_vectors_read':False,
            'conditional_effects_or_CIs':None,'new_model_or_EDA_calls':0}
    binding = read(baseline_output/'private/binding.json')
    if Path(binding['manifest']).resolve()!=manifest_path:
        raise ValueError('Actual original baseline belongs to another method freeze')
    plan_root, plan = load_plan(manifest['original_baseline_plan'])
    check_methods_freeze(manifest_path,plan_root,plan)
    originals = {}; tasks = {}; selected = []

    def inspected(row, point, source, files, evaluator):
        run = row.get('run_directory') or row.get('checked',{}).get('run_directory')
        if not run: raise ValueError('An actual point has no physical run binding')
        expected_source = source_contents(source,files,binary=True)
        with read_only_run_view(run) as view:
            actual = verify_cached({**row,'run_directory':str(view)},expected_source,point,evaluator)
        if actual is None:
            return {'checked':{'execution_integrity':'incomplete','S2':False},'objective':None}
        return {'checked':actual['checked'],'objective':actual['objective']}

    for task_row in plan['tasks']:
        ident = task_row['task_id']; task = read(plan_root/task_row['task_file']); tasks[ident] = task; originals[ident] = {}
        for slot in task_row['points']:
            filename = baseline_output/'private/points'/ident/slot['configuration_id']/'point.json'
            row = read(filename)
            if (row['task_id']!=ident or row['configuration_id']!=slot['configuration_id']
                    or row['role']!=slot['role'] or row['fidelity']!='pex_spice'
                    or row['checked']['execution_integrity']!='valid'):
                raise ValueError('Actual original point contradicts the completed600-slot gate')
            if slot['role']=='hidden':
                _,point,source,evaluator = point_inputs(plan_root,task_row,slot)
                originals[ident][slot['configuration_id']] = inspected(row,point,source,task_row['source_files'],evaluator)
        for method in METHODS:
            for trial in map(str,range(1,6)):
                episode = directories[ident,method,trial]; require_release(manifest,episode)
                if read(episode/'private/manifest.json')!=manifest or read(episode/'private/task.json')!=task:
                    raise ValueError('Selected and original frozen task/reference/contract bindings differ')
                state = read(episode/'private/state.json')
                if state.get('in_flight') or not state.get('sealed') or state.get('formal_trial') is not True:
                    raise ValueError('Selected source is unsealed or unresolved')
                source = episode/'private'/('revisions/%03d/source'%state['selection']['revision'])
                rows = read(episode/'private/post_freeze_points.json')
                mapped = {row['configuration_id']:row for row in rows}
                if len(mapped)!=25 or len(rows)!=25 or set(mapped)!={p['configuration_id'] for p in task['configurations']}:
                    raise ValueError('Selected complete post-freeze report omitted or repeated a fixed point')
                vectors = {}
                for slot in task_row['points']:
                    row = mapped[slot['configuration_id']]
                    if row['role']!=slot['role'] or row['checked']['execution_integrity']!='valid':
                        raise ValueError('Selected25-point record contradicts public completeness')
                    if slot['role']=='hidden':
                        _,point,_,evaluator = point_inputs(plan_root,task_row,slot)
                        vectors[slot['configuration_id']] = inspected(row,point,source,task['source_files'],evaluator)
                selected.append({'task_id':ident,'method':method,'trial_id':trial,'points':vectors})
    report = analyze(manifest,tasks,originals,selected,rule,complete_gate=True)
    report.update(freeze_id=manifest['freeze_id'],declaration_sha256=digest(declaration_path),
        actual_shared_release=manifest['hidden_release_file'],private_vectors_read=True,
        original_records_modified=False,new_model_or_EDA_calls=0)
    return report
