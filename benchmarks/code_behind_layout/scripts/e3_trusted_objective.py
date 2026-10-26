"""E3 objective adapter around the unchanged frozen E1 physical evaluator."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import gdstk

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gds',required=True)
p.add_argument('--output',required=True);p.add_argument('--fidelity',required=True);args=p.parse_args()
out=Path(args.output)
process=subprocess.run([sys.executable,'/trusted/original_physical_evaluate.py',*sys.argv[1:]])
path=out/'validation.json'
if not path.is_file():raise SystemExit(process.returncode or 1)
result=json.loads(path.read_text());meta=json.loads(Path('/trusted/meta.json').read_text())
library=gdstk.read_gds(args.gds);matches=[c for c in library.cells if c.name==meta['top_cell']]
area=None
if len(matches)==1 and (box:=matches[0].bounding_box()) is not None:
    area=float((box[1][0]-box[0][0])*(box[1][1]-box[0][1])*(library.unit/1e-6)**2)
if area is not None and math.isfinite(area) and area>0:
    for row in result['observation']['corners'].values():
        metrics=row['metrics'];metrics['area']={'value':area,'unit':'um2'}
        if result['contract']['objective']['metric']=='ugb_per_area':
            ugb=metrics.get('ugb',{})
            if ugb.get('unit')=='Hz' and type(ugb.get('value')) in (int,float) and math.isfinite(ugb['value']) and ugb['value']>0:
                metrics['ugb_per_area']={'value':ugb['value']/area,'unit':'Hz/um2'}
objective=result['contract']['objective']
if result['assessment']['S2']:
    for corner in result['contract']['required_corners']:
        metric=result['observation']['corners'][corner]['metrics'].get(objective['metric'],{})
        if metric.get('unit')!=objective['unit'] or type(metric.get('value')) not in (int,float) or not math.isfinite(metric['value']):
            raise RuntimeError('Physical S2 passed but the declared E3 objective was not established')
result.update(base_evaluator_scope=result['scope'],scope='E3_original_physical_checks_with_actual_GDS_objective',
    derived_objective_definition=objective,actual_bbox_area_um2=area,
    original_bench_and_electrical_specifications_changed=False)
path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(process.returncode)
