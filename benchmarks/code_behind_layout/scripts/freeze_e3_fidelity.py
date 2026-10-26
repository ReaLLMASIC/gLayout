"""Freeze the ten-search F3 ablation only after two actual staged controls.

No EDA, model, hidden evaluation or artifact coefficient fitting is performed.
The main source/model sealing release remains mandatory for all hidden work.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import e3_episode as main
from scripts.e3_fidelity_episode import POLICY
from src.domain_runner import inspect_point,source_contents
from src.spice_validation import validate_analysis

TASKS=['draft_E3_five_t_edit02','draft_E3_compact_miller_edit02']
OWN=['scripts/e3_fidelity_episode.py','scripts/freeze_e3_fidelity.py','scripts/e3_fidelity_point.py',
    'scripts/e3_nominal_objective.py','scripts/e2_stage_prepare.py','scripts/e2_cached_evaluator.py',
    'scripts/e2_nominal_bench.py','scripts/e2_spice_process_profile.py','scripts/e2_execution.py',
    'src/promotion_calibration.py']


def audit_controls(summary):
    summary=Path(summary);report=main.read(summary)
    if not report.get('complete') or not report.get('all_transport_controls_passed') or len(report.get('rows',[]))!=2:
        raise ValueError('Two complete actual F3 transport controls are required; no freeze from preparation/software fixtures')
    if {r['task_id'] for r in report['rows']}!={'draft_E3_five_t_edit01','draft_E3_compact_miller_edit01'}:
        raise ValueError('The fixed actual-control identities changed')
    snapshot=summary.parent/'implementation_snapshot'
    expected=['scripts/e3_fidelity_point.py','scripts/e3_nominal_objective.py','scripts/e3_trusted_objective.py',
        'scripts/e2_stage_prepare.py','scripts/e2_cached_evaluator.py','scripts/e2_nominal_bench.py',
        'scripts/e2_spice_process_profile.py','runtime/e3_fidelity_control_20261019/controls.py']
    if any(not (snapshot/name).is_file() for name in expected):
        raise ValueError('Actual control lacks its complete premeasurement implementation snapshot')
    for path in snapshot.rglob('*.py'):
        relative=path.relative_to(snapshot)
        if path.read_bytes()!=(ROOT/relative).read_bytes():
            raise ValueError('Implementation changed since its actual control: '+str(relative))
    if not (snapshot/'scripts/e3_fidelity_point.py').is_file():
        raise ValueError('Actual controls did not retain their premeasurement data-layer source')
    proofs=[]
    for row in report['rows']:
        handle_path=Path(row['point']);handle=main.read(handle_path);out=handle_path.parent
        point=main.read(out/'point_binding.json');task=main.read(out/'task_binding.json')
        if handle['task_id']!=row['task_id'] or handle['configuration_id']!='anchor' or handle['fidelity_policy']!='F3':
            raise ValueError('A transport control used another source/configuration/fidelity')
        nominal=handle['nominal_actual'];full=handle['full_actual']
        if not nominal or not full or handle['costs']['actual_nominal_SPICE_calls']!=1:
            raise ValueError('A control must acquire actual nominal SPICE before actual full')
        nominal_run=Path(nominal['run_directory']);raw=main.read(nominal_run/'evidence/validation.json')
        measurement=raw['nominal']
        if (raw.get('S2') is not False or raw.get('point_evaluation_complete') is not False or
            measurement['new_SPICE_calls']!=1 or measurement['new_Tran_DC_SS_FF_SPICE_calls']!=0 or
            measurement['measurement_function_or_loop_unchanged'] is not True):
            raise ValueError('Nominal transport crossed its declared fidelity')
        for name in ['op','ac']:
            artifact=measurement['analyses'][name]
            # Container absolute paths map to this retained evidence tree.
            path=Path(artifact['data']);log=Path(artifact['log'])
            data_path=nominal_run/'evidence'/path.relative_to('/evidence')
            log_path=nominal_run/'evidence'/log.relative_to('/evidence')
            if not validate_analysis(data_path,log_path,point['contract']['analysis_contracts'][name],artifact['returncode'])['complete']:
                raise ValueError('Actual nominal OP/AC raw coverage is incomplete')
        full_run=Path(full['run_directory']);manifest=main.read(full_run/'manifest.json')
        full_raw=main.read(full_run/'evidence/validation.json')
        expected=source_contents(full_run/'source',manifest['source_files'],binary=True)
        checked=inspect_point({'run_directory':str(full_run)},point,expected,{'parameters':point['parameters']},gold_control_check=False)
        if not checked['S2'] or not checked['analysis_complete']:
            raise ValueError('A staged actual full control is not complete S2')
        origin=Path(handle['physical_actual']['run_directory'])
        origin_record=main.read(origin/'evidence/validation.json')
        if (origin_record['physical_tool_calls']['SPICE']!=0 or
                any(full_raw['physical_tool_calls'][name]!=0 for name in ['DRC','LVS','PEX']) or
                any(raw['physical_tool_calls'][name]!=0 for name in ['DRC','LVS','PEX'])):
            raise ValueError('Fidelity controls used an undeclared expensive acquisition')
        acquisitions=[main.read(run/'manifest.json') for run in [origin,nominal_run,full_run]]
        if any(datetime.fromisoformat(left['trusted']['ended_at_utc'])>
                datetime.fromisoformat(right['candidate']['started_at_utc'])
                for left,right in zip(acquisitions,acquisitions[1:])):
            raise ValueError('The actual nominal acquisition did not precede actual full')
        actual_source=source_contents(origin/'source',task['source_files'],binary=True)
        if actual_source!=source_contents(Path(handle['source']),task['source_files'],binary=True):
            raise ValueError('Actual full control does not bind the complete initial source')
        if any((run/'accepted/candidate.gds').read_bytes()!=(origin/'accepted/candidate.gds').read_bytes()
                for run in [nominal_run,full_run]):
            raise ValueError('Staged controls did not use the exact same GDS')
        original_rc=origin/'evidence'/origin_record['artifacts']['pex']['netlist']
        retained_rc=full_run/'evidence'/full_raw['artifacts']['pex']['netlist']
        if original_rc.read_bytes()!=retained_rc.read_bytes():
            raise ValueError('Full stage changed or simplified the original physical RC')
        if handle['promotion_decision']['action']!='promote_full' or full['DRC_LVS_PEX_repeated_for_electrical'] is not False:
            raise ValueError('The control did not test the real nominal-to-shared-PEX full path')
        corners=full_raw['observation']['corners']
        actual_tt=corners['tt']['metrics']['ugb']['value']
        nominal_tt=measurement['metrics']['tt_ugb_Hz']
        if abs(actual_tt-nominal_tt)/abs(actual_tt)>1e-6:
            raise ValueError('Nominal and unchanged full TT measurements disagree')
        for corner in point['contract']['required_corners']:
            metrics=corners[corner]['metrics'];ugb=metrics['ugb']['value'];area=metrics['area']['value']
            objective=metrics['ugb_per_area']
            if objective['unit']!='Hz/um2' or abs(objective['value']*area-ugb)/abs(ugb)>1e-12:
                raise ValueError('The actual three-corner UGB/area objective was not established')
        proofs.append({'task_id':row['task_id'],'point_record':str(handle_path),'actual_physical_run':str(origin),
            'actual_nominal_run':str(nominal_run),'actual_full_run':str(full_run),'raw_full_checked':checked,
            'actual_costs':handle['costs'],'nominal_and_full_use_same_GDS_and_PEX':True})
    return proofs


def freeze(main_manifest,control_summary,artifact_path,output,check_only=False):
    main_manifest=Path(main_manifest).resolve();base=main.read(main_manifest);main.verify(base)
    if base['status']!='FROZEN_E3' or base.get('formal_dispatch') is not True:
        raise ValueError('F3 needs the separate completed main E3 freeze')
    required={'wall_seconds':14400,'decisions':24,'patches':8,'full_evaluations':8,
        'maximum_context_tokens':16384,'maximum_output_tokens':1024}
    if any(base['budget'].get(key)!=value for key,value in required.items()):
        raise ValueError('The prospective F3 budget must remain matched to the declared main budget')
    if not set(TASKS).issubset(base['task_ids']):raise ValueError('Two declared OTA editing states are absent')
    proofs=audit_controls(control_summary)
    from scripts.e3_fidelity_point import calibration
    artifact,_=calibration(artifact_path,{'parent_lineage':'F3_freeze_control_not_a_fit_source'},False)
    for proof in proofs:
        if main.read(Path(proof['point_record']).parent/'frozen_calibration_copy.json')!=artifact:
            raise ValueError('Freeze artifact differs from the artifact used by the actual controls')
    if not artifact.get('train_rows') or not artifact.get('validation_rows'):
        raise ValueError('Actual train/validation UGB provenance absent')
    plan=[{'task_id':task,'method':'C','trial_id':str(trial),'policy_variant':'GPT',
        'selection_seed':base['selection_seeds'][trial-1],'fidelity_policy':POLICY}
        for task in TASKS for trial in range(1,6)]
    if check_only:return {'status':'READY_TO_FREEZE_F3_METHOD','searches':len(plan),'new_physical_calls':0,'controls':proofs}
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    for path in [Path(control_summary),Path(artifact_path)]:shutil.copyfile(path,output/path.name)
    frozen_artifact=copy.deepcopy(artifact)
    frozen_artifact.update(formal_calibration_freeze=True,formal_frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        original_predeclared_artifact=str(Path(artifact_path).resolve()),coefficients_support_and_residuals_changed=False)
    main.save(output/'promotion_calibration.json',frozen_artifact)
    main.save(output/'actual_control_proofs.json',proofs)
    identity=dict(base['implementation_sha256'])
    for name in OWN:identity[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    manifest={**base,'status':'FROZEN_E3_FIDELITY_METHOD','freeze_id':output.name,
        'fidelity_freeze_id':output.name,'main_freeze_id':base['freeze_id'],
        'main_protocol_manifest':str(main_manifest),'fidelity_policy':POLICY,
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'backend_manifest_path':str(output/'manifest.json'),
        'task_ids':TASKS,'methods':['C'],'trials':5,'policy_variants':['GPT'],'search_plan':plan,
        'promotion_calibration':str(output/'promotion_calibration.json'),
        'promotion_calibration_sha256':hashlib.sha256((output/'promotion_calibration.json').read_bytes()).hexdigest(),
        'fidelity_budget':{'low_fidelity_calls':32,'counting':'Actual PEX acquisition=1; actual TT nominal invocation=1; combined total32, not64',
            'actual_full_evaluator_invocations':8,'wall_and_decision_patch_context_budgets_match_main':True},
        'implementation_sha256':identity,'actual_control_proofs':str(output/'actual_control_proofs.json'),
        'F0_comparison':'Reuse the same main C task/trial searches; do not launch or relabel extra F0 trials',
        'retained_verification':'Anchor and all previously observed passing/failing regressions force actual full; only new untested development points may be screened_deferred',
        'screened_status':'No S2 prediction, no actual failure/counterexample, no observed pass; verified selection uses actual full only',
        'post_freeze_physical_path':'Fresh original F0 source-to-GDS/full physical benchmark for every configuration; no search cache reuse',
        'hidden_evaluation':'Use the main global release only after this method artifact and all ten extra search sources are sealed and source-hash bound',
        'expected_efficiency_limitation':'Existing development OTA nominals are outside calibration support and force full. Zero full savings plus nominal overhead is an admissible negative result.',
        'new_physical_calls_during_freeze':0,'new_model_calls_during_freeze':0}
    main.save(output/'manifest.json',manifest)
    for file in sorted(output.rglob('*'),reverse=True):file.chmod(0o555 if file.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status':manifest['status'],'manifest':str(output/'manifest.json'),'searches':10,'new_physical_calls':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main-manifest',type=Path,required=True);p.add_argument('--actual-controls',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'runtime/protocol_freezes/E3_F3_primary')
    p.add_argument('--check-only',action='store_true');a=p.parse_args()
    print(json.dumps(freeze(a.main_manifest,a.actual_controls,a.calibration,a.output,a.check_only),allow_nan=False),flush=True)
