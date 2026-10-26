#!/usr/bin/env python3
"""One bounded real anchor per target through the exact E1 runner; no model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import argparse,difflib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.e1_matched_runner import backend

TASKS=['draft_E1_mirror_s01','draft_E1_cascode_mirror_s02','draft_E1_source_follower_s01','draft_E1_stacked_switch_s02',
    'draft_E1_common_source_stage_s01','draft_E1_resistive_diff_s02','draft_E1_five_t_s01','draft_E1_compact_miller_s02']


def run(task):
    info=backend({'op':'start','manifest':'configs/development/e1_freeze_manifest_draft.json','task_id':task,'method':'G2','trial_id':'mechanical',
        'driver_role':'engineering_mechanical_control','formal':False});directory=info['episode_directory'];packet=info['packet']
    target=task[len('draft_E1_'):].rsplit('_s',1)[0]
    source='''import argparse,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
configuration=json.loads(Path(a.configuration).read_text())
'''
    if target in ('mirror','five_t','compact_miller'):
        source+='from component_build import build\nbuild(configuration["parameters"],Path("/tmp/reused.gds"))\nshutil.copyfile("/tmp/reused.gds",a.output)\n'
    else:source+='from src.generators.'+target+' import build\ngenerated=build(Path("/tmp/reuse"),configuration["parameters"])\nshutil.copyfile(generated,a.output)\n'
    patch=''.join(difflib.unified_diff(packet['visible_sources']['generator.py'].splitlines(True),source.splitlines(True),fromfile='a/generator.py',tofile='b/generator.py'))
    base={'path':'','patch':'','configuration_ids':[],'fidelity':'','summary':'Transparent engineering integration control, no model inference'}
    backend({'op':'action','episode_directory':directory,'action':{**base,'action':'propose_patch','patch':patch}})
    result=backend({'op':'action','episode_directory':directory,'action':{**base,'action':'request_evaluation','configuration_ids':['anchor'],'fidelity':'pex_spice'}})
    backend({'op':'seal','episode_directory':directory,'status':'ENGINEERING_MECHANICAL_CONTROL_COMPLETE'})
    report=backend({'op':'post_freeze','episode_directory':directory,'anchor_only':True})
    print(json.dumps({'task_id':task,'actual_anchor':result,'report':report}),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tasks',nargs='+',choices=TASKS,default=TASKS[:1]);p.add_argument('--workers',type=int,choices=[1,2],default=1);a=p.parse_args()
    output=ROOT/'runs/development/E1_mechanical_summary'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        records=list(pool.map(run,a.tasks))
    (output/'summary.json').write_text(json.dumps({'scope':'transparent_engineering_E1_runner_integration_controls','formal_trials':0,'model_calls':0,'episodes':records},indent=2)+'\n')
    print(json.dumps({'summary':str(output/'summary.json')}),flush=True)
