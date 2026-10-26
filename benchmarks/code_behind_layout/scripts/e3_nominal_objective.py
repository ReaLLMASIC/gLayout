"""Add only actual GDS area to the retained TT nominal measurement.

No other electrical analysis runs here. The original E2 nominal consumer keeps
its exact deck/solver/timeout; this result never establishes S2.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import gdstk

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--gds', required=True)
p.add_argument('--output', required=True)
p.add_argument('--fidelity', required=True)
a = p.parse_args()
process = subprocess.run([sys.executable, '/trusted/original_nominal_evaluate.py', *sys.argv[1:]])
path = Path(a.output)/'validation.json'
if not path.is_file():
    raise SystemExit(process.returncode or 1)
record = json.loads(path.read_text())
meta = json.loads(Path('/trusted/meta.json').read_text())
library = gdstk.read_gds(a.gds)
matches = [cell for cell in library.cells if cell.name == meta['top_cell']]
if len(matches) != 1 or (box := matches[0].bounding_box()) is None:
    raise ValueError('Nominal objective needs its exact named GDS target')
area = float((box[1][0]-box[0][0])*(box[1][1]-box[0][1])*(library.unit/1e-6)**2)
if not math.isfinite(area) or area <= 0:
    raise ValueError('Actual GDS bbox area is invalid')
record.update(scope='E3_actual_nominal_TT_OP_AC_plus_actual_GDS_area_NOT_S2',
    actual_bbox_area_um2=area, original_nominal_function_and_deck_changed=False)
if record.get('S2') is not False or record.get('point_evaluation_complete') is not False:
    raise ValueError('A nominal observation cannot establish full S2')
path.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')
print(json.dumps(record), flush=True)
raise SystemExit(process.returncode)
