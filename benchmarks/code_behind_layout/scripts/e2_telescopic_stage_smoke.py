"""One bounded real telescopic geometry -> PEX -> two-deck nominal -> full.

This development control uses the already qualified default source/N. It tests
the exact isolated E2 transport; it never starts a candidate pool or changes a
size, bias, load, solver, timeout or specification after observing a result.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def implementation():
    from scripts.e2_four_source import IMPLEMENTATION,digest
    # The materializer/freezer performs no measured tool operation. Its later
    # formal freeze binds its bytes separately; only physical-path code belongs
    # to this premeasurement transport snapshot.
    return {name:digest(ROOT/name) for name in IMPLEMENTATION if name!='scripts/e2_four_source.py'}


def audit_smoke(summary,manifest):
    from scripts.e2_four_source import raw_run,artifact_path,digest
    from src.device_intent import compare_device_intent
    from src.domain_runner import inspect_point,source_contents
    from src.spice_validation import validate_analysis
    report=read(summary)
    if report['status']!='COMPLETE' or report['passed'] is not True:
        raise ValueError('One real complete telescopic staged transport control is required')
    for name,value in report['implementation_sha256'].items():
        if digest(ROOT/name)!=value:raise ValueError('Implementation changed after the real stage control: '+name)
    pool=next(p for p in manifest['pools'] if p['pool_id']=='telescopic_s1');point=read(pool['point'])
    if point['parameters']!=report['point']['parameters'] or point['contract']!=report['point']['contract']:
        raise ValueError('Actual nominal/full transport control used another sized electrical contract')
    generation=Path(report['stages']['geometry']['run_directory'])
    physical=Path(report['stages']['pex']['run_directory'])
    nominal=Path(report['stages']['nominal']['run_directory'])
    full=Path(report['stages']['full']['run_directory'])
    with raw_run(generation) as g,raw_run(physical) as p,raw_run(nominal) as n,raw_run(full) as f:
        generated=read(g/'evidence/validation.json');pex=read(p/'evidence/validation.json')
        nom=read(n/'evidence/validation.json');complete=read(f/'evidence/validation.json')
        if not generated['requested_fidelity_complete'] or generated['physical_tool_calls']!={'DRC':0,'LVS':0,'PEX':0,'SPICE':0}:
            raise ValueError('Actual geometry stage exceeded its declared fidelity')
        if not pex['requested_fidelity_complete'] or not pex['assessment']['S1'] or pex['physical_tool_calls']['SPICE']!=0:
            raise ValueError('Actual PEX-only control incomplete or ran an undeclared simulator')
        if any(pex['physical_tool_calls'][name]!=1 for name in ['DRC','LVS','PEX']):
            raise ValueError('Expected exactly one actual independent physical acquisition')
        if not compare_device_intent((p/'evidence/extracted_lvs.spice').read_text(),Path(point['reference_file']).read_text())['is_clean']:
            raise ValueError('Actual stage control lacks the exact per-finger terminal intent')
        measurement=nom['nominal']
        if (not nom['requested_fidelity_complete'] or nom['S2'] is not False or nom['point_evaluation_complete'] is not False
                or nom['physical_tool_calls']!={'DRC':0,'LVS':0,'PEX':0,'SPICE':2}
                or measurement['new_SPICE_calls']!=2 or measurement['new_Tran_DC_SS_FF_SPICE_calls']!=0):
            raise ValueError('Nominal did not actually run only the two declared original TT analyses')
        if complete['physical_tool_calls']!={'DRC':0,'LVS':0,'PEX':0,'SPICE':12}:
            raise ValueError('Full did not preserve twelve actual analyses / shared physical acquisition')
        if (g/'source'/pool['layout_target']).read_bytes()!=Path(pool['source_snapshot']).read_bytes():
            raise ValueError('Actual generated source differs from the proposed frozen source')
        for name in ['original_bench.py','ota_frozen_bench.py']:
            if (f/'trusted'/name).read_bytes()!=(Path(pool['full_trusted'])/name).read_bytes():
                raise ValueError('Actual protected bench binding changed: '+name)
        actual_names=read(f/'manifest.json')['source_files']
        checked=inspect_point({'run_directory':str(f)},point,source_contents(f/'source',actual_names,binary=True),
            {'parameters':point['parameters']},gold_control_check=False)
        if not checked['S2'] or not checked['analysis_complete']:raise ValueError('Actual full control incomplete or fails the fixed spec')
        for root in [p,n,f]:
            if (root/'accepted/candidate.gds').read_bytes()!=(g/'accepted/candidate.gds').read_bytes():
                raise ValueError('A staged control changed the exact accepted GDS')
        original_rc=(p/'evidence'/pex['artifacts']['pex']['netlist']).read_bytes()
        for root,row in [(n,nom),(f,complete)]:
            path=(root/'evidence/telescopic_mirror_ota_pex.spice')
            if path.read_bytes()!=original_rc:raise ValueError('An electrical stage changed the positive full RC')
        for name in ['op','ac']:
            artifact=measurement['analyses'][name]
            data=artifact_path(n/'evidence',artifact['data']);log=artifact_path(n/'evidence',artifact['log'])
            if not validate_analysis(data,log,point['contract']['analysis_contracts'][name],artifact['returncode'])['complete']:
                raise ValueError('Nominal original OP/AC raw coverage is incomplete')
            if (n/'evidence/nominal_tt'/(name+'.spice')).read_bytes()!=(f/'evidence/post_rc_measurements/tt'/(name+'.spice')).read_bytes():
                raise ValueError('Nominal TT stimulus is not byte-identical to the original full TT deck')
            # Identical numerical settings/decks should yield the same vectors;
            # allow only print-rounding scale, not a new physical tolerance.
            import numpy as np
            left=np.loadtxt(data,skiprows=1,ndmin=2)
            right=np.loadtxt(f/'evidence/post_rc_measurements/tt'/(name+'.dat'),skiprows=1,ndmin=2)
            if left.shape!=right.shape or not np.allclose(left,right,rtol=1e-9,atol=1e-12):
                raise ValueError('Nominal/full original TT vectors differ')
        original=complete['observation']['corners']['tt']['metrics']['ugb']['value'];value=measurement['metrics']['tt_ugb_Hz']
        relative=abs(original-value)/abs(original)
        if relative>1e-6:raise ValueError('Nominal/full TT UGB transport differs')
        stages=[read(root/'manifest.json') for root in [g,p,n,f]]
        if any(datetime.fromisoformat(a['trusted']['ended_at_utc'])>datetime.fromisoformat(b['candidate']['started_at_utc']) for a,b in zip(stages,stages[1:])):
            raise ValueError('Actual nominal stage did not precede the full stage')
    return {'passed':True,'summary':str(Path(summary).resolve()),'complete_actual_geometry_PEX_nominal_full':True,
        'nominal_SPICE_calls':2,'full_SPICE_calls':12,'nominal_full_TT_UGB_relative_error':relative,
        'same_GDS_and_positive_RC':True,'nominal_claims_S2':False,'new_EDA_calls_during_audit':0}


def smoke(old_manifest,output,calibration):
    from scripts.e2_telescopic_adapter import point,trusted,source_pack,pool_class
    from scripts.e2_execution import COPY
    from scripts.e2_stage_prepare import build,cached
    from src.generators.telescopic_ota_reference import DEFAULT,schematic
    from src.promotion_calibration import NominalWorstCalibration
    from scripts.archive_e2_run import archive
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    report={'scope':'actual_E2_telescopic_isolated_stage_transport_control_NOT_FORMAL',
        'status':'RUNNING','passed':False,'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'implementation_sha256':implementation(),'stages':{},'retries_allowed':False}
    save(output/'report.json',report)
    old=read(old_manifest);primitive=next(p for p in old['pools'] if p['pool_id']=='five_t_s1')
    inputs=output/'inputs';inputs.mkdir();pack=inputs/'source'
    names=source_pack(primitive['source_dir'],primitive['source_paths'],pack)
    ref=inputs/'reference.spice';ref.write_text(schematic(DEFAULT));p=point(DEFAULT,'s1',ref)
    save(inputs/'point.json',p);trusted(p,inputs/'trusted_full')
    pool={'pool_id':'telescopic_s1','source_family':'telescopic','point':str(inputs/'point.json'),
        'source_dir':str(pack),'source_paths':names,'layout_target':'src/generators/telescopic_ota.py',
        'source_snapshot':str(pack/'src/generators/telescopic_ota.py'),'full_trusted':str(inputs/'trusted_full'),
        'top_cell':'telescopic_mirror_ota','development_mask_paths':[],'candidate_stream':[]}
    controller=pool_class()({'heuristics':{'full_budget':16}},pool,output/'execution','full_oracle',False,
        NominalWorstCalibration(read(calibration)))
    report['point']=p
    try:
        geom=inputs/'geometry_trusted';files=build('geometry',geom,top=pool['top_cell'])
        if any(name in files for name in ['contract.json','reference.spice','original_bench.py']):raise ValueError('Geometry template mounted gold/bench')
        def execute(source,names,trusted,files,fidelity,stage,label):
            result=controller.execute(source,names,trusted,files,fidelity,stage,0)
            report['stages'][label]=result;save(output/'report.json',report)
            return result
        generation=execute(pack,names,geom,files,'geometry','source_to_geometry','geometry')
        if not (generation.get('physical_result') or {}).get('requested_fidelity_complete'):raise ValueError('Actual geometry stage incomplete')
        copied=inputs/'retained_gds_source';copied.mkdir();(copied/'generator.py').write_text(COPY)
        shutil.copyfile(Path(generation['run_directory'])/'accepted/candidate.gds',copied/'input.gds')
        phys=inputs/'pex_trusted';files=build('pex',phys,top=pool['top_cell'],point=p,full_trusted=pool['full_trusted'])
        physical=execute(copied,['generator.py','input.gds'],phys,files,'pex','actual_physical_PEX','pex')
        row=physical.get('physical_result') or {}
        if not row.get('requested_fidelity_complete') or not row.get('assessment',{}).get('S1'):raise ValueError('Actual positive full-PEX stage not qualified')
        nom=inputs/'nominal_trusted';files=cached(nom,point=p,full_trusted=pool['full_trusted'],physical_run=physical['run_directory'],nominal=True)
        nominal=execute(copied,['generator.py','input.gds'],nom,files,'pex_spice','actual_nominal_TT_OP_AC','nominal')
        if not (nominal.get('physical_result') or {}).get('requested_fidelity_complete'):raise ValueError('Actual two-deck nominal stage incomplete')
        full=inputs/'electrical_trusted';files=cached(full,point=p,full_trusted=pool['full_trusted'],physical_run=physical['run_directory'])
        execute(copied,['generator.py','input.gds'],full,files,'pex_spice','full_electrical_on_retained_PEX','full')
        report.update(status='COMPLETE',passed=True);save(output/'report.json',report)
        report['raw_transport_audit']=audit_smoke(output/'report.json',{'pools':[pool]})
        report['new_formal_labels']=0;report['completed_at_utc']=datetime.now(timezone.utc).isoformat()
        save(output/'report.json',report)
    except Exception as error:
        report.update(status='FAILED_OR_UNKNOWN_RETAINED_NO_RETRY',passed=False,error=type(error).__name__+': '+str(error))
        save(output/'report.json',report);raise
    finally:
        for stage,result in report['stages'].items():
            report.setdefault('raw_archives',{})[stage]=archive(result['run_directory'],retain_accepted_gds=stage=='geometry')
        save(output/'report.json',report)
    return {'report':str(output/'report.json'),'passed':report['passed'],'new_formal_labels':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--old-manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True);a=p.parse_args()
    print(json.dumps(smoke(a.old_manifest,a.output,a.calibration),allow_nan=False),flush=True)
