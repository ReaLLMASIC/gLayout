"""Assess train/validation selector evidence and save a transparent rule.

No evaluation labels, failure probability fit, source-risk fit or trained
ensemble is produced. The AC comparison checks whether the already declared
positive-ratio bootstrap ensemble changes nominal-versus-worst UGB ordering.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.e3_risk_model import VERSION, DISABLED, STATUS_PREDICATES, VisibleMarginDistanceRule, normalized_margin
from src.e3_episode_state import EpisodeState


def ranking(rows, offsets):
    actual = [r['worst_ugb_Hz'] for r in rows]
    predicted = [r['nominal_ugb_Hz'] for r in rows]
    pairs = [(i,j) for i in range(len(rows)) for j in range(i)]
    informative = [(i,j) for i,j in pairs if actual[i] != actual[j]]
    def reversals(values):
        return sum((values[i]-values[j])*(actual[i]-actual[j]) < 0 for i,j in informative)
    ensemble = [sum(value*math.exp(offset) for offset in offsets)/len(offsets) for value in predicted]
    return {'measurements': len(rows), 'informative_pairs': len(informative),
        'nominal_order_reversals': reversals(predicted),
        'bootstrap_positive_ratio_ensemble_order_reversals': reversals(ensemble),
        'ensemble_ordering_differs_from_nominal': any((predicted[i]-predicted[j])*(ensemble[i]-ensemble[j]) < 0 for i,j in pairs),
        'comparison_target': 'continuous actual worst-corner UGB ordering, not S2 or failure probability',
        'configuration_failure_metrics': None}


def replay_margin_rule(controls):
    """Nine real train control points; no validation or failure-model claim."""
    if len(controls) != 9:
        return {'status':'UNAVAILABLE','reason':'Exactly nine actual baseline control measurements required'}
    points=[]
    for ident,row in controls.items():
        params={device+'_'+key:value for device,sizes in row['parameters']['sizing'].items()
            for key,value in sizes.items() if type(value) in (int,float)}
        points.append({'configuration_id':ident,'role':'anchor' if ident.endswith('_anchor') else 'development','parameters':params})
    curves={};events={};weights={'failure_probability':0,'uncertainty':1,'changed_call_coverage':0,'low_margin':1}
    expected_worst=min(row['margin'] for row in controls.values())
    for method in ('B','C'):
        state=EpisodeState(method,points,41,'min',weights if method=='C' else None)
        state.value['contract']=next(iter(controls.values()))['raw']['contract']
        rule=VisibleMarginDistanceRule({'version':VERSION,'status':'TRANSPARENT_HEURISTIC_NOT_CALIBRATED_FAILURE_MODEL',
            'evaluation_outcomes_used':False,'disabled_channels':list(DISABLED),
            'continuous_margin_excluded_status_predicates':list(STATUS_PREDICATES)})
        measured=[];curve=[]
        while len(measured)<9:
            predictions=rule.predict({},state.value,{p['configuration_id']:p['parameters'] for p in points}) if method=='C' else None
            name=state.next_configuration(predictions)
            if name is None:break
            row=controls[name];measured.append(name)
            raw=row['raw'];definition=raw['contract']['objective']
            if raw['assessment']['S2'] is not True:
                raise ValueError('The train control replay requires actual completed baseline S2')
            metrics=[raw['observation']['corners'][corner]['metrics'][definition['metric']]
                for corner in raw['contract']['required_corners']]
            if any(metric['unit']!=definition['unit'] for metric in metrics):
                raise ValueError('Train control objective units differ')
            values=[metric['value'] for metric in metrics]
            objective=max(values) if definition['direction']=='min' else min(values)
            state.observe({'configuration_id':name,'checked':{'execution_integrity':'valid','S1':True,'S2':True},
                'objective':objective,'physical_feedback':raw['observation']})
            actual_min=min(controls[ident]['margin'] for ident in measured)
            curve.append({'actual_points_acquired':len(measured),'minimum_observed_spec_margin':actual_min,
                'gap_to_actual_nine_point_minimum':actual_min-expected_worst})
        curves[method]=curve;events[method]=measured
    return {'status':'ACTUAL_TRAIN_CONTROL_REPLAY_NOT_VALIDATION_OR_FORMAL_EXPERIMENT',
        'configuration_points':9,'independent_programs':1,'new_physical_calls':0,
        'C_weights':weights,'weight_choice':'Fixed illustrative equal margin/coverage weights; not validation selected',
        'selection_events':events,'curves':curves,'oracle_use':'Only for offline reporting; predictor gets acquired observations only',
        'failure_probability_validation':False,'ensemble_advantage':'UNDETERMINED; no configuration-specific failure validation'}


def build(signal_path, calibration_path, archives):
    signal = json.loads(signal_path.read_text())
    calibration = json.loads(calibration_path.read_text())
    if signal.get('scope') != 'train_only_selector_signal_inventory_not_formal_experiment' or signal.get('parent_lineage') != 'textbook_universal_compiler_cropped':
        raise ValueError('Only the declared current-gate train inventory is allowed')
    if calibration.get('evaluation_lineages_or_outcomes_used') is not False:
        raise ValueError('Evaluation measurements cannot select the risk rule')
    for split in ('train', 'validation'):
        for row in calibration[split+'_rows']:
            if row['split'] != split or row['parent_lineage'] not in calibration[split+'_source_lineages'] or row['actual_three_corner_AC_complete'] is not True:
                raise ValueError('AC evidence split/lineage/completeness differs')
            if not all(type(row[key]) in (int,float) and math.isfinite(row[key]) and row[key] > 0 for key in ('nominal_ugb_Hz','worst_ugb_Hz')):
                raise ValueError('AC ranking requires actual positive finite UGB')
    candidate_stats = []
    for row in signal['records']:
        if len(row['configuration_ids']) != 9 or len(row['S2']) != 9:
            raise ValueError('Every train vector must preserve its full nine-point domain')
        candidate_stats.append({'candidate_id': row['candidate_id'], 'points':9,
            'passing':sum(row['S2']), 'configuration_specific_failure':len(set(row['S2'])) > 1})
    margins = []; controls = {}
    seen_runs = set()
    allowed_runs = {run for row in signal['records'] for run in row['tool_log_ids']}
    for archive in archives:
        with tarfile.open(archive) as stream:
            members={m.name:m for m in stream.getmembers() if m.isfile()}
            for member in stream:
                if not member.isfile() or not member.name.endswith('/evidence/validation.json'):
                    continue
                run = Path(member.name).parts[-3]
                if run not in allowed_runs or run in seen_runs:
                    continue
                raw = json.load(stream.extractfile(member))
                if raw['contract']['task_id'] != 'train_collection_c05':
                    raise ValueError('Unexpected source in C05 train margin inventory')
                margin = normalized_margin(raw['contract'],raw['observation'])
                if margin is not None:
                    seen_runs.add(run)
                    margins.append({'run_id':run,'configuration_id':raw['contract']['configuration_id'],
                        'worst_signed_relative_spec_margin':margin,'archive':str(archive),
                        'member':member.name,'interpretation':'Actual complete electrical metrics only; no new physical run or negative label'})
                    folder=str(Path(member.name).parent.parent)
                    manifest=json.load(stream.extractfile(members[folder+'/manifest.json']))
                    if 'trusted_evaluator_control' in manifest.get('context',{}).get('evidence_roles',[]):
                        configuration=json.load(stream.extractfile(members[folder+'/configuration.json']))
                        controls[raw['contract']['configuration_id']]={'raw':raw,'margin':margin,'parameters':configuration}
    return {'version':VERSION,'status':'TRANSPARENT_HEURISTIC_NOT_CALIBRATED_FAILURE_MODEL',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'evaluation_outcomes_used':False,'input_sources':{'train_inventory':str(signal_path),'AC_train_validation':str(calibration_path),'train_archives':[str(p) for p in archives]},
        'disabled_channels':list(DISABLED),
        'continuous_margin_excluded_status_predicates':list(STATUS_PREDICATES),
        'status_predicate_rule':'Require actual unit1/min1/max1/value1 in every required corner; retain this feasibility gate in S2. Exclude only the named predicate from continuous margin. No remaining continuous spec means unavailable low_margin=0.',
        'channel_definitions':{'failure_probability':'UNAVAILABLE; numeric zero placeholder; zero weight required; not an estimated probability',
            'changed_call_coverage':'UNAVAILABLE; no runtime call coverage; numeric zero placeholder; zero weight required',
            'uncertainty':'Deterministic normalized RMS parameter distance to nearest current-revision measured configuration; one before any measurement; not calibrated uncertainty',
            'low_margin':'Nearest visible configuration prior of 1/(1+max(0,worst signed relative continuous frozen-spec margin)); only complete actual metrics; original_development_predicate is a required feasibility gate excluded from this distance; zero if continuous contract/metrics unavailable; not a probability'},
        'selection_weight_status':'NOT_VALIDATION_SELECTED; gateway must predeclare transparent-rule weights; unavailable channels must stay zero',
        'train_evidence':{'initial_contexts':signal['distinct_initial_states'],'candidate_vectors':candidate_stats,
            'configuration_specific_failure_vectors':sum(r['configuration_specific_failure'] for r in candidate_stats),
            'actual_margin_records':margins},
        'AC_rule_comparison':{split:ranking(calibration[split+'_rows'],calibration['ensemble_log_ratio_offsets']) for split in ('train','validation')},
        'actual_train_margin_replay':replay_margin_rule(controls),
        'failure_model_fit':False,'ensemble_selector_fit':False,'formal_C_ready':False,
        'limitations':['Whole-program failures provide no identifiable configuration-risk ranking.',
            'Independent validation AC rows establish no full S2 or failure outcomes.',
            'Train follower margins and validation OTA UGB have different contracts and cannot calibrate a shared failure probability.',
            'A positive global UGB ratio ensemble preserves nominal ordering and cannot establish selector improvement.',
            'Nearest-neighbor past margins are disclosed heuristics and become stale after source edits; all required physical rechecks remain necessary.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-inventory',type=Path,default=ROOT/'results/derived/risk_training_signal_inventory_c05_20261019T0343Z.json')
    parser.add_argument('--ac-calibration',type=Path,default=ROOT/'results/derived/promotion_calibration_20261019T0353Z_nine_validation.json')
    parser.add_argument('--train-archive',type=Path,action='append')
    parser.add_argument('--output',type=Path,default=ROOT/'results/derived/e3_visible_risk_rule_draft.json')
    args=parser.parse_args()
    archives=args.train_archive or [ROOT/'results/raw/c05_minimal_first_state_partial_20261019T0326Z.tar.gz']
    result=build(args.train_inventory,args.ac_calibration,archives)
    if args.output.exists():raise FileExistsError('Preserve previous risk artifacts; choose a new output path')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(args.output),'formal_C_ready':False,'margins':len(result['train_evidence']['actual_margin_records']),'AC_rule_comparison':result['AC_rule_comparison']}))


if __name__ == '__main__':main()
