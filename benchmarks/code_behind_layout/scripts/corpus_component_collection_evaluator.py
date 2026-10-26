"""Independent trusted C07/TG evaluator; only accepted GDS crosses the boundary."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,'/trusted')
from component_physical import evaluate
from src.measurement import assess

parser=argparse.ArgumentParser();parser.add_argument('--gds');parser.add_argument('--output');parser.add_argument('--fidelity');args=parser.parse_args()
out=Path(args.output);configuration=json.loads(Path('/configuration.json').read_text());identifier=configuration['configuration_id']
contract=json.loads((Path('/trusted/contracts')/(identifier+'.json')).read_text())
if contract['configuration_id']!=identifier:raise ValueError('Independent contract configuration differs')
cid=configuration['circuit']['circuit_id']
if cid not in ['C02','C07','TRAIN_TG01']:raise ValueError('Undeclared component graph')
circuit=SimpleNamespace(circuit_id=cid,ports=configuration['circuit']['ports'])
record=evaluate(out,circuit,configuration['sizing'],configuration['top_cell'],Path(args.gds),
    Path('/trusted/references')/(identifier+'.spice'),contract,
    solver=contract['numerical_controls']['integration_method'],
    independent_transient_inputs=contract['numerical_controls']['independent_transient_inputs'],pex_script=Path('/trusted/run_pex.sh'))
(out/'drc_full/metadata.json').write_text(json.dumps(record['DRC'],indent=2)+'\n')
lvs=record.get('LVS',{}).get('is_clean',False);intent=record.get('DeviceIntent',{}).get('is_clean',False);real=record.get('RC',{}).get('has_real_RC',False)
observation={key:contract[key] for key in ['task_id','configuration_id','reference_id']}
observation.update(executed=True,gds_emitted=True,checks={'drc':record['DRC']['is_clean'],'lvs':lvs,'devices':intent,'ports':intent,'intent':intent},
    pex={'executed':record.get('pex_returncode')==0,'kind':'physical_rc','resistance_extracted':real,'capacitance_extracted':real},corners={})
artifacts={'drc':{'report':'drc_full/direct_drc.rpt','metadata':'drc_full/metadata.json'},'lvs':{'report':'netgen_lvs.rpt'},'spice':{}}
if real:artifacts['pex']={'netlist':configuration['top_cell']+'_pex.spice','top_cell':configuration['top_cell']+'_rc','ports':circuit.ports}
units={'differential_transconductance_S':'S','systematic_input_offset_V':'V','zero_input_differential_current_A':'A',
       'settled_current_error_vs_DC_A':'A','differential_current_span_A':'A','main_supply_power_W':'W',
       'on_gain_10Hz':'1','on_f3db_Hz':'Hz','max_on_resistance_ohm':'ohm','max_on_DC_tracking_error_V':'V',
       'max_off_leakage_A':'A','settled_signal_tracking_error_V':'V','signal_source_power_W':'W','main_well_supply_power_W':'W'}
units.update(input_bias_V='V',nominal_current_A='A',nominal_current_relative_error='1',output_resistance_ohm='ohm',
    output_conductance_10Hz_S='S',compliance_5percent_sampled_low_V='V',compliance_5percent_sampled_high_V='V',
    max_current_relative_error_1p3_to_1p7V='1',external_reference_supply_power_W='W',DUT_input_port_power_W='W',DUT_output_port_power_W='W')
for corner,row in record.get('corners',{}).items():
    metrics={name:{'value':row['metrics'][name],'unit':unit} for name,unit in units.items() if name in row['metrics']}
    metrics['area']={'value':record['area_um2'],'unit':'um2'}
    observation['corners'][corner]={'converged':row['complete'],'operating_point_valid':row['operating_point_valid'],'metrics':metrics}
    artifacts['spice'][corner]={'analyses':{name:{'data':corner+'/'+name+'.dat','log':corner+'/'+('ac' if name=='op' else name)+'.log','returncode':values['returncode']} for name,values in row['analyses'].items()}}
assessment=assess(contract,observation);complete=record.get('full_physical_analysis_complete',False)
validation={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assessment,'analysis_complete':complete,
    'execution_integrity':'valid' if complete else 'incomplete','failure_class':None if assessment['S2'] else 'candidate' if complete else 'unknown',
    'point_evaluation_complete':complete,'scope':'independent_trusted_point_evaluation_host_owns_phase_and_domain'}
(out/'validation.json').write_text(json.dumps(validation,indent=2)+'\n');print(json.dumps(validation),flush=True)
raise SystemExit(0 if assessment['S2'] and complete else 2)
