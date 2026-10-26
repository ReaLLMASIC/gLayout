"""Read true accepted GDS geometry for the bounded mirror witness; no simulation."""
import json,os
from pathlib import Path
import gdstk
out=Path.cwd();witness=Path(os.environ['PROBE_INPUT'])
record=json.loads((witness/'witness.json').read_text());host=Path('/srv/code-behind-layout')
rows={}
for role,key in [('baseline','baseline_run'),('candidate','run_directory')]:
    directory=Path('/work')/Path(record[key]).relative_to(host)
    path=directory/'accepted/candidate.gds';library=gdstk.read_gds(path);top,=library.top_level();scale=library.unit/1e-6
    bbox=top.bounding_box();area=(bbox[1][0]-bbox[0][0])*(bbox[1][1]-bbox[0][1])*scale**2
    rows[role]={'accepted_gds':str(path),'actual_top':top.name,'bbox_um':[[float(v*scale) for v in point] for point in bbox],
        'bbox_area_um2':float(area),'per_layer_polygon_area_sum_um2':float(sum(p.area() for p in top.get_polygons())*scale**2)}
result={'phase':'development_component_engineering_witness_geometry','formal_trials':0,'training_examples':0,
    'witness':str(witness),'geometry':rows,
    'bbox_area_relative_reduction':1-rows['candidate']['bbox_area_um2']/rows['baseline']['bbox_area_um2'],
    'current_error_objectives':record['objectives'],'family_improvement_established':False}
(out/'geometry.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
