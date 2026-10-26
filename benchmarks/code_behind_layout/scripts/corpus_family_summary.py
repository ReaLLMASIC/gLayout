"""Summarize actual nine-point development baselines without relabeling them."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path);a=p.parse_args()
batch=a.batch or max((ROOT/'runs/development/corpus_family_yield').glob('*/batch.json'),key=lambda path:path.stat().st_mtime)
state=json.loads(batch.read_text())
if not state['baseline_only'] or len(state['jobs'])!=8:raise ValueError('Eight new baseline points are not all complete yet')
anchor=ROOT/'runs/phase0/phase0_20261018T234700264280Z_corpus_yield_pilot/baseline'
original=json.loads((anchor/'physical.json').read_text());canonical=json.loads((anchor/'canonical_mirror_metrics.json').read_text())
summary={'scope':'development_nine_geometry_baselines_not_formal_or_training','batch':str(batch),'configurations':{},'formal_training_rows':0,'specification_freeze':False}
def record(point,root,physical,corners):
 if not physical.get('full_physical_analysis_complete'):raise ValueError('Physical baseline incomplete: '+point)
 if not all(physical.get(key,{}).get('is_clean') for key in ['DRC','LVS']) or not physical['RC']['has_real_RC']:raise ValueError('Physical hard gate failed: '+point)
 values=list(corners.values());lows=[m['compliance_5pct_lower_V'] for m in values];highs=[m['compliance_5pct_upper_V'] for m in values]
 return {'configuration_id':point,'raw_run':str(root),'physical_and_all_twelve_analyses_complete':True,'area_um2':physical['area_um2'],'R':physical['RC']['counts']['R'],'C':physical['RC']['counts']['C'],'corners':corners,'worst_nominal_current_relative_error':max(m['nominal_current_relative_error'] for m in values),'minimum_output_resistance_ohm':min(m['output_resistance_ohm'] for m in values),'common_sampled_5pct_compliance_V':[max(lows),min(highs)] if None not in lows+highs else None}
summary['configurations']['anchor']=record('anchor',anchor,original,canonical)
for job in state['jobs']:
 root=Path(job['output']);physical=json.loads((root/'baseline/physical.json').read_text())
 corners={corner:row['metrics'] for corner,row in physical['corners'].items()}
 summary['configurations'][job['configuration_id']]=record(job['configuration_id'],root,physical,corners)
out=ROOT/'results/derived/c01_family_baseline_development.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({name:{key:row[key] for key in ['area_um2','worst_nominal_current_relative_error','minimum_output_resistance_ohm','common_sampled_5pct_compliance_V']} for name,row in summary['configurations'].items()},indent=2))
