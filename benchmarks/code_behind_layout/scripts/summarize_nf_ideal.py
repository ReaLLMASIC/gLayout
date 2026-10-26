"""Read actual mirror ideal DC/OP evidence without launching a simulator."""
import argparse
import json
from pathlib import Path


def summarize(run):
    run=Path(run);raw=json.loads((run/'ideal_control.json').read_text());rows=[]
    for point in raw['points']:
        for corner,data in point['corners'].items():
            metrics=data.get('ideal_metrics',{});band=[v['relative_error'] for v in metrics.get('dc_sweep_relative_errors',[]) if .7-1e-7<=v['voltage_V']<=1+1e-7]
            op_path=run/point['configuration_id']/corner/'op.dat'
            values=[[float(v) for v in line.split()] for line in op_path.read_text().splitlines()[1:] if line.strip()] if op_path.exists() else []
            op=values[0] if len(values)==1 and len(values[0])==4 else None
            failed=[]
            if not data['complete']:failed.append('analysis_incomplete')
            if metrics.get('nominal_current_relative_error',float('inf'))>.05:failed.append('nominal_current_error')
            if metrics.get('output_resistance_ohm',0)<300000:failed.append('output_resistance')
            if len(band)!=4 or max(band)>.05:failed.append('sampled_compliance_band')
            rows.append({'configuration_id':point['configuration_id'],'corner':corner,'complete':data['complete'],
                'raw_declared_pass':data['ideal_application_constraints_pass'],'failed_declared_conditions':failed,
                'nominal_current_A':metrics.get('nominal_current_A'),'nominal_current_relative_error':metrics.get('nominal_current_relative_error'),
                'output_resistance_ohm':metrics.get('output_resistance_ohm'),'compliance_band_max_relative_error':max(band) if len(band)==4 else None,
                'sampled_compliance_5pct_lower_V':metrics.get('compliance_5pct_lower_V'),'sampled_compliance_5pct_upper_V':metrics.get('compliance_5pct_upper_V'),
                'OP_VGS_reference_and_output_V':op[2] if op else None,'OP_VDS_diode_reference_V':op[2] if op else None,
                'OP_VDS_output_V':op[1] if op else None,'OP_Iout_A':-op[3] if op else None,
                'OP_bias_and_output_VDS_difference_V':op[1]-op[2] if op else None,'op_path':str(op_path)})
    return {'scope':'read_only_actual_ideal_failure_diagnosis_not_training_labels','run_directory':str(run),
        'points':len(raw['points']),'qualified_points':sum(p['ideal_application_constraints_pass'] for p in raw['points']),
        'complete_corner_analyses':sum(row['complete'] for row in rows),'corner_rows':rows,
        'limitations':'Terminal OP voltages and DC slopes are measured. Internal MOS gm/gds/vth/vdsat were not recorded, so no unique BSIM mechanism or saturation claim is established.',
        'new_model_or_physical_calls':0,'old_results_or_contracts_changed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(summarize(args.run),indent=2,allow_nan=False))
