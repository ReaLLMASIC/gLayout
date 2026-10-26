"""Draft trusted nine-point C01 adapter; no candidate source is imported here."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import gdstk
sys.path.insert(0,'/trusted')
from physical import evaluate_gds
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument('--gds');p.add_argument('--output');p.add_argument('--fidelity');a=p.parse_args()
out=Path(a.output);configuration=json.loads(Path('/configuration.json').read_text())
id=configuration['configuration_id'];contract=json.loads((Path('/trusted/contracts')/(id+'.json')).read_text())
if contract['configuration_id']!=id:raise ValueError('Immutable configuration/contract differs')
circuit=SimpleNamespace(circuit_id=configuration['circuit']['circuit_id'],ports=configuration['circuit']['ports'])
reference=Path('/trusted/references')/(id+'.spice')
record=evaluate_gds(out,circuit,configuration['sizing'],configuration['top_cell'],Path(a.gds),reference,Path('/trusted/run_pex.sh'))
# GDS coordinates are in library units, not intrinsically in micrometres.
library=gdstk.read_gds(a.gds);top,=library.top_level();box=top.bounding_box()
area=(box[1][0]-box[0][0])*(box[1][1]-box[0][1])*(library.unit/1e-6)**2
(out/'drc_full/metadata.json').write_text(json.dumps(record['DRC'],indent=2)+'\n')
observation={key:contract[key] for key in ['task_id','configuration_id','reference_id']}
lvs=record.get('LVS',{}).get('is_clean',False);real=record.get('RC',{}).get('has_real_RC',False)
observation.update(executed=True,gds_emitted=True,checks={'drc':record['DRC']['is_clean'],'lvs':lvs,'devices':lvs,'ports':lvs,'intent':lvs},pex={'executed':record.get('pex_returncode')==0,'kind':'physical_rc','resistance_extracted':real,'capacitance_extracted':real},corners={})
artifacts={'drc':{'report':'drc_full/direct_drc.rpt','metadata':'drc_full/metadata.json'},'lvs':{'report':'netgen_lvs.rpt'},'spice':{}}
if real:artifacts['pex']={'netlist':configuration['top_cell']+'_pex.spice','top_cell':configuration['top_cell']+'_rc','ports':circuit.ports}
for corner,row in record.get('corners',{}).items():
 m=row['metrics'];complete=row['complete']
 metrics={}
 if complete:
  errors=[point['relative_error'] for point in m['dc_sweep_relative_errors'] if .7-1e-8<=point['voltage_V']<=1.0+1e-8]
  if len(errors)!=4:raise ValueError('Declared compliance subgrid is incomplete')
  metrics={'nominal_current_relative_error':{'value':m['nominal_current_relative_error'],'unit':'1'},'output_resistance':{'value':m['output_resistance_ohm'],'unit':'ohm'},'compliance_band_max_relative_error':{'value':max(errors),'unit':'1'},'area':{'value':area,'unit':'um2'}}
 observation['corners'][corner]={'converged':complete,'operating_point_valid':complete and abs(m['output_bias_V']-.9)<1e-7 and 0<m['bias_V']<1.8 and m['nominal_current_A']>0,'metrics':metrics}
 artifacts['spice'][corner]={'analyses':{name:{'data':corner+'/'+name+'.dat','log':corner+'/'+('ac' if name=='op' else name)+'.log','returncode':values['returncode']} for name,values in row['analyses'].items()}}
assessment=assess(contract,observation);complete=record.get('full_physical_analysis_complete',False)
validation={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,'analysis_complete':complete,'execution_integrity':'valid' if complete else 'incomplete','failure_class':None if assessment['S2'] else 'candidate' if complete else 'unknown','point_evaluation_complete':complete,'scope':'independent_trusted_point_evaluation_host_owns_phase_and_domain'}
(out/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
print(json.dumps(validation,indent=2),flush=True)
raise SystemExit(0 if assessment['S2'] and complete else 2)
