"""Real Magic calibration of contract-named target selection in multi-top GDS."""
import json,os
from pathlib import Path
import sys
import gdstk
sys.path.insert(0,'/work')
from src.physical_drc import check_gds

out=Path.cwd();input_dir=Path(os.environ['PROBE_INPUT'])
source=input_dir/'validation_mirror.gds';rows=[]
for mode in ('good_target_bad_unrelated','bad_target_unrelated','bad_child_far_unrelated'):
    library=gdstk.read_gds(source)
    target=next(cell for cell in library.cells if cell.name=='validation_mirror')
    unrelated=library.new_cell('unrelated')
    unrelated.add(gdstk.rectangle((10000,10000),(10000.01,10000.01),layer=67,datatype=20))
    if mode=='bad_target_unrelated':
        target.add(gdstk.rectangle((2000,2000),(2000.01,2000.01),layer=67,datatype=20))
    if mode=='bad_child_far_unrelated':
        child=library.new_cell('target_child')
        child.add(gdstk.rectangle((0,0),(.01,.01),layer=67,datatype=20))
        target.add(gdstk.Reference(child,(2000,2000)))
    path=out/(mode+'.gds');library.write_gds(path)
    row=check_gds(path,out/mode,top_name='validation_mirror')
    row.update(case=mode,original_input=str(source),original_input_unchanged=True)
    rows.append(row)
    assert row['completed'] and row['actual_top']=='validation_mirror'
    assert row['is_clean']==(mode=='good_target_bad_unrelated')
    assert row['check_box_um'][2]<3000 and row['check_box_um'][3]<3000
    if mode=='bad_child_far_unrelated':assert row['check_box_um'][2]>2000
try:
    check_gds(out/'good_target_bad_unrelated.gds',out/'missing_named_target',top_name='missing_target')
except ValueError as exc:missing={'rejected':True,'message':str(exc)}
else:raise AssertionError('Missing named top was accepted')
record={'scope':'development_named_actual_top_full_DRC_calibration','formal_trials':0,'training_examples':0,
    'cases':rows,'missing_named_target':missing,'passed':True}
(out/'named_top.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
