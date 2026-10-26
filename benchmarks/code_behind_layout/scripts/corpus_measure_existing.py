"""Read actual retained mirror waveforms; emit separate canonical DC metrics."""
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.corpus_metrics import mirror_dc_metrics
from src.spice_validation import validate_analysis
p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args()
r=a.run.resolve();summary={'scope':'development_offline_metrics_no_new_simulation_no_formal_label','source_run':str(r),'cases':{}}
for physical in sorted(r.rglob('physical.json')):
 data=json.loads(physical.read_text())
 if data.get('circuit_id')!='C01':continue
 work=physical.parent;corners={}
 for corner,row in data.get('corners',{}).items():
  valid=validate_analysis(work/corner/'dc.dat',work/corner/'dc.log',{'kind':'dc','columns':3,'start':0,'end':1.8,'points':19,'scale':'linear'},0)
  if not valid['complete']:raise ValueError('Incomplete raw sweep: '+str(work/corner))
  metrics=mirror_dc_metrics(work/corner/'dc.dat')
  op=row['metrics'].get('measured_current_A');metrics['previous_OP_current_A']=op
  metrics['OP_DC_relative_discrepancy']=abs(op/metrics['nominal_current_A']-1) if op is not None else None
  corners[corner]=metrics
 (work/'canonical_mirror_metrics.json').write_text(json.dumps(corners,indent=2)+'\n')
 summary['cases'][str(work.relative_to(r))]=corners
(r/'canonical_mirror_metrics.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'cases':len(summary['cases']),'output':str(r/'canonical_mirror_metrics.json')}))
