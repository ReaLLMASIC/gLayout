"""Separate E3 F0/F3 data-layer consumer; never calls EpisodeState.observe.

F3 acquires physical RC once from the complete edited source, then an actual
TT OP/AC observation on that RC. A copied train/validation calibration may
defer an empirically screened point. Deferred is not a physical failure, and a
delivered source still needs actual full checks. Components use original F0.
The caller owns resource admission, common UTC budgets and final source choice.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.e3_physical_point import evaluate as original_full
from scripts.e3_task_prepare import capsule
from scripts.e2_execution import COPY, measured_cost
from scripts.e2_stage_prepare import build, cached
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point, source_contents
from src.e1_benchmarks import build_trusted
from src.promotion_calibration import NominalWorstCalibration


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def prediction_decision(nominal, prediction, contract):
    """Empirical screen only; no predicted pass or actual counterexample."""
    result = {'action':'promote_full','force_full':True,'reason':None,
        'prediction_establishes_S2':False,'is_actual_counterexample':False}
    if not nominal.get('complete') or not nominal.get('operating_point_valid'):
        return {**result,'reason':'nominal_incomplete_or_unhealthy'}
    if prediction is None:
        return {**result,'reason':'nominal_has_no_usable_calibrated_UGB'}
    if prediction['force_full']:
        return {**result,'reason':prediction['reason']}
    ugb = next((spec for spec in contract['specifications'] if spec['name']=='ugb' and spec['unit']=='Hz'),None)
    if ugb and 'min' in ugb and prediction['upper_ugb_Hz'] < ugb['min']:
        return {**result,'action':'screened_deferred','force_full':False,
            'reason':'empirical_upper_UGB_below_declared_minimum','UGB_minimum_Hz':ugb['min'],
            'verified_source_selection_eligible':False,'requires_actual_full_before_verified_delivery':True}
    return {**result,'force_full':False,
        'reason':'UGB_interval_does_not_screen_out_other_corner_constraints_and_objective_need_actual_full'}


def calibration(path, task, formal):
    artifact = read(path)
    if (artifact.get('coefficient_fit_split')!='train_only' or
        artifact.get('residual_and_support_selection_split')!='train_and_validation_only' or
        artifact.get('S2_is_established_by_prediction') is not False):
        raise ValueError('F3 accepts the independent train/validation UGB artifact only')
    if formal and artifact.get('formal_calibration_freeze') is not True:
        raise ValueError('Formal F3 needs a prospectively frozen calibration artifact')
    for split in ['train','validation']:
        rows = artifact.get(split+'_rows')
        if not rows or any(row.get('split')!=split or not row.get('raw_evidence') or
                row.get('actual_three_corner_AC_complete') is not True for row in rows):
            raise ValueError('Calibration lacks actual '+split+' AC provenance')
    used = set(artifact['train_source_lineages'])|set(artifact['validation_source_lineages'])
    if set(artifact['train_source_lineages']) & set(artifact['validation_source_lineages']):
        raise ValueError('Training and validation calibration source lineages overlap')
    if task['parent_lineage'] in used:
        raise ValueError('An E3 evaluation source cannot be its promotion calibration source')
    return artifact, NominalWorstCalibration(artifact)


def physical_stage_status(result, point, expected):
    """Actual physical rejection is distinct from deferred electrical analysis."""
    raw = result.get('physical_result') or {}
    if raw.get('requested_fidelity_complete') and raw.get('assessment',{}).get('S1'):
        return 'admitted_actual_PEX', None
    run = Path(result['run_directory'])
    manifest = read(run/'manifest.json')
    if manifest['status']=='BUDGET_EXHAUSTED':
        return 'budget_exhausted', None
    if raw.get('failure_class')=='candidate' or manifest['status'] in ['CANDIDATE_FAILED','REJECTED_OUTPUT']:
        checked = inspect_point(result,point,expected,{'parameters':point['parameters']},gold_control_check=False)
        if checked['execution_integrity']=='valid' and checked['failure_class']=='candidate':
            return 'actual_physical_rejection', checked
    return 'incomplete_physical_unknown', None


def finish_full(handle_path, *, deadline=None):
    """Complete a deferred/promoted point from its original actual RC, no rerun."""
    handle_path = Path(handle_path)
    handle = read(handle_path)
    inside_primary = handle.get('status')=='promote_full'
    began, host_cpu = time.monotonic(), time.thread_time()
    if handle.get('full_actual') is not None or handle.get('full_attempt_started'):
        raise ValueError('This point already has a full attempt; inspect it instead of rerunning')
    if handle['physical_status']!='admitted_actual_PEX':
        raise ValueError('A full electrical stage needs the original admitted PEX')
    out = handle_path.parent
    point = read(out/'point_binding.json')
    task = read(out/'task_binding.json')
    physical = handle['physical_actual']
    physical_run = Path(physical['run_directory'])
    original_manifest = read(physical_run/'manifest.json')
    if source_contents(physical_run/'source',original_manifest['source_files'],binary=True)!=source_contents(
            Path(handle['source']),task['source_files'],binary=True):
        raise ValueError('The complete editing source changed since its GDS/PEX acquisition')
    source = out/'retained_GDS_source'
    expected = source_contents(source,['generator.py','input.gds'],binary=True)
    trusted = out/'full_cached_trusted'
    files = cached(trusted,point=point,full_trusted=out/'original_full_trusted',physical_run=physical_run)
    (trusted/'evaluate.py').rename(trusted/'original_physical_evaluate.py')
    shutil.copyfile(ROOT/'scripts/e3_trusted_objective.py',trusted/'evaluate.py')
    files = sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
    executor = CandidateExecutor(ROOT/'runtime/GLdev',out/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
    handle.update(full_attempt_started=True,full_attempt_started_at_utc=datetime.now(timezone.utc).isoformat())
    handle['costs'].update(full_requests=1,actual_full_SPICE_calls=None)
    write(handle_path,handle)
    result = executor.execute(source_dir=source,source_paths=['generator.py','input.gds'],entrypoint='generator.py',
        representation='G0',configuration={'parameters':point['parameters']},trusted_dir=trusted,trusted_paths=files,
        fidelity='pex_spice',phase='formal_E3' if handle['formal_trial'] else 'development_E3_fidelity_integration',
        context={**handle['execution_context'],'stage':'full_electrical_on_exact_retained_PEX'},
        generation_timeout_seconds=30,evaluator_timeout_seconds=720,
        **({'execution_deadline_utc':deadline} if deadline else {}))
    try:
        execution = read(Path(result['run_directory'])/'manifest.json')
        if execution['status']=='BUDGET_EXHAUSTED':
            checked = {'S0':False,'S1':False,'S2':False,'execution_integrity':'budget_exhausted',
                'failure_class':'budget','reason':'Common UTC deadline; not a circuit-negative label'}
        else:
            checked = inspect_point(result,point,expected,{'parameters':point['parameters']},gold_control_check=False)
    except (OSError,ValueError,KeyError,TypeError) as error:
        checked = {'S0':False,'S1':False,'S2':False,'execution_integrity':'incomplete',
            'failure_class':'unknown','reason':type(error).__name__+': '+str(error)}
    raw = result.get('physical_result') or {}
    definition = point['contract']['objective'];objective = None
    objective_raw = None
    if checked['S2']:
        if definition.get('corner_aggregation')!='worst' or definition['direction'] not in ['max','min']:
            raise ValueError('The E3 objective must retain its declared worst-corner aggregation')
        metrics = [raw['observation']['corners'][corner]['metrics'][definition['metric']]
            for corner in point['contract']['required_corners']]
        if any(metric['unit']!=definition['unit'] or type(metric['value']) not in (int,float)
                or not math.isfinite(metric['value']) for metric in metrics):
            raise ValueError('Actual full objective differs from the immutable E3 contract')
        values = [metric['value'] for metric in metrics]
        objective = min(values) if definition['direction']=='max' else max(values)
        objective_raw = {'definition':definition,'corner_metrics':dict(zip(point['contract']['required_corners'],metrics)),
            'worst_corner_value':objective,'all_original_analyses_independently_complete':checked['analysis_complete']}
    from scripts.e1_matched_runner import visible_feedback
    full = {'run_directory':result['run_directory'],'checked':checked,'objective':objective,
        'objective_definition':definition,'physical_feedback':visible_feedback(result),
        'objective_raw_validation':objective_raw,
        'actual_cost':measured_cost(result['run_directory']),'stage_wall_seconds':time.monotonic()-began,
        'source_to_GDS_origin':physical['run_directory'],'physical_PEX_reused_from':physical['run_directory'],
        'DRC_LVS_PEX_repeated_for_electrical':False}
    handle.update(full_actual=full,status='actual_full_returned')
    handle['costs']['stages'].append({'stage':'full_electrical_on_retained_PEX',**full['actual_cost'],
        'run_directory':result['run_directory']})
    full_execution = read(Path(result['run_directory'])/'manifest.json')
    handle['costs']['full_requests'] = 1
    handle['costs']['actual_full_evaluator_invocations'] = int('trusted' in full_execution)
    handle['costs']['actual_full_SPICE_calls'] = (raw.get('physical_tool_calls',{}).get('SPICE')
        if 'trusted' in full_execution else 0)
    handle['costs']['full_continuation_wall_seconds'] = time.monotonic()-began
    handle['costs']['full_continuation_host_thread_CPU_seconds'] = time.thread_time()-host_cpu
    handle['costs']['full_continuation_cost_is_inside_primary_point'] = inside_primary
    handle['final_verified_source_selection_eligible'] = bool(checked['S2'])
    write(handle_path,handle)
    return handle


def evaluate(task_path, configuration_id, output, source=None, *, policy='F0',
        calibration_path=None, allow_screening=False, deadline=None, formal=False):
    """Return nominal_actual/promotion_decision/full_actual as distinct evidence."""
    if policy not in ['F0','F3']:
        raise ValueError('This data consumer implements only the separate F0/F3 ablation')
    task_path, output = Path(task_path), Path(output)
    task = read(task_path)
    if formal and not (task.get('formal_admission') is True and task.get('status')=='FROZEN_E3_TASK'):
        raise ValueError('Formal E3 fidelity calls need a separately frozen admitted task')
    point = next(point for point in task['configurations'] if point['configuration_id']==configuration_id)
    began, host_cpu = time.monotonic(), time.thread_time()
    output.mkdir(parents=True,exist_ok=False)
    handle = {'scope':'E3_separate_F0_F3_data_layer_NOT_EpisodeState_observation','task_id':task['task_id'],
        'configuration_id':configuration_id,'fidelity_policy':policy,'formal_trial':formal,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'PREPARING','nominal_actual':None,'full_actual':None,
        'physical_actual':None,'prediction':None,'promotion_decision':None,
        'screened_is_an_actual_failure':False,'source':str(source) if source else None,
        'final_verified_source_selection_eligible':False,
        'costs':{'stages':[],'nominal_requests':0,'full_requests':0,
            'actual_nominal_evaluator_invocations':0,'actual_full_evaluator_invocations':0,
            'actual_nominal_SPICE_calls':0,'actual_full_SPICE_calls':0,
            'component_CPU_scope':'Actual per-container waited children. These are components, not extra allocated CPU estimates. Whole point wall includes stages; do not add it to stage walls.'}}
    handle_path = output/'fidelity_point.json'
    write(output/'task_binding.json',task);write(output/'point_binding.json',point)
    def save(): write(handle_path,handle)
    try:
        applicable = task['target'] in ['five_t','compact_miller']
        if policy=='F0' or not applicable or calibration_path is None:
            reason = ('F0_actual_full' if policy=='F0' else 'no_applicable_component_surrogate' if not applicable else 'missing_independent_calibration')
            if formal and policy=='F3' and applicable and calibration_path is None:
                raise ValueError('The formal OTA F3 ablation must bind its frozen calibration path')
            handle['promotion_decision']={'action':'promote_full','force_full':True,'reason':reason,
                'prediction_establishes_S2':False,'is_actual_counterexample':False}
            handle['costs'].update(full_requests=1,actual_full_SPICE_calls=None)
            save()
            full = original_full(task_path,configuration_id,output/'original_full',source,
                deadline=deadline,formal=formal)
            full['actual_cost'] = measured_cost(full['run_directory'])
            handle.update(full_actual=full,status='actual_full_returned',
                final_verified_source_selection_eligible=bool(full['checked']['S2']))
            full_execution = read(Path(full['run_directory'])/'manifest.json')
            handle['costs'].update(full_requests=1,actual_full_evaluator_invocations=int('trusted' in full_execution),
                stages=[{'stage':'original_full','run_directory':full['run_directory'],**full['actual_cost']}])
            if 'trusted' not in full_execution:
                handle['costs']['actual_full_SPICE_calls'] = 0
            if full['checked'].get('analysis_complete'):
                raw = read(Path(full['run_directory'])/'evidence/validation.json')
                logs = {item['log'] for corner in raw['artifacts']['spice'].values()
                    for item in corner['analyses'].values()}
                handle['costs']['actual_full_SPICE_calls'] = len(logs)
            return handle
        artifact, model = calibration(calibration_path,task,formal)
        write(output/'frozen_calibration_copy.json',artifact)
        handle['calibration_binding']={'original_file':str(Path(calibration_path).resolve()),
            'retained_copy':str(output/'frozen_calibration_copy.json'),
            'train_source_lineages':artifact['train_source_lineages'],
            'validation_source_lineages':artifact['validation_source_lineages'],
            'fit_or_support_changed_from_E3_outcomes':False}
        if source is None:
            source = output/'source';capsule(task_path,source)
        source = Path(source).resolve();handle['source'] = str(source)
        expected = source_contents(source,task['source_files'],binary=True)
        original_task = read(task['E1_binding'])
        full_trusted = output/'original_full_trusted'
        build_trusted(original_task,point,full_trusted)
        context = {'source_role':'formal_E3_candidate' if formal else 'development_E3_candidate',
            'candidate_id':task['task_id'],'initial_state_id':task['task_id'],'parent_lineage':task['parent_lineage'],
            'configuration_id':configuration_id,'reference_id':point['reference_id'],
            'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'}
        handle['execution_context'] = context
        executor = CandidateExecutor(ROOT/'runtime/GLdev',output/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
        pex_trusted = output/'physical_PEX_trusted'
        files = build('pex',pex_trusted,top=task['top_cell'],point=point,full_trusted=full_trusted)
        result = executor.execute(source_dir=source,source_paths=task['source_files'],entrypoint=task['entrypoint'],
            representation='G2',configuration={'parameters':point['parameters']},trusted_dir=pex_trusted,trusted_paths=files,
            fidelity='pex',phase='formal_E3' if formal else 'development_E3_fidelity_integration',
            context={**context,'stage':'complete_source_to_GDS_and_actual_PEX'},
            generation_timeout_seconds=240,evaluator_timeout_seconds=720,
            **({'execution_deadline_utc':deadline} if deadline else {}))
        physical_run = Path(result['run_directory'])
        if source_contents(physical_run/'source',task['source_files'],binary=True)!=expected:
            raise ValueError('The physical acquisition did not execute the complete exact editing source')
        status, rejected = physical_stage_status(result,point,expected)
        handle.update(physical_status=status,physical_actual={'run_directory':str(physical_run),
            'actual_cost':measured_cost(physical_run),'actual_physical_rejection':rejected})
        handle['costs']['stages'].append({'stage':'source_GDS_and_PEX',
            'run_directory':str(physical_run),**handle['physical_actual']['actual_cost']})
        save()
        if status!='admitted_actual_PEX':
            handle.update(status=status,promotion_decision={'action':'no_electrical_promotion',
                'reason':status,'is_actual_counterexample':rejected is not None,'prediction_establishes_S2':False})
            return handle
        retained = output/'retained_GDS_source';retained.mkdir()
        (retained/'generator.py').write_text(COPY)
        shutil.copyfile(physical_run/'accepted/candidate.gds',retained/'input.gds')
        nominal_trusted = output/'nominal_cached_trusted'
        cached(nominal_trusted,point=point,full_trusted=full_trusted,physical_run=physical_run,nominal=True)
        (nominal_trusted/'evaluate.py').rename(nominal_trusted/'original_nominal_evaluate.py')
        shutil.copyfile(ROOT/'scripts/e3_nominal_objective.py',nominal_trusted/'evaluate.py')
        files = sorted(str(p.relative_to(nominal_trusted)) for p in nominal_trusted.rglob('*') if p.is_file())
        nominal_run = executor.execute(source_dir=retained,source_paths=['generator.py','input.gds'],entrypoint='generator.py',
            representation='G0',configuration={'parameters':point['parameters']},trusted_dir=nominal_trusted,trusted_paths=files,
            fidelity='pex_spice',phase='formal_E3' if formal else 'development_E3_fidelity_integration',
            context={**context,'stage':'actual_nominal_TT_OP_AC'},generation_timeout_seconds=30,evaluator_timeout_seconds=720,
            **({'execution_deadline_utc':deadline} if deadline else {}))
        nominal_raw = nominal_run.get('physical_result') or {}
        nominal = nominal_raw.get('nominal') or {}
        if nominal_raw and (nominal_raw.get('S2') is not False or nominal_raw.get('point_evaluation_complete') is not False):
            raise ValueError('Nominal stage claimed a full correctness/performance result')
        handle['nominal_actual']={'run_directory':nominal_run['run_directory'],'measurement':nominal,
            'actual_bbox_area_um2':nominal_raw.get('actual_bbox_area_um2'),
            'actual_cost':measured_cost(nominal_run['run_directory']),'S2_established':False}
        handle['costs']['stages'].append({'stage':'actual_nominal_TT_OP_AC',
            'run_directory':nominal_run['run_directory'],**handle['nominal_actual']['actual_cost']})
        nominal_execution = read(Path(nominal_run['run_directory'])/'manifest.json')
        handle['costs']['nominal_requests'] = 1
        handle['costs']['actual_nominal_evaluator_invocations'] = int('trusted' in nominal_execution)
        handle['costs']['actual_nominal_SPICE_calls'] = nominal.get('new_SPICE_calls')
        save()
        if nominal.get('complete') and nominal.get('operating_point_valid'):
            ugb = nominal.get('metrics',{}).get('tt_ugb_Hz')
            if type(ugb) in (int,float) and math.isfinite(ugb) and ugb>0:
                handle['prediction'] = model.predict(ugb)
        decision = prediction_decision(nominal,handle['prediction'],point['contract'])
        if not allow_screening and decision['action']=='screened_deferred':
            decision.update(action='promote_full',force_full=True,
                reason='screening_disabled_this_point_requires_actual_full')
        handle.update(promotion_decision=decision,status=decision['action'])
        save()
        if decision['action']=='promote_full':
            handle = finish_full(handle_path,deadline=deadline)
        return handle
    except (OSError,ValueError,KeyError,TypeError) as error:
        if handle_path.is_file() and (saved := read(handle_path)).get('full_attempt_started'):
            handle = saved
        handle.update(status='incomplete_unknown',error=type(error).__name__+': '+str(error))
        return handle
    finally:
        handle['costs'].update(point_wall_seconds=time.monotonic()-began,
            host_controller_thread_CPU_seconds=time.thread_time()-host_cpu)
        save()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',type=Path,required=True)
    p.add_argument('--configuration',default='anchor')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path)
    p.add_argument('--policy',choices=['F0','F3'],default='F0')
    p.add_argument('--calibration',type=Path)
    p.add_argument('--allow-screening',action='store_true')
    a = p.parse_args()
    print(json.dumps(evaluate(a.task,a.configuration,a.output,a.source,policy=a.policy,
        calibration_path=a.calibration,allow_screening=a.allow_screening),allow_nan=False),flush=True)
