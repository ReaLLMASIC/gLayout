"""Trusted C05/C08 power-constrained area evaluator; candidate Python is absent."""
import argparse,json
from pathlib import Path
import sys
from types import SimpleNamespace
import gdstk
sys.path.insert(0,'/trusted')
from physical import evaluate_gds
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument('--gds');p.add_argument('--output');p.add_argument('--fidelity');a=p.parse_args()
out=Path(a.output);configuration=json.loads(Path('/configuration.json').read_text());identifier=configuration['configuration_id']
contract=json.loads((Path('/trusted/contracts')/(identifier+'.json')).read_text())
if contract['configuration_id']!=identifier:raise ValueError('Configuration and independent contract differ')
cid=configuration['circuit']['circuit_id']
if cid not in ['C05','C08']:raise ValueError('This frozen evaluator supports only its declared circuits')
circuit=SimpleNamespace(circuit_id=cid,ports=configuration['circuit']['ports'])
record=evaluate_gds(out,circuit,configuration['sizing'],configuration['top_cell'],Path(a.gds),Path('/trusted/references')/(identifier+'.spice'),Path('/trusted/run_pex.sh'))
library=gdstk.read_gds(a.gds);top,=library.top_level();box=top.bounding_box();area=(box[1][0]-box[0][0])*(box[1][1]-box[0][1])*(library.unit/1e-6)**2
(out/'drc_full/metadata.json').write_text(json.dumps(record['DRC'],indent=2)+'\n')
lvs=record.get('LVS',{}).get('is_clean',False);real=record.get('RC',{}).get('has_real_RC',False)
observation={key:contract[key] for key in ['task_id','configuration_id','reference_id']}
observation.update(executed=True,gds_emitted=True,checks={'drc':record['DRC']['is_clean'],'lvs':lvs,'devices':lvs,'ports':lvs,'intent':lvs},pex={'executed':record.get('pex_returncode')==0,'kind':'physical_rc','resistance_extracted':real,'capacitance_extracted':real},corners={})
artifacts={'drc':{'report':'drc_full/direct_drc.rpt','metadata':'drc_full/metadata.json'},'lvs':{'report':'netgen_lvs.rpt'},'spice':{}}
if real:artifacts['pex']={'netlist':configuration['top_cell']+'_pex.spice','top_cell':configuration['top_cell']+'_rc','ports':circuit.ports}
units={'gain_10Hz_real':'1','f3db_Hz':'Hz','gain_10Hz_dB':'dB','ugb_Hz':'Hz','phase_margin_deg':'deg','settled_tracking_error_V':'V','DUT_supply_power_W':'W'}
for corner,row in record.get('corners',{}).items():
    m=row['metrics'];complete=row['complete'];metrics={name:{'value':m[name],'unit':unit} for name,unit in units.items() if name in m};metrics['area']={'value':area,'unit':'um2'}
    valid=complete and 0<m.get('bias_V',0)<1.8 and (.1<m.get('output_bias_V',0)<1.7 if cid=='C05' else abs(m.get('output_bias_V',0)-.9)<=.015)
    observation['corners'][corner]={'converged':complete,'operating_point_valid':valid,'metrics':metrics}
    artifacts['spice'][corner]={'analyses':{name:{'data':corner+'/'+name+'.dat','log':corner+'/'+('ac' if name=='op' else name)+'.log','returncode':values['returncode']} for name,values in row['analyses'].items()}}
assessment=assess(contract,observation);complete=record.get('full_physical_analysis_complete',False)
validation={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,'analysis_complete':complete,'execution_integrity':'valid' if complete else 'incomplete','failure_class':None if assessment['S2'] else 'candidate' if complete else 'unknown','point_evaluation_complete':complete,'scope':'independent_trusted_point_evaluation_host_owns_phase_and_domain'}
(out/'validation.json').write_text(json.dumps(validation,indent=2)+'\n');print(json.dumps(validation,indent=2),flush=True)
raise SystemExit(0 if assessment['S2'] and complete else 2)
