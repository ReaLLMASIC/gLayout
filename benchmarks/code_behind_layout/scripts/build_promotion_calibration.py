"""Fit the declared UGB model from actual train/validation AC tables only."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.device_intent import compare_device_intent
from src.promotion_calibration import fit_nominal_worst,NominalWorstCalibration
from src.report_parsers import magic_drc_report,netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis

AC={'kind':'ac','columns':3,'start':10.,'end':1e9,'points':241,'scale':'log'}


def read(path):return json.loads(Path(path).read_text())


def crossing(path,log,code):
    integrity=validate_analysis(path,log,AC,code)
    if not integrity['complete']:raise ValueError('Incomplete actual AC calibration input: '+str(path))
    values=[[float(x) for x in line.split()] for line in path.read_text().splitlines()[1:] if line.strip()]
    for left,right in zip(values,values[1:]):
        db0=20*math.log10(math.hypot(left[1],left[2]));db1=20*math.log10(math.hypot(right[1],right[2]))
        if db0>=0>db1:
            return 10**(math.log10(left[0])-db0/(db1-db0)*math.log10(right[0]/left[0]))
    raise ValueError('No observed positive-to-negative unity-gain crossing: '+str(path))


def physical_gate(base,reference,lvs,report,pex,top):
    if not magic_drc_report(report.read_text())['is_clean'] or not netgen_lvs_report(lvs.read_text())['is_clean']:
        raise ValueError('Actual DRC/LVS reports do not establish physical correctness')
    reference_text=reference.read_text()
    if not compare_device_intent((base/'layout_lvs.spice').read_text(),reference_text)['is_clean']:
        raise ValueError('Actual configuration reference device graph differs')
    ports=next(line.split()[2:] for line in reference_text.splitlines() if line.lower().startswith('.subckt '))
    if not rc_netlist_inventory(pex.read_text(),top,ports)['has_real_RC']:
        raise ValueError('Actual complete positive RC not established')


def train_rows(index):
    if index['source_lineage']!='textbook_universal_compiler_cropped' or index['circuit']!='C08_five_transistor_OTA':
        raise ValueError('The declared train-only calibration inventory changed')
    rows=[]
    for point in index['points']:
        base=Path(point['raw_run'])/'baseline';physical=read(base/'physical.json')
        if not physical['full_physical_analysis_complete'] or physical['source_revision']!='1f90e33913208e572744b7c5a144a7da8c073235':
            raise ValueError('C08 train source or full physical completion differs')
        if not physical['DRC']['completed'] or physical['DRC']['style']!='drc(full)':raise ValueError('DRC completion missing')
        physical_gate(base,base/'target.spice',base/'netgen_lvs.rpt',base/'drc_full/direct_drc.rpt',base/'corpus_c08_pex.spice','corpus_c08_rc')
        measured={c:crossing(base/c/'ac.dat',base/c/'ac.log',physical['corners'][c]['analyses']['ac']['returncode']) for c in ['tt','ss','ff']}
        rows.append({'parent_lineage':index['source_lineage'],'split':'train','measurement_id':point['configuration_id'],
            'nominal_ugb_Hz':measured['tt'],'worst_ugb_Hz':min(measured.values()),'corner_UGB_Hz':measured,
            'raw_evidence':[str(base)],'actual_three_corner_AC_complete':True,'source_phase_retained':'development_train_lineage',
            'DUT_load_F':1e-12})
    return rows


def validation_row(run,identifier):
    data=read(run/'qualification.json')
    if data['status']!='COMPLETE_VALIDATION_AC_CALIBRATION':raise ValueError('Validation AC qualification incomplete')
    if not data['DRC']['completed'] or data['DRC']['style']!='drc(full)':raise ValueError('Actual validation DRC completion missing')
    # Same independent checks as the train points, with the validation filenames.
    if not magic_drc_report((run/'drc_full/direct_drc.rpt').read_text())['is_clean'] or not netgen_lvs_report((run/'lvs.rpt').read_text())['is_clean']:
        raise ValueError('Validation physical reports differ from the summary')
    reference=(run/'independent_reference.spice').read_text()
    if not compare_device_intent((run/'extracted_lvs.spice').read_text(),reference)['is_clean']:raise ValueError('Validation device graph differs')
    ports=next(line.split()[2:] for line in reference.splitlines() if line.lower().startswith('.subckt '))
    if not rc_netlist_inventory((run/'validation_row_ota_pex.spice').read_text(),'validation_row_ota_rc',ports)['has_real_RC']:
        raise ValueError('Validation positive RC not established')
    measured={c:crossing(run/('postlayout_'+c)/'AC.dat',run/('postlayout_'+c)/'AC.log',data['measurements']['postlayout_'+c]['analyses']['AC']['returncode']) for c in ['tt','ss','ff']}
    return {'parent_lineage':'research_validation_row_bus_ota','split':'validation','measurement_id':identifier,
        'nominal_ugb_Hz':measured['tt'],'worst_ugb_Hz':min(measured.values()),'corner_UGB_Hz':measured,
        'raw_evidence':[str(run)],'actual_three_corner_AC_complete':True,'source_phase_retained':'validation_development',
        'DUT_load_F':data['load_F'],'layout':data['layout'],'full_S2_claim':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--train-index',type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--validation-domain',type=Path);group.add_argument('--validation-anchor',type=Path)
    p.add_argument('--registry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Do not overwrite a calibration artifact; create a new prospective version')
    train=train_rows(read(a.train_index));excluded=[]
    if a.validation_anchor:
        validation=[validation_row(a.validation_anchor,'anchor')];declared=1
    else:
        domain=read(a.validation_domain)
        if domain['status']!='TERMINAL_DECLARED_DOMAIN':raise ValueError('The full declared validation domain has not terminated')
        declared=domain['declared_configurations'];validation=[]
        for point in domain['points']:
            if point['measurement']['actual_AC_calibration_complete']:
                validation.append(validation_row(Path(point['measurement']['run_directory']),point['configuration_id']))
            else:excluded.append({'configuration_id':point['configuration_id'],'measurement':point['measurement'],
                'reason':'Actual AC target unavailable; preserved as declared failure, no replacement configuration'})
    artifact=fit_nominal_worst(train,validation,read(a.registry))
    model=NominalWorstCalibration(artifact)
    artifact.update(created_at_utc=datetime.now(timezone.utc).isoformat(),validation_declared_configurations=declared,
        validation_unavailable_points=excluded,validation_predictions=[{'measurement_id':r['measurement_id'],**model.predict(r['nominal_ugb_Hz']),
        'actual_worst_ugb_Hz':r['worst_ugb_Hz']} for r in validation],
        registry_snapshot_path=str(a.registry.resolve()),evaluation_lineages_or_outcomes_used=False,
        validation_ancestry='Separately authored row/bus assembly; common MOS/terminal-access primitives and high-level row/global-bus strategy shared with an evaluation assembly, disclosed limitation')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:artifact[k] for k in ['version','status','train_measurements','validation_measurements','train_source_lineages','validation_source_lineages','validation_radius_log','formal_calibration_freeze']}))


if __name__=='__main__':main()
