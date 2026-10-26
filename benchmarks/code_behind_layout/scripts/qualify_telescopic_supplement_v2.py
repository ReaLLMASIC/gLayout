"""Finite telescopic audit correction; the v1 driver/snapshot remain unchanged.

prepare only reopens real saved evidence. full is a separately authorized,
once-only continuation: one verified original raw plus at most24 new points.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_telescopic_supplement import SERVER, TARGET, read, save, digest, validate
from scripts.qualify_telescopic_supplement import resource_gate, verify_ideal_family

ORIGINAL = SERVER/'runtime/task_preparation/telescopic_supplement_5x5_v1'
IDEAL = SERVER/'runs/development/telescopic_supplement_qualification/ideal_v1'
PRIOR = SERVER/'runs/development/telescopic_supplement_qualification/full_v1'
PREPARATION = SERVER/'runtime/task_preparation/telescopic_supplement_5x5_audit_v2'
OUTPUT = SERVER/'runs/development/telescopic_supplement_qualification/full_v2'
PAUSE = SERVER/'logs/telescopic_supplement_full_v2/PAUSE_REQUESTED'
ORIGINAL_SHA = '0a2389b5a2861deb3fad03303cf10d2a80fa7c924eb1925a096aad64a1ad02c0'
NODES = {'VDD':'vdd', 'GND':'0', 'IBIAS':'bias', 'VBN':'vbn', 'VBP':'vbp',
         'VP':'vp', 'VN':'vn', 'VOUT':'out'}


def verify_decks(evidence, pex, corners):
    ports = pex['ports']; checked = []
    for corner in corners:
        for analysis in ['op', 'ac', 'transient', 'dc']:
            binding = dict(NODES)
            if analysis in ['transient', 'dc']: binding['VN'] = 'out'
            path = evidence/'post_rc_measurements'/corner/(analysis+'.spice')
            lines = [line.split() for line in path.read_text().splitlines() if line.split()]
            actual = [line for line in lines if line[0].upper() == 'XDUT']
            expected = ['XDUT', *(binding[p.upper()] for p in ports), pex['top_cell']]
            if len(actual) != 1 or [s.upper() for s in actual[0]] != [s.upper() for s in expected]:
                raise ValueError('Actual XDUT terminal mapping differs from unchanged original bench')
            includes = [line[1:] for line in lines if line[0].lower() == '.include']
            if includes != [['/evidence/'+pex['netlist']]]:
                raise ValueError('Actual bench does not include the original unsimplified PEX')
            checked.append(str(path.relative_to(evidence)))
    return checked


def full_rc_audit(run, task, point, output):
    from scripts.audit_train_pair_nf_rc import contracted_devices
    from src.device_intent import compare_device_intent
    from src.training import TrustedPhysicalStore
    started, cpu = time.monotonic(), time.process_time()
    audit = {'status':'QUARANTINED_UNKNOWN', 'required_after_S1':True,
        'original_RC_changed':False, 'audit_view_never_simulated':True}
    try:
        evidence = run/'evidence'; validation = read(evidence/'validation.json')
        if validation['contract'] != point['contract']: raise ValueError('Independent point contract differs')
        pex = validation['artifacts']['pex']; ports = pex['ports']
        if (len(ports) != len(task['ports']) or len(set(p.upper() for p in ports)) != len(ports)
                or set(p.upper() for p in ports) != set(p.upper() for p in task['ports'])
                or pex['top_cell'] != task['top_cell']+'_rc'):
            raise ValueError('Full-RC top/named ports differ from independent N')
        path = TrustedPhysicalStore._file(evidence, pex['netlist']); before = path.read_bytes()
        reference = TrustedPhysicalStore._file(run/'trusted', 'reference.spice')
        if reference.read_bytes() != Path(point['reference_file']).read_bytes():
            raise ValueError('Independent reference bytes changed')
        decks = verify_decks(evidence, pex, point['contract']['required_corners'])
        view = contracted_devices(before.decode(), pex['top_cell'], ports)
        graph = compare_device_intent(view, reference.read_text())
        if path.read_bytes() != before: raise ValueError('The original physical RC bytes changed during audit')
        audit.update(status='RC_DEVICE_GRAPH_MATCH' if graph['is_clean'] else 'QUARANTINED_MISMATCH',
            actual_PEX_port_order=ports, independent_header_order=task['ports'],
            actual_decks_checked=decks, original_PEX_bytes_unchanged=True, graph=graph)
        if not graph['is_clean']: audit['error'] = 'Actual fullRC device/terminal graph differs from independent N'
    except (ValueError, OSError, KeyError, TypeError) as error:
        audit['error'] = type(error).__name__+': '+str(error)
    finally:
        audit.update(wall_seconds=time.monotonic()-started, parent_CPU_seconds=time.process_time()-cpu)
        save(output/'full_rc_intent_audit.json', audit)
    return audit


def actual_ledger(run):
    """Read returned process telemetry independently of host admission success."""
    result = {'actual_costs_by_stage':{}, 'actual_SPICE_calls':None, 'process_ledger_missing':True}
    manifest = read(run/'manifest.json')
    for stage in ['candidate', 'trusted']:
        entry = manifest.get(stage) or {}; path = run/(stage+'_stage/resource_usage.json')
        usage = read(path) if path.is_file() else None
        if not entry and usage is None: continue
        result['actual_costs_by_stage'][stage] = {
            'wall_seconds':entry.get('wall_seconds', usage.get('wall_seconds') if usage else None),
            'returncode':entry.get('returncode', usage.get('returncode') if usage else None),
            'waited_child_CPU_seconds':usage['child_user_cpu_seconds']+usage['child_system_cpu_seconds'] if usage else None,
            'CPU_scope':'actual waited child processes' if usage else 'missing; no allocated CPU estimate'}
    path = run/'evidence/post_rc_measurements/actual_processes.json'
    if path.is_file():
        calls = read(path)
        result.update(actual_SPICE_calls=len(calls), process_ledger_missing=False,
            actual_SPICE_returncode0=sum(c['returncode'] == 0 for c in calls),
            actual_SPICE_error_count=sum(bool(c.get('error')) for c in calls))
    elif not manifest.get('trusted'):
        result.update(actual_SPICE_calls=0, process_ledger_missing=False,
            actual_SPICE_returncode0=0, actual_SPICE_error_count=0)
    return result


def inspect_existing(task, point, run, output):
    from src.domain_runner import inspect_point, source_contents
    from src.training import TrustedPhysicalStore
    started, cpu = time.monotonic(), time.process_time()
    output.mkdir(parents=True, exist_ok=False)
    record = {'configuration_id':point['configuration_id'], 'raw_directory':str(run),
        'checked':{'S0':False,'S1':False,'S2':False,'execution_integrity':'incomplete','failure_class':'unknown'},
        'Store_development_check':None,'full_RC_device_port_audit':None,
        'actual_SPICE_calls':None,'new_model_calls':0,'formal_training_label':False}
    try:
        manifest = read(run/'manifest.json'); record['origin_run_id'] = manifest['run_id']
        configuration = {'parameters':point['parameters']}
        expected = source_contents(Path(task['source_pack']), task['source_files'], binary=True)
        checked = inspect_point({**manifest, 'run_directory':str(run)}, point, expected, configuration, gold_control_check=False)
        record['checked'] = checked
        if checked['S1']:
            audit = full_rc_audit(run, task, point, output); record['full_RC_device_port_audit'] = audit
            if audit['status'] != 'RC_DEVICE_GRAPH_MATCH':
                checked.update(S2=False, execution_integrity='incomplete', failure_class='unknown', reason=audit.get('error'))
        if checked['S2'] and checked['execution_integrity'] == 'valid':
            source = Path(task['source_pack'])
            dry = {**point, 'parameters':configuration, 'source_files':task['source_files'],
                'editable_paths':[TARGET], 'lineage_editable_paths':[TARGET],
                'frozen_source_files':[n for n in task['source_files'] if n != TARGET],
                'frozen_source_pack':str(source), 'intent_reference_path':'reference.spice',
                'trusted_evaluator_files':{n:(Path(point['trusted_dir'])/n).read_text() for n in point['trusted_files']}}
            record['Store_development_check'] = TrustedPhysicalStore.inspect_development_run(run, dry, {TARGET:(source/TARGET).read_text()})
            if not record['Store_development_check']['S2']: raise ValueError('Current Store contradicts saved physical point')
    except Exception as error:
        record['error'] = type(error).__name__+': '+str(error)
        record['checked'].update(S2=False, execution_integrity='incomplete', failure_class='unknown', reason=record['error'])
    finally:
        try: record.update(actual_ledger(run))
        except (ValueError, OSError, KeyError, TypeError) as error:
            record['cost_or_process_ledger_error'] = type(error).__name__+': '+str(error)
        record.update(readback_wall_seconds=time.monotonic()-started, readback_parent_CPU_seconds=time.process_time()-cpu)
        save(output/'point.json', record)
    return record


def verify_carry(record):
    if (record['checked']['execution_integrity'] != 'valid' or not record['checked']['S2']
            or not (record.get('Store_development_check') or {}).get('S2')
            or (record.get('full_RC_device_port_audit') or {}).get('status') != 'RC_DEVICE_GRAPH_MATCH'
            or record['actual_SPICE_calls'] != 12 or record.get('actual_SPICE_returncode0') != 12
            or record.get('actual_SPICE_error_count') != 0):
        raise ValueError('The one original raw is not fully established; never request a replacement')


def fixed_continuation(task, prior):
    rows = task['configurations']; attempted = [(k,v) for k,v in prior['points'].items() if v.get('actual_point_calls')]
    if len(rows) != 25 or len({p['configuration_id'] for p in rows}) != 25:
        raise ValueError('Exactly the original25 distinct points are required')
    if (prior['phase'] != 'full' or prior['status'] != 'UNKNOWN_STOPPED' or len(attempted) != 1
            or attempted[0][0] != rows[0]['configuration_id'] or attempted[0][1]['actual_point_calls'] != 1):
        raise ValueError('Carry-forward is limited to the actual first and only prior attempt')
    return rows[0], rows[1:]


def prepare():
    started, cpu = time.monotonic(), time.process_time()
    if ROOT != SERVER: raise ValueError('Private execution endpoint only')
    if digest(ORIGINAL/'private/manifest.json') != ORIGINAL_SHA: raise ValueError('Original fixed preparation differs')
    task = verify_ideal_family(ORIGINAL, IDEAL); prior = read(PRIOR/'state.json')
    point, remaining = fixed_continuation(task, prior)
    PREPARATION.mkdir(parents=True, exist_ok=False); PREPARATION.chmod(0o700)
    private = PREPARATION/'private'; private.mkdir(mode=0o700)
    raw = Path(prior['points'][point['configuration_id']]['raw_directory'])
    record = inspect_existing(task, point, raw, private/'carry_forward'); verify_carry(record)
    (private/'task.json').write_bytes((ORIGINAL/'private/task.json').read_bytes())
    old = read(ORIGINAL/'private/manifest.json')
    implementations = {**old['implementation_sha256'], 'scripts/qualify_telescopic_supplement_v2.py':digest(Path(__file__))}
    manifest = {'status':'DRAFT_TELESCOPIC_AUDIT_V2_PREPARED_NO_NEW_EDA',
        'original_preparation':str(ORIGINAL), 'original_preparation_manifest_sha256':ORIGINAL_SHA,
        'original_ideal_output':str(IDEAL), 'original_full_output':str(PRIOR),
        'original_full_state_sha256':digest(PRIOR/'state.json'),
        'declared_order':[p['configuration_id'] for p in task['configurations']],
        'carry_configuration_id':point['configuration_id'], 'carry_run_directory':str(raw), 'carry_origin_run_id':record['origin_run_id'],
        'old_status_retained':'UNKNOWN_STOPPED', 'remaining_order':[p['configuration_id'] for p in remaining],
        'maximum_new_physical_calls':24, 'maximum_new_SPICE_calls':288,
        'maximum_dispatch_seconds':86400, 'CPUs':2, 'memory_GiB':8,
        'generation_timeout_seconds':240, 'evaluator_timeout_seconds':3000,
        'output':str(OUTPUT), 'pause_file':str(PAUSE), 'automatic_retry':False,
        'implementation_sha256':implementations,
        'snapshot_sha256':{str(p.relative_to(private)):digest(p) for p in private.rglob('*') if p.is_file()}}
    save(private/'manifest.json', manifest)
    public = {'status':manifest['status'], 'declared_configurations':25, 'verified_carry_forward':1,
        'maximum_new_physical_calls':24, 'maximum_new_SPICE_calls':288, 'new_EDA_or_model_calls':0,
        'old_status_or_raw_rewritten':False, 'actual_origin_SPICE_calls':12,
        'carry_current_Store_S2':True, 'carry_fullRC_graph_clean':True,
        'carry_original_costs_charged_again':False, 'carry_origin_run_id':record['origin_run_id'],
        'preparation_wall_seconds':time.monotonic()-started, 'preparation_parent_CPU_seconds':time.process_time()-cpu,
        'manifest':str(private/'manifest.json'), 'manifest_sha256':digest(private/'manifest.json'),
        'pause_file':str(PAUSE), 'new_dispatch_authorized':False}
    save(PREPARATION/'public_summary.json', public)
    for p in private.rglob('*'):
        if p.is_file(): p.chmod(0o444)
    for p in sorted(private.rglob('*'), reverse=True):
        if p.is_dir(): p.chmod(0o500)
    private.chmod(0o500)
    return public


def verify_preparation():
    private = PREPARATION/'private'; m = read(private/'manifest.json')
    if m['status'] != 'DRAFT_TELESCOPIC_AUDIT_V2_PREPARED_NO_NEW_EDA': raise ValueError('Wrong limited qualification plan')
    if m['original_preparation_manifest_sha256'] != ORIGINAL_SHA or digest(ORIGINAL/'private/manifest.json') != ORIGINAL_SHA:
        raise ValueError('Original domain binding differs')
    task = validate(ORIGINAL)
    if (private/'task.json').read_bytes() != (ORIGINAL/'private/task.json').read_bytes(): raise ValueError('Task bytes differ')
    if digest(PRIOR/'state.json') != m['original_full_state_sha256']: raise ValueError('Original terminal status changed')
    for n, value in m['implementation_sha256'].items():
        if digest(ROOT/n) != value: raise ValueError('Implementation drift: '+n)
    for n, value in m['snapshot_sha256'].items():
        if digest(private/n) != value: raise ValueError('Prepared evidence drift: '+n)
    point, remaining = fixed_continuation(task, read(PRIOR/'state.json'))
    if m['remaining_order'] != [p['configuration_id'] for p in remaining] or m['declared_order'] != [p['configuration_id'] for p in task['configurations']]:
        raise ValueError('Original fixed order changed')
    return m, task, point, remaining


def full_point(task, point, output, deadline):
    from src.candidate_executor import CandidateExecutor
    record = {'configuration_id':point['configuration_id'], 'new_physical_calls':1,
        'checked':{'S0':False, 'S1':False, 'S2':False, 'execution_integrity':'incomplete', 'failure_class':'unknown'},
        'actual_SPICE_calls':None, 'new_model_calls':0}
    run = None
    try:
        executor = CandidateExecutor(ROOT/'runtime/GLdev', output/'physical', ROOT/'runtime/magic-8.3.685', timeout=3000)
        result = executor.execute(source_dir=Path(task['source_pack']), source_paths=task['source_files'], entrypoint=task['entrypoint'],
            representation='G2', configuration={'parameters':point['parameters']}, trusted_dir=point['trusted_dir'], trusted_paths=point['trusted_files'],
            fidelity='pex_spice', phase='development_telescopic_supplement_qualification_v2',
            context={'source_role':'trusted_evaluator_control', 'candidate_id':task['task_id'], 'initial_state_id':task['task_id'],
                'parent_lineage':task['parent_lineage'], 'configuration_id':point['configuration_id'],
                'reference_id':point['reference_id'], 'pdk_revision':point['pdk_revision']},
            generation_timeout_seconds=240, evaluator_timeout_seconds=3000,
            execution_deadline_utc=datetime.fromtimestamp(deadline, timezone.utc).isoformat())
        run = Path(result['run_directory'])
        record.update(inspect_existing(task, point, run, output/'readback'))
    except Exception as error:
        record.update(error=type(error).__name__+': '+str(error))
    finally:
        if run is None:
            found = list((output/'physical').glob('*/manifest.json'))
            if len(found) == 1: run = found[0].parent
        if run is not None:
            record['raw_directory'] = str(run)
            try: record.update(actual_ledger(run))
            except (ValueError, OSError, KeyError, TypeError) as error:
                record['cost_or_process_ledger_error'] = type(error).__name__+': '+str(error)
        save(output/'point.json', record)
    return record


def run():
    if ROOT != SERVER: raise ValueError('Private execution endpoint only')
    started, cpu = time.monotonic(), time.process_time(); deadline = time.time()+86400
    m, task, point, remaining = verify_preparation()
    OUTPUT.mkdir(parents=True, exist_ok=False); OUTPUT.chmod(0o700)
    state = {'status':'VERIFYING_CARRY_FORWARD', 'phase':'full_audit_v2', 'scope':'development_qualification_not_formal_not_training',
        'preparation':str(PREPARATION), 'points':{p['configuration_id']:{'status':'NOT_RUN', 'actual_point_calls':0} for p in task['configurations']},
        'resource_samples':[], 'new_model_calls':0, 'automatic_retry':False,
        'deadline_utc':datetime.fromtimestamp(deadline, timezone.utc).isoformat(), 'pause_file':str(PAUSE)}
    def checkpoint():
        temp = OUTPUT/'state.tmp'; save(temp, state); temp.replace(OUTPUT/'state.json')
    checkpoint()
    try:
        carry = inspect_existing(task, point, Path(m['carry_run_directory']), OUTPUT/'carry_forward'); verify_carry(carry)
        if carry['origin_run_id'] != m['carry_origin_run_id']: raise ValueError('Carry-forward original run identity changed')
        state['points'][point['configuration_id']].update(status='PASS', carried_forward=True,
            origin_run_id=carry['origin_run_id'], raw_directory=carry['raw_directory'], actual_point_calls=0,
            origin_SPICE_calls=carry['actual_SPICE_calls'], origin_costs_not_charged_again=carry['actual_costs_by_stage'],
            new_readback_wall_seconds=carry['readback_wall_seconds'], new_readback_CPU_seconds=carry['readback_parent_CPU_seconds'])
        state['status'] = 'RUNNING'; checkpoint()
        for p in remaining:
            ident = p['configuration_id']; entry = state['points'][ident]
            if PAUSE.exists(): state['status'] = 'PAUSE_REQUESTED'; break
            resource_gate(deadline, state['resource_samples']); checkpoint(); verify_preparation()
            if PAUSE.exists(): state['status'] = 'PAUSE_REQUESTED'; break
            if time.time() >= deadline: raise TimeoutError('The original24h UTC phase window expired')
            entry.update(status='RUNNING', actual_point_calls=1); checkpoint()
            work = OUTPUT/ident; work.mkdir()
            actual = full_point(task, p, work, deadline)
            entry.update({k:actual.get(k) for k in ['raw_directory','origin_run_id','actual_costs_by_stage','actual_SPICE_calls','actual_SPICE_returncode0','actual_SPICE_error_count','process_ledger_missing','error']})
            entry['checked'] = actual['checked']
            if actual['checked']['execution_integrity'] != 'valid':
                entry['status'] = 'UNKNOWN_STOPPED'; state['status'] = 'UNKNOWN_STOPPED'; checkpoint(); break
            entry['status'] = 'PASS' if actual['checked']['S2'] else 'COMPLETE_SHORTFALL'; checkpoint()
        else:
            state['status'] = 'QUALIFICATION_COMPLETE_PASS' if all(v['status'] == 'PASS' for v in state['points'].values()) else 'QUALIFICATION_COMPLETE_SHORTFALL'
    except Exception as error:
        state.update(status='UNKNOWN_STOPPED', error=type(error).__name__+': '+str(error))
    finally:
        state.update(coordinator_wall_seconds=time.monotonic()-started, coordinator_parent_CPU_seconds=time.process_time()-cpu)
        checkpoint()
    rows = list(state['points'].values()); fresh = [v for v in rows if v['actual_point_calls']]
    public = {'status':state['status'], 'scope':state['scope'], 'declared_configurations':25,
        'carried_configurations':sum(bool(v.get('carried_forward')) for v in rows),
        'new_physical_calls':len(fresh), 'actual_new_SPICE_calls_known':sum(v.get('actual_SPICE_calls') or 0 for v in fresh),
        'fresh_process_ledger_missing':sum(v.get('actual_SPICE_calls') is None for v in fresh),
        'complete_configurations':sum(v['status'] in ['PASS','COMPLETE_SHORTFALL'] for v in rows),
        'passed_configurations':sum(v['status'] == 'PASS' for v in rows), 'not_run':sum(v['status'] == 'NOT_RUN' for v in rows),
        'coordinator_wall_seconds':state['coordinator_wall_seconds'], 'coordinator_parent_CPU_seconds':state['coordinator_parent_CPU_seconds'],
        'new_model_calls':0, 'formal_training_labels':0, 'formal_policy_trials':0, 'formal_admission':False,
        'hidden_vectors_exported':False, 'original_status_or_raw_rewritten':False, 'original_physical_cost_charged_again':False}
    save(OUTPUT/'public_summary.json', public)
    return public


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--mode', choices=['prepare','validate','full'], required=True)
    a = parser.parse_args()
    if a.mode == 'prepare': result = prepare()
    elif a.mode == 'validate':
        m, _, _, remaining = verify_preparation(); result = {'status':'DRAFT_AUDIT_V2_VALID_NO_NEW_EDA', 'remaining':len(remaining), 'manifest_sha256':digest(PREPARATION/'private/manifest.json')}
    else: result = run()
    print(json.dumps(result, indent=2, allow_nan=False))
