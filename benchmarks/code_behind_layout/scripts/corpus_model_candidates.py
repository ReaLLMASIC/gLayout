"""Draw actual T0 development proposals with one identical packet and real seeds.

Run on the research server. The fixed local-only model endpoint cannot read
files or execute tools. Its original response, malformed diffs and usage remain
recorded. Nothing here admits a training row or repairs a model output.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.model_adapter import validate_action


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--seeds',type=int,nargs='+',default=[101,173,241,307,379,443,509,577])
    p.add_argument('--output-name',default='model_pool.json')
    p.add_argument('--source-pack',type=Path)
    p.add_argument('--baseline',type=Path)
    a=p.parse_args();run=a.source_run.resolve()
    run.relative_to(ROOT/'runs')
    pack=(a.source_pack or run/'base_source').resolve()
    source=(pack/'textbook_sharing/layout.py').read_text()
    circuit=json.loads((pack/'circuit_input.json').read_text())
    sizing=json.loads((pack/'sizing_input.json').read_text())
    baseline_path=(a.baseline or run/'baseline/physical.json').resolve()
    baseline=json.loads(baseline_path.read_text())
    if not (baseline.get('full_physical_analysis_complete') or baseline.get('full_tt_ss_ff_flow_complete')):
        raise ValueError('Wait for actual baseline full tt/ss/ff physical analysis before model proposals')
    if len(set(a.seeds))!=len(a.seeds) or not 1<=len(a.seeds)<=16:
        raise ValueError('Use 1..16 distinct actual proposal seeds')
    with urllib.request.urlopen('http://127.0.0.1:8114/health',timeout=60) as response:
        health=json.load(response)
    if health.get('status')!='READY':
        raise RuntimeError('Sampling service is not READY; no candidate request was issued')
    path='textbook_sharing/layout.py'
    packet={'task_id':'development_corpus_'+circuit['circuit_id']+'_original_compiler',
       'goal':'Propose one actual unified source diff that improves the worst-corner nominal mirror current accuracy while preserving the immutable transistor graph, sizes and ports. Use the complete supplied compiler module and frozen APIs. Return propose_patch directly. This is development corpus-yield collection, excluded from formal training/evaluation.',
       'contract':{'scope':'development_only_not_frozen','objective':{'metric':'worst_corner_nominal_current_relative_error','direction':'min'},
          'required_corners':['tt','ss','ff'],'immutable_circuit':circuit,'immutable_sizing':sizing,
          'required_checks':['full-rule DRC','independent per-finger gold LVS','positive all-net RC','complete actual OP/AC/transient/DC'],
          'anchor_testbench':{'reference_current_A':20e-6,'nominal_output_V':.9,'supply_V':1.8},
          'constraints':{'nominal_current_relative_error_max':.1},'near_tie_absolute_tolerance':.0001},
       'allowed_paths':[path],'visible_sources':{path:source},
       'documents':{'frozen_api':'build_mos_group(pdk, group, plan, name) accepts validated sharing plans. named_plans supplies independent, diffusion_only, gate_only, combined (or None when unavailable). assemble(pdk, RowSpec[], ports, name) retains net labels and routing checks; its implementation and all device/PDK/netlist libraries are frozen. Do not replace layout generation with a hardcoded layout or alter validation.',
          'patch_format':'Return a full ordinary unified diff with --- a/textbook_sharing/layout.py and +++ b/textbook_sharing/layout.py, exact @@ old/new line counts, and final newline. No source outside this complete module is editable.'},
       'visible_configurations':['anchor'],'budget':{'decisions':1}}
    observation={'status':'begin','baseline':{key:baseline.get(key) for key in ['area_um2','DRC','LVS','RC']},
                 'baseline_corner_metrics':{corner:row['metrics'] for corner,row in baseline.get('corners',{}).items()}}
    if circuit['circuit_id']=='C05':
        packet['goal']='Propose one source diff improving source-follower worst-corner 3dB bandwidth while preserving the immutable graph, sizing, gain and valid bias. Return propose_patch directly. Development proposal-only collection, excluded from formal training/evaluation.'
        packet['contract']={'scope':'development_only_not_frozen','objective':{'metric':'f3db_Hz','direction':'max'},'required_corners':['tt','ss','ff'],'immutable_circuit':circuit,'immutable_sizing':sizing,'nominal_bench':{'supply_V':1.8,'input_V':1.17,'replica_bias_current_A':20e-6,'load_R_ohm':20000,'load_C_F':1e-12},'constraints':{'positive_small_signal_gain_min':.6,'valid_output_bias_V':[.1,1.7]},'required_checks':['full DRC','independent per-finger gold LVS','positive all-net RC','complete OP/AC/transient/DC'],'no_output_equals_input_requirement':'Source follower has a physical gate-source drop; no C01 .9V clamp or mirror-current metric applies.'}
        from src.corpus_metrics import frequency_3db
        for corner,metrics in observation['baseline_corner_metrics'].items():
            metrics['f3db_Hz']=frequency_3db(baseline_path.parent/corner/'ac.dat')
    elif circuit['circuit_id']=='C08':
        packet['goal']='Propose one source diff improving five-transistor OTA worst-corner unity-gain bandwidth while preserving the immutable graph, sizing, stable closed-loop bias, gain and phase margin. Return propose_patch directly. Development proposal-only collection, excluded from formal training/evaluation.'
        packet['contract']={'scope':'development_only_not_frozen','objective':{'metric':'ugb_Hz','direction':'max'},'required_corners':['tt','ss','ff'],'immutable_circuit':circuit,'immutable_sizing':sizing,'nominal_bench':{'supply_V':1.8,'input_common_mode_V':.9,'NMOS_replica_bias_current_A':40e-6,'load_C_F':1e-12,'feedback':'DC servo for AC; direct follower feedback for transient/DC'},'constraints':{'gain_dB_min':25,'phase_margin_deg_min':60,'nominal_tracking_error_V_max':.015},'required_checks':['full DRC','independent per-finger gold LVS','positive all-net RC','complete OP/AC/transient/DC'],'no_mirror_clamp_requirement':'Output is electrically biased by the OTA feedback, not clamped at .9 V. No mirror-current metric applies.'}
        observation['baseline_corner_metrics']={corner:row['metrics'] for corner,row in baseline['results']['post_rc'].items()}
        observation['actual_baseline_evidence']=str(baseline_path)
    elif circuit['circuit_id']!='C01':raise ValueError('Only actual C01/C05/C08 benches are implemented')
    request={'task_packet':packet,'visible_history':[{'observation':observation}]}
    output=run/a.output_name
    if output.exists():raise ValueError('Preserve previous candidate pool; choose a fresh output name')
    requests=run/(output.stem+'_requests');requests.mkdir()
    pool={'scope':'development_T0_sampled_candidates_not_training','circuit_id':circuit['circuit_id'],'editable_source':source,
          'identical_request':request,'candidates':[],'formal_training_rows':0}
    for seed in a.seeds:
        work=requests/('seed_'+str(seed));work.mkdir()
        body={'variant':'T0','mode':'development_corpus','sampling':{'temperature':.7,'top_p':.95,'seed':seed},'request':request}
        (work/'request.json').write_text(json.dumps(body,indent=2)+'\n')
        call=urllib.request.Request('http://127.0.0.1:8114/decision',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        begin=time.monotonic();started=datetime.now(timezone.utc).isoformat()
        try:
            with urllib.request.urlopen(call,timeout=600) as response:
                raw=response.read().decode();status=response.status
        except urllib.error.HTTPError as exc:
            raw=exc.read().decode();status=exc.code
        except Exception as exc:
            raw=json.dumps({'error':type(exc).__name__+': '+str(exc)});status=None
        (work/'response.json').write_text(raw+'\n')
        response=json.loads(raw);action=response.get('action');error=response.get('error')
        if action:
            try:validate_action(action,packet)
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
        patch=action.get('patch','') if action and action.get('action')=='propose_patch' and error is None else ''
        record={'candidate_id':'T0_seed_'+str(seed),'proposal_source':'actual_T0_sampled_model','patch':patch,
                'seed':seed,'sampling':body['sampling'],'response_status':status,'action':action,'model_error':error,
                'inference_id':response.get('inference_id'),'usage':response.get('usage'),'model':response.get('model'),
                'started_at_utc':started,'request_wall_seconds':time.monotonic()-begin,'response_path':str(work/'response.json')}
        pool['candidates'].append(record);output.write_text(json.dumps(pool,indent=2)+'\n')
        print(json.dumps({key:record[key] for key in ['candidate_id','response_status','model_error','request_wall_seconds','usage']}),flush=True)


if __name__=='__main__':main()
