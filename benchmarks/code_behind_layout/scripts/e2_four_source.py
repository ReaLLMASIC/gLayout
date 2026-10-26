"""Prepare, qualify, freeze and dispatch the prospective four-source E2 matrix.

This consumer keeps the measured legacy failures in their original development
records. It imports the unchanged three-source Pool and specializes only the
new telescopic nominal transport. Preparation never runs an EDA tool.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import resource
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
FAMILIES=['five_t','compact_miller','fvf','telescopic']
ONLINE=[f'{f}_{s}' for f in FAMILIES[:3] for s in ['s0','s2']]
METHODS=['full_oracle','fixed_area','adaptive_geometry','fixed_rc_product','f3_calibrated']
IMPLEMENTATION=['scripts/e2_four_source.py','scripts/e2_telescopic_adapter.py',
    'scripts/e2_telescopic_frozen_bench.py','scripts/e2_telescopic_stage_smoke.py',
    'scripts/e2_execution.py','scripts/e2_stage_prepare.py','scripts/e2_cached_evaluator.py',
    'scripts/e2_nominal_bench.py','scripts/e2_spice_process_profile.py','scripts/e2_geometry_evaluator.py',
    'scripts/e2_mask_stage.py','scripts/archive_e2_run.py','src/candidate_executor.py',
    'src/e2_mask_geometry.py','src/device_intent.py','src/measurement.py','src/report_parsers.py',
    'src/spice_validation.py','src/promotion_calibration.py','src/domain_runner.py']


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matrix(manifest):
    pools=manifest['pools']
    expected={f'{f}_{s}' for f in FAMILIES for s in ['s0','s1','s2']}
    if len(pools)!=12 or {p['pool_id'] for p in pools}!=expected:
        raise ValueError('E2 requires exactly four sources x three sizings, excluding legacy')
    if [p['pool_id'] for p in pools if p['online_selected']]!=ONLINE:
        raise ValueError('The six online identities were fixed before pool outcomes')
    if manifest['candidate_pool_size']!=64 or manifest['maximum_generation_attempts_per_pool']!=256:
        raise ValueError('The prospective 64 accepted / 256 attempted stream changed')
    if manifest.get('heuristics',{}).get('full_budget')!=16:
        raise ValueError('The E2 online budget remains sixteen actual full attempts')
    for pool in pools:
        stream=pool['candidate_stream']
        if len(stream)!=256 or [r['stream_index'] for r in stream]!=list(range(256)):
            raise ValueError('A pool must retain its complete ordered prospective stream')
    return {'sources':4,'sizings_per_source':3,'offline_pools':12,'oracle_full_attempts_max':768,
        'online_pools_per_method':6,'online_methods':4,'online_full_attempts_max':384,
        'all_methods_full_attempts_max':1152,'generation_attempts_max_per_execution':256,
        'nominal_or_PEX_acquisitions_are_additional_charged_cost':True}


def controls_map(path,require_all=True):
    report=read(path);rows=report['controls']
    result={r['pool_id']:r for r in rows}
    if len(result)!=len(rows):raise ValueError('Duplicate sizing controls')
    if require_all and set(result)!={f'{f}_{s}' for f in FAMILIES for s in ['s0','s1','s2']}:
        raise ValueError('All twelve actual control identities must be supplied')
    return result


def prepare(old_path,plan_path,controls_path,output):
    from scripts.e2_telescopic_adapter import point,trusted,source_pack,variant
    from src.generators.telescopic_ota_reference import schematic
    output=Path(output).resolve();old=read(old_path);plan=read(plan_path)
    controls=controls_map(controls_path,require_all=False)
    output.mkdir(parents=True,exist_ok=False)
    manifest=copy.deepcopy(old)
    manifest.update(status='DRAFT_NOT_FROZEN',formal_execution_allowed=False,pools=[],
        prepared_at_utc=datetime.now(timezone.utc).isoformat(),scope='prospective_E2_four_independent_assemblies',
        original_three_source_manifest=str(Path(old_path).resolve()),prospective_plan=str(output/'prospective_plan.json'),
        actual_admission_controls=str(output/'admission_controls.json'),development_labels_reused_as_formal=False,
        legacy_not_in_new_formal_matrix=True,legacy_original_records_unchanged=True)
    save(output/'prospective_plan.json',plan);save(output/'admission_controls.json',read(controls_path))
    manifest['calibrated_F3']={'admitted':False,'artifact_required':True,'fit_from_evaluation_outcomes':False}
    manifest['blocking_before_freeze']=plan['required_actual_pre_freeze_controls']
    family_sources={};family_streams={}
    for family in FAMILIES[:3]:
        originals=[p for p in old['pools'] if p['source_family']==family]
        if len(originals)!=3:raise ValueError('The original source has a missing sizing: '+family)
        base=originals[0];directory=output/family;directory.mkdir()
        pack=directory/'source';shutil.copytree(base['source_dir'],pack)
        family_sources[family]=(pack,base['source_paths'])
        patches=directory/'layout_patches';patches.mkdir();stream=[]
        declared=plan['candidate_streams'][family]
        if [r['controls'] for r in base['candidate_stream']]!=[r['controls'] for r in declared]:
            raise ValueError('The previously predeclared three-source stream changed')
        for row in base['candidate_stream']:
            p=patches/Path(row['patch']).name;shutil.copyfile(row['patch'],p)
            stream.append({**row,'patch':str(p)})
        family_streams[family]=stream
        for prior in originals:
            pool=copy.deepcopy(prior);sid=pool['sizing_id'];sized=directory/sid;sized.mkdir()
            ref=sized/'reference.spice';oldpoint=read(pool['point']);shutil.copyfile(oldpoint['reference_file'],ref)
            oldpoint['reference_file']=str(ref);save(sized/'point.json',oldpoint)
            shutil.copytree(pool['full_trusted'],sized/'trusted_full')
            if read(sized/'trusted_full/contract.json')!=oldpoint['contract']:
                raise ValueError('The old physical control and original bench contract disagree')
            pool.update(point=str(sized/'point.json'),source_dir=str(pack),source_snapshot=str(pack/pool['layout_target']),
                full_trusted=str(sized/'trusted_full'),candidate_stream=stream,online_selected=pool['pool_id'] in ONLINE,
                source_qualified=False,physical_control_pending=True)
            manifest['pools'].append(pool)
    directory=output/'telescopic';directory.mkdir();pack=directory/'source'
    primitive_pack,primitive_files=family_sources['five_t']
    files=source_pack(primitive_pack,primitive_files,pack)
    before=(pack/'src/generators/telescopic_ota.py').read_text()
    patches=directory/'layout_patches';patches.mkdir();stream=[]
    for row in plan['candidate_streams']['telescopic']:
        after=variant(before,row['controls']);path=patches/f"layout_{row['stream_index']:03d}.patch"
        path.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
            fromfile='src/generators/telescopic_ota.py',tofile='src/generators/telescopic_ota.py')))
        stream.append({**row,'patch':str(path)})
    for size in plan['source_qualifications']['telescopic']['independent_sizings']:
        sid=size['sizing_id'];sized=directory/sid;sized.mkdir();reference=sized/'reference.spice'
        reference.write_text(schematic(size['sizing']));p=point(size['sizing'],sid,reference);save(sized/'point.json',p)
        trusted(p,sized/'trusted_full')
        manifest['pools'].append({'pool_id':'telescopic_'+sid,'source_family':'telescopic','sizing_id':sid,
            'point':str(sized/'point.json'),'source_dir':str(pack),'source_paths':files,'entrypoint':'generator.py',
            'layout_target':'src/generators/telescopic_ota.py','source_snapshot':str(pack/'src/generators/telescopic_ota.py'),
            'full_trusted':str(sized/'trusted_full'),'top_cell':'telescopic_mirror_ota','candidate_stream':stream,
            'source_qualified':False,'physical_control_pending':True,'development_mask_paths':[],'online_selected':False})
    for pool in manifest['pools']:
        masks=list(pool['development_mask_paths'])
        control=controls.get(pool['pool_id'])
        if control and control.get('mask_gds'):masks.append(control['mask_gds'])
        target=Path(pool['point']).parent/'retained_development_masks';target.mkdir()
        retained=[]
        for index,source in enumerate(dict.fromkeys(masks)):
            source=Path(source).resolve()
            if not source.is_file():raise ValueError('Declared known development mask missing: '+str(source))
            destination=target/f'{index:03d}.gds'
            # One retained inode avoids a second heavy GDS copy. Byte bindings
            # are checked at freeze; accepted GDS stays available for exact XOR.
            import os
            os.link(source,destination);retained.append(str(destination))
        pool['development_mask_paths']=retained
    manifest['counts']=matrix(manifest)
    manifest['source_group_caveat']=plan['independence_limit']
    save(output/'execution_manifest.json',manifest)
    preflight(manifest)
    return {'status':manifest['status'],'manifest':str(output/'execution_manifest.json'),**manifest['counts'],
        'new_EDA_calls':0,'formal_labels':0}


def preflight(manifest):
    """Actually apply all literal patches to one target, compile, restore."""
    tested=set();patches=0
    for pool in manifest['pools']:
        identity=(pool['source_family'],pool['source_snapshot'])
        if identity in tested:continue
        tested.add(identity)
        with tempfile.TemporaryDirectory(prefix='e2_patch_preflight_') as tmp:
            target=Path(tmp)/pool['layout_target'];target.parent.mkdir(parents=True)
            original=Path(pool['source_snapshot']).read_bytes()
            for row in pool['candidate_stream']:
                target.write_bytes(original)
                command=subprocess.run(['patch','--batch','--fuzz=0','-p0','-i',str(Path(row['patch']).resolve())],
                    cwd=tmp,capture_output=True,text=True)
                if command.returncode:raise ValueError('Frozen patch cannot apply: '+command.stdout+command.stderr)
                ast.parse(target.read_text());patches+=1
    if patches!=1024:raise ValueError('Expected four complete 256-member patch streams')
    return {'literal_patches_applied_and_AST_compiled':patches,'new_EDA_calls':0}


@contextmanager
def raw_run(path):
    """Inspect already-archived evidence without repopulating the live run."""
    path=Path(path).resolve();archive=path/'terminal_raw.tar.gz'
    if not archive.is_file():yield path;return
    index=read(path/'raw_archive.json')
    if index.get('byte_exact_all_members_verified') is not True:raise ValueError('Raw archive lacks its original byte comparison')
    with tempfile.TemporaryDirectory(prefix='e2_admission_raw_') as tmp:
        root=Path(tmp)
        with tarfile.open(archive,'r:gz') as saved:
            for member in saved.getmembers():
                relative=Path(member.name)
                if relative.is_absolute() or '..' in relative.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected nonregular original evidence member')
                destination=root/relative
                if member.isdir():destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with saved.extractfile(member) as source,destination.open('wb') as target:shutil.copyfileobj(source,target)
        yield root


def artifact_path(root,path):
    path=Path(path)
    if path.is_absolute():path=path.relative_to('/evidence')
    if '..' in path.parts:raise ValueError('Analysis escaped original evidence')
    return Path(root)/path


def repository_path(value):
    path=Path(value)
    return ROOT/path.relative_to('/work') if path.is_relative_to('/work') else path


def control_source(pool,control):
    """A disclosed previously measured stream member can be an N(z) control.

    Its complete source bytes must equal the literal frozen source plus that
    exact predeclared patch. Merely matching layout control values is not enough.
    Its known GDS is excluded from subsequent prospective formal generation.
    """
    if 'layout_patch_index' not in control:return Path(pool['source_snapshot']).read_bytes()
    index=control['layout_patch_index']
    candidate=next((r for r in pool['candidate_stream'] if r['stream_index']==index),None)
    if candidate is None:raise ValueError('The qualification source is outside the predeclared geometric stream')
    with tempfile.TemporaryDirectory(prefix='e2_control_source_') as tmp:
        path=Path(tmp)/pool['layout_target'];path.parent.mkdir(parents=True)
        path.write_bytes(Path(pool['source_snapshot']).read_bytes())
        result=subprocess.run(['patch','--batch','--fuzz=0','-p0','-i',str(Path(candidate['patch']).resolve())],cwd=tmp,capture_output=True,text=True)
        if result.returncode:raise ValueError('Previously measured layout-source patch cannot apply')
        ast.parse(path.read_text());return path.read_bytes()


def audit_executor_control(pool,control):
    from src.domain_runner import inspect_point,source_contents
    from src.device_intent import compare_device_intent
    from src.measurement import assess
    point=read(pool['point']);run=Path(control['run_directory'])
    with raw_run(run) as actual:
        record=read(actual/'evidence/validation.json');historical=copy.deepcopy(point)
        historical['contract']=record['contract']
        for key in ['configuration_id','reference_id']:historical[key]=record['contract'][key]
        if record['contract'].get('immutable_parameters')!=point['parameters']:
            raise ValueError('Actual sized control differs from the independent prospective N')
        if (actual/'evidence/reference.spice').read_bytes()!=Path(point['reference_file']).read_bytes():
            raise ValueError('Actual independent gold differs from this fixed sizing')
        if (actual/'trusted/original_bench.py').read_bytes()!=(Path(pool['full_trusted'])/'original_bench.py').read_bytes():
            raise ValueError('Actual electrical bench differs from the proposed fixed bench')
        names=read(actual/'manifest.json')['source_files']
        checked=inspect_point({'run_directory':str(actual)},historical,source_contents(actual/'source',names,binary=True),
            {'parameters':point['parameters']},gold_control_check=False)
        if not checked['S2'] or not checked['analysis_complete']:raise ValueError('Sizing control is not actual complete S2')
        graph=compare_device_intent((actual/'evidence/extracted_lvs.spice').read_text(),Path(point['reference_file']).read_text())
        if not graph['is_clean']:raise ValueError('Raw control fails independent per-finger terminal intent')
        observation=copy.deepcopy(record['observation'])
        for key in ['task_id','configuration_id','reference_id']:observation[key]=point['contract'][key]
        if not assess(point['contract'],observation)['S2']:raise ValueError('Old evidence does not meet the unchanged prospective specifications')
    origin=Path(control['source_generation_run'])
    with raw_run(origin) as actual:
        if (actual/'source'/pool['layout_target']).read_bytes()!=control_source(pool,control):
            raise ValueError('Actual control generation used another high-level source')
        if (actual/'accepted/candidate.gds').read_bytes()!=Path(control['mask_gds']).read_bytes():
            raise ValueError('Known control geometry differs from the actual generated GDS')
    return {'pool_id':pool['pool_id'],'run_directory':str(run),'source_generation_run':str(origin),
        'complete_S2':True,'raw_per_finger_graph_rechecked':True,'new_EDA_calls':0,
        'disclosed_development_stream_patch_index':control.get('layout_patch_index')}


def audit_telescopic_control(pool,control):
    from scripts.e2_telescopic_frozen_bench import normalize
    from src.device_intent import compare_device_intent
    from src.spice_validation import validate_analysis
    from src.report_parsers import magic_drc_report,netgen_lvs_report,rc_netlist_inventory
    from src.measurement import assess
    from src.generators.telescopic_ota_reference import PORTS
    run=Path(control['run_directory']);point=read(pool['point']);record=read(run/'qualification.json')
    if record['status']!='COMPLETE' or any(record[k] is not True for k in ['S0','S1','S2']):
        raise ValueError('The new telescopic sizing has no actual complete positive control')
    if record['sizing']!=point['parameters']:raise ValueError('Telescopic control sizing changed')
    if (run/'independent_reference.spice').read_bytes()!=Path(point['reference_file']).read_bytes():
        raise ValueError('Telescopic control independent N differs')
    if (run/'telescopic_ota.py').read_bytes()!=Path(pool['source_snapshot']).read_bytes():
        raise ValueError('Telescopic control generated another source')
    if read(run/'frozen_fullflow_declaration.json')!=read(Path(pool['full_trusted'])/'telescopic_declaration.json'):
        raise ValueError('Telescopic application or numeric contract changed')
    from scripts.telescopic_sizing_qualification import functions
    recorded_source=run/'telescopic_ota_fullflow.py'
    if not recorded_source.is_file():
        prepared=repository_path(record['sizing_qualification_provenance']['preparation'])
        recorded_source=prepared/'source_snapshot/scripts/telescopic_ota_fullflow.py'
    names={'bench_decks','electrical','printed_mos_OP','power'}
    if functions(recorded_source.read_text(),names)!=functions((Path(pool['full_trusted'])/'original_bench.py').read_text(),names):
        raise ValueError('Actual telescopic control used another electrical deck renderer or measurement function')
    drc=record['DRC']
    # check_gds retains both completed full-rule metadata and its raw report.
    if not drc['completed'] or drc['style']!='drc(full)' or not drc['is_clean'] or not magic_drc_report((run/'drc_full/direct_drc.rpt').read_text())['is_clean']:
        raise ValueError('Full-rule DRC control is not actually clean')
    if not netgen_lvs_report((run/'lvs.rpt').read_text())['is_clean']:
        raise ValueError('Actual independent LVS did not pass')
    if not compare_device_intent((run/'extracted_lvs.spice').read_text(),Path(point['reference_file']).read_text())['is_clean']:
        raise ValueError('Telescopic raw per-finger terminal graph differs')
    if not rc_netlist_inventory((run/'telescopic_mirror_ota_pex.spice').read_text(),'telescopic_mirror_ota_rc',PORTS)['has_real_RC']:
        raise ValueError('Telescopic control has no accepted positive full RC')
    corners=normalize(record['corners'],run)['corners']
    for corner,row in corners.items():
        for name,requirement in point['contract']['analysis_contracts'].items():
            artifact=row['analyses'][name]
            if not validate_analysis(artifact['data'],artifact['log'],requirement,artifact['returncode'])['complete']:
                raise ValueError('Telescopic original corner analysis incomplete')
        row['metrics']['original_development_predicate']={'value':int(row['original_development_constraints_passed']),'unit':'1'}
    observation={**{key:point['contract'][key] for key in ['task_id','configuration_id','reference_id']},
        'executed':True,'gds_emitted':True,'checks':{k:True for k in ['drc','lvs','devices','ports','intent']},
        'pex':{'executed':True,'kind':'physical_rc','resistance_extracted':True,'capacitance_extracted':True},'corners':corners}
    if not assess(point['contract'],observation)['S2']:raise ValueError('Actual telescopic corner metrics fail prospective contract')
    if Path(control['mask_gds']).read_bytes()!=(run/'telescopic_mirror_ota.gds').read_bytes():
        raise ValueError('Known telescopic development geometry does not bind the actual control')
    return {'pool_id':pool['pool_id'],'run_directory':str(run),'complete_S2':True,
        'raw_per_finger_graph_rechecked':True,'new_EDA_calls':0}


def audit_telescopic_ideals(manifest,controls):
    from src.spice_validation import validate_analysis
    from scripts.telescopic_ota_characterization import device_OP
    roots={str(repository_path(read(Path(controls['telescopic_'+sid]['run_directory'])/'qualification.json')
        ['sizing_qualification_provenance']['ideal_run'])) for sid in ['s0','s2']}
    if len(roots)!=1:raise ValueError('The nondefault telescope sizes must use their single fixed six-call ideal sequence')
    root=Path(roots.pop());summary=read(root/'summary.json')
    prepared=repository_path(read(root/'input_preparation_binding.json')['preparation']);declaration=read(prepared/'manifest.json')
    if (summary['all6_corner_calls_complete'] is not True or summary['actual_new_ideal_calls']!=6
            or set(summary['positive_sizing_ids'])!={'s0','s2'} or len(summary['records'])!=6):
        raise ValueError('The original six ideal calls are incomplete or a fixed sizing is infeasible')
    identities={(r['control_id'],r['corner']) for r in summary['records']}
    if identities!={(s,c) for s in ['s0','s2'] for c in ['tt','ss','ff']}:
        raise ValueError('The original six ideal identities changed')
    for row in summary['records']:
        sid=row['control_id'];corner=row['corner'];directory=root/sid/corner
        pool=next(p for p in manifest['pools'] if p['pool_id']=='telescopic_'+sid);point=read(pool['point'])
        if declaration['fixed_sizings'][sid]!=point['parameters'] or (prepared/sid/'independent_reference.spice').read_bytes()!=Path(point['reference_file']).read_bytes():
            raise ValueError('Actual ideal independent N differs from its prospective fixed sizing')
        control=next(c for c in declaration['controls'] if c['id']==sid)
        if (directory/'analysis.spice').read_bytes()!=(prepared/control['predeclared_decks'][corner]).read_bytes():
            raise ValueError('Actual ideal deck differs from its premeasurement rendering')
        if not row['complete'] or not row['ideal_OP_AC_requirements_passed'] or not device_OP((directory/'ngspice.log').read_text(),32)['complete']:
            raise ValueError('Actual ideal OP/AC requirements or per-finger OP failed')
        for name,contract in declaration['analysis_contracts'].items():
            data=directory/('operating_point.dat' if name=='op' else 'ac.dat')
            if not validate_analysis(data,directory/'ngspice.log',contract,row['returncode'])['complete']:
                raise ValueError('An actual predeclared ideal OP/AC call is incomplete')
    return {'actual_six_call_run':str(root),'all6_raw_corner_calls_complete_and_positive':True,
        'actual_ideal_calls':6,'new_EDA_calls_during_audit':0}


def input_files(manifest):
    paths=set()
    for pool in manifest['pools']:
        for name in pool['source_paths']:paths.add(str(Path(pool['source_dir'])/name))
        paths.add(pool['point']);paths.add(read(pool['point'])['reference_file'])
        paths.update(str(p) for p in Path(pool['full_trusted']).rglob('*') if p.is_file())
        paths.update(row['patch'] for row in pool['candidate_stream'])
        paths.update(pool['development_mask_paths'])
    paths.update([manifest['prospective_plan'],manifest['actual_admission_controls']])
    return sorted(paths)


def verify(manifest):
    if manifest['status']!='FROZEN' or manifest.get('formal_execution_allowed') is not True:
        raise ValueError('Only the separately qualified FROZEN E2 manifest can dispatch formal work')
    matrix(manifest)
    for name,value in manifest['implementation_sha256'].items():
        if digest(ROOT/name)!=value:raise ValueError('Formal E2 implementation drift: '+name)
    for name,value in manifest['immutable_input_sha256'].items():
        if digest(name)!=value:raise ValueError('Formal E2 source/bench/input drift: '+name)


def reserve(manifest,pool,method,output):
    directory=ROOT/'runs/formal/E2_reservations'/manifest['freeze_id']/method
    directory.mkdir(parents=True,exist_ok=True);path=directory/(pool['pool_id']+'.json')
    record={'freeze_id':manifest['freeze_id'],'pool_id':pool['pool_id'],'method':method,
        'output':str(Path(output).resolve()),'status':'RESERVED_NO_AUTOMATIC_RETRY',
        'reserved_at_utc':datetime.now(timezone.utc).isoformat()}
    with path.open('x') as file:json.dump(record,file,indent=2)
    return path,record


def writable_sampler_target(controller):
    """Thaw only the disposable target copied from the readonly freeze.

    Pool restores and patches this working file before each generation. copytree
    preserves the freeze's 0444/0555 modes, so the unmodified Pool otherwise
    cannot execute any formal patch. The protected inputs stay readonly.
    """
    target=controller.source/controller.pool['layout_target']
    for directory in [target.parent,*target.parent.parents]:
        if not directory.is_relative_to(controller.source):break
        directory.chmod(stat.S_IMODE(directory.stat().st_mode)|stat.S_IRWXU)
    target.chmod(stat.S_IMODE(target.stat().st_mode)|stat.S_IRUSR|stat.S_IWUSR)
    controller.state['sampler_working_target_writable']=True
    controller.state['frozen_source_changed']=False
    controller.save()


def audit_controls(manifest_path,controls_path,output):
    manifest=read(manifest_path);controls=controls_map(controls_path,require_all=False);rows=[]
    pools={p['pool_id']:p for p in manifest['pools'] if p['source_family'] in FAMILIES}
    for name,control in controls.items():
        if name not in pools:raise ValueError('A control belongs to an undeclared pool: '+name)
        pool=pools[name]
        try:
            proof=audit_telescopic_control(pool,control) if pool['source_family']=='telescopic' else audit_executor_control(pool,control)
            rows.append({'pool_id':name,'qualified':True,'proof':proof})
        except (OSError,ValueError,KeyError,TypeError) as error:
            rows.append({'pool_id':name,'qualified':False,'status':'ADMISSION_UNKNOWN_OR_MISMATCH_NOT_CANDIDATE_FAILURE',
                'error':type(error).__name__+': '+str(error),'control':control})
    report={'scope':'Read-only actual E2 control source/N/bench/raw inspection; no new measurements',
        'controls':rows,'not_supplied':sorted(set(pools)-set(controls)),
        'qualified':sum(r['qualified'] for r in rows),'attempted':len(rows),'new_EDA_calls':0,
        'new_formal_labels':0,'legacy_negative_records_unchanged':True}
    save(output,report);return {'report':str(Path(output).resolve()),'qualified':report['qualified'],'attempted':len(rows),'new_EDA_calls':0}


def qualify(manifest_path,smoke_path,calibration_path):
    manifest=read(manifest_path);counts=matrix(manifest);controls=controls_map(manifest['actual_admission_controls'])
    preflight(manifest);proofs=[]
    for pool in manifest['pools']:
        control=controls[pool['pool_id']]
        if not control.get('mask_gds') or Path(control['mask_gds']).read_bytes() not in [Path(p).read_bytes() for p in pool['development_mask_paths']]:
            raise ValueError('Every known sizing control mask must be excluded from formal selection')
        proofs.append(audit_telescopic_control(pool,control) if pool['source_family']=='telescopic' else audit_executor_control(pool,control))
    from scripts.e2_telescopic_stage_smoke import audit_smoke
    smoke=audit_smoke(smoke_path,manifest)
    ideals=audit_telescopic_ideals(manifest,controls)
    artifact=read(calibration_path)
    original=ROOT/'runs/development/promotion_calibration_20261019T0353Z_nine_validation.json'
    if artifact!=read(original):
        raise ValueError('E2 must use the original predeclared train/validation artifact without refit or widened support')
    from src.promotion_calibration import NominalWorstCalibration
    NominalWorstCalibration(artifact)
    if len(artifact.get('train_rows',[]))!=9 or len(artifact.get('validation_rows',[]))!=9:
        raise ValueError('The original nine train / nine validation actual AC provenance is required')
    registry=read(ROOT/'data/splits/registry.json')
    assignments={r['lineage_id']:r['split'] for r in registry['lineages']}
    for split,key in [('train','train_rows'),('validation','validation_rows')]:
        for row in artifact[key]:
            if row['split']!=split or assignments.get(row['parent_lineage'])!=split or not row['actual_three_corner_AC_complete'] or not row['raw_evidence']:
                raise ValueError('Calibration source provenance conflicts with the shared source registry')
    # No model coefficient, support or residual is fitted or recomputed here.
    return manifest,{'counts':counts,'controls':proofs,'actual_telescopic_transport':smoke,
        'actual_telescopic_nondefault_ideals':ideals,
        'calibration_original_path':str(Path(calibration_path).resolve()),'calibration_refit':False},artifact


def freeze(manifest_path,smoke,calibration,committed_index,output,check_only=False):
    manifest,proof,artifact=qualify(manifest_path,smoke,calibration)
    index=read(committed_index)
    if not re.fullmatch('[0-9a-f]{40}',index['revision']):
        raise ValueError('E2 must bind the actual full committed source revision')
    for name in IMPLEMENTATION:
        if index['files_sha256'].get(name)!=digest(ROOT/name):
            raise ValueError('Live E2 implementation differs from the committed-source index: '+name)
    registry_path=ROOT/'data/splits/registry.json';registry=read(registry_path)
    from src.measurement import split_errors
    if split_errors(registry):raise ValueError('Global registry has conflicting source assignments')
    required={'research_five_t','research_compact_miller','glayout_fvf_ota'}
    if not required.issubset({r['lineage_id'] for r in registry['lineages'] if r['split']=='test'}):
        raise ValueError('An evaluated source overlaps train/validation or is absent')
    if any(r['lineage_id']=='research_telescopic_ota' and r['split']!='test' for r in registry['lineages']):
        raise ValueError('The new telescopic source cannot enter train or calibration')
    if check_only:return {'status':'READY_TO_FREEZE_E2','new_EDA_calls':0,**proof['counts']}
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    frozen=copy.deepcopy(manifest);save(output/'admission_proofs.json',proof)
    save(output/'committed_source_index.json',index)
    save(output/'actual_telescopic_smoke.json',read(smoke))
    artifact.update(formal_calibration_freeze=True,formal_frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        original_predeclared_artifact=str(Path(calibration).resolve()),coefficients_support_and_residuals_changed=False)
    save(output/'promotion_calibration.json',artifact)
    frozen.update(status='FROZEN',formal_execution_allowed=True,freeze_id=output.name,
        frozen_at_utc=datetime.now(timezone.utc).isoformat(),formal_calibration=str(output/'promotion_calibration.json'),
        actual_admission_proofs=str(output/'admission_proofs.json'),frozen_registry=str(output/'registry.json'),
        source_revision=index['revision'],committed_source_index=str(output/'committed_source_index.json'),
        implementation_sha256={name:digest(ROOT/name) for name in IMPLEMENTATION},
        immutable_input_sha256={name:digest(name) for name in input_files(manifest)},
        formal_labels_observed_before_freeze=0)
    frozen.update(blocking_before_freeze=[],calibrated_F3={'admitted':True,
        'frozen_artifact':str(output/'promotion_calibration.json'),'evaluation_outcomes_used_for_fit':False})
    for pool in frozen['pools']:pool.update(source_qualified=True,physical_control_pending=False)
    frozen['immutable_input_sha256'][str(output/'promotion_calibration.json')]=digest(output/'promotion_calibration.json')
    new=copy.deepcopy(registry)
    if not any(r['lineage_id']=='research_telescopic_ota' for r in new['lineages']):
        new['lineages'].append({'lineage_id':'research_telescopic_ota','split':'test','topology_family':'telescopic_cascode_mirror_ota',
            'source':'src/generators/telescopic_ota.py','source_dependencies':['frozen_PDK_MOS_via','src/generators/terminal_access.py'],
            'source_ancestry':'Independent two-column four-tier cascode-mirror assembly; shared primitive/access constraints disclosed',
            'purpose':'E2 evaluation only; never train or promotion calibration','qualification_evidence':str(output/'admission_proofs.json')})
    ids={r['task_id'] for r in new.get('formal_tasks',[])}
    for pool in frozen['pools']:
        task_id='E2_'+pool['pool_id']
        if task_id in ids:raise ValueError('A formal E2 identity already exists; do not repeat or silently replace')
        new.setdefault('formal_tasks',[]).append({'task_id':task_id,'pool_id':pool['pool_id'],'experiment':'E2','split':'test',
            'parent_lineage':{'five_t':'research_five_t','compact_miller':'research_compact_miller','fvf':'glayout_fvf_ota','telescopic':'research_telescopic_ota'}[pool['source_family']],
            'frozen_manifest':str(output/'manifest.json')})
    if split_errors(new):raise ValueError('New E2 registry conflicts with the existing split')
    if read(registry_path)!=registry:raise ValueError('Global registry changed during freeze; root must serialize freezes')
    save(output/'prior_global_registry.json',registry);save(output/'registry.json',new)
    for name in ['admission_proofs.json','actual_telescopic_smoke.json','registry.json','committed_source_index.json']:
        frozen['immutable_input_sha256'][str(output/name)]=digest(output/name)
    save(output/'manifest.json',frozen)
    verify(frozen)
    save(registry_path,new)
    for path in input_files(frozen):Path(path).chmod(0o444)
    for path in sorted(output.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status':'FROZEN','manifest':str(output/'manifest.json'),'new_EDA_calls':0,**proof['counts']}


def dispatch(manifest_path,output,method,workers=1,pool_ids=None,development=False):
    if method not in METHODS:raise ValueError('Unknown frozen E2 method')
    manifest=read(manifest_path)
    if not development:verify(manifest)
    counts=matrix(manifest)
    pools=[p for p in manifest['pools'] if (method=='full_oracle' or p['online_selected']) and (not pool_ids or p['pool_id'] in pool_ids)]
    if pool_ids and set(pool_ids)!={p['pool_id'] for p in pools}:raise ValueError('Unknown or unassigned pool selection')
    if not pools:raise ValueError('No declared pool selected')
    from scripts.e2_execution import Pool
    from scripts.e2_telescopic_adapter import pool_class
    from src.promotion_calibration import NominalWorstCalibration
    calibration=NominalWorstCalibration(read(manifest['formal_calibration'])) if method=='f3_calibrated' else None
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    save(output/'execution.json',{'manifest':str(Path(manifest_path).resolve()),'method':method,'workers':workers,
        'pool_ids':[p['pool_id'] for p in pools],'formal':not development,'oracle_labels_available_to_method':False,'planned_counts':counts})
    def run(pool):
        if not development:verify(manifest)
        cls=pool_class() if pool['source_family']=='telescopic' else Pool
        reservation,record=reserve(manifest,pool,method,output/pool['pool_id']) if not development else (None,None)
        try:
            controller=cls(manifest,pool,output/pool['pool_id'],method,not development,calibration)
            writable_sampler_target(controller)
            result=controller.run()
            if reservation:record.update(status=result['status'],terminal_at_utc=datetime.now(timezone.utc).isoformat());save(reservation,record)
            return result
        except Exception as error:
            if reservation:
                record.update(status='INTERRUPTED_OR_UNKNOWN_NO_AUTOMATIC_RETRY',error=type(error).__name__+': '+str(error))
                save(reservation,record)
            raise
    with ThreadPoolExecutor(max_workers=workers) as executor:results=list(executor.map(run,pools))
    save(output/'summary.json',{'method':method,'formal':not development,'pools':[{
        k:r.get(k) for k in ['pool_id','status','observed_feasible','observed_unknown','best_observed_feasible_ugb_Hz','full_measurements_completed_or_attempted']} for r in results]})


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--old-manifest',type=Path,required=True)
    prep.add_argument('--plan',type=Path,default=ROOT/'configs/experiments/e2_four_source_prospective_v3.json')
    prep.add_argument('--controls',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    fr=sub.add_parser('freeze');fr.add_argument('--manifest',type=Path,required=True);fr.add_argument('--actual-smoke',type=Path,required=True)
    fr.add_argument('--calibration',type=Path,required=True);fr.add_argument('--committed-source-index',type=Path,required=True)
    fr.add_argument('--output',type=Path,required=True);fr.add_argument('--check-only',action='store_true')
    audit=sub.add_parser('audit-controls');audit.add_argument('--manifest',type=Path,required=True)
    audit.add_argument('--controls',type=Path,required=True);audit.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--manifest',type=Path,required=True);run.add_argument('--output',type=Path,required=True)
    run.add_argument('--method',choices=METHODS,required=True);run.add_argument('--workers',type=int,choices=[1,2],default=1)
    run.add_argument('--pool-id',action='append');run.add_argument('--development',action='store_true')
    a=p.parse_args();started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
    if a.command=='prepare':result=prepare(a.old_manifest,a.plan,a.controls,a.output)
    elif a.command=='audit-controls':result=audit_controls(a.manifest,a.controls,a.output)
    elif a.command=='freeze':result=freeze(a.manifest,a.actual_smoke,a.calibration,a.committed_source_index,a.output,a.check_only)
    else:
        try:result=dispatch(a.manifest,a.output,a.method,a.workers,a.pool_id,a.development)
        finally:
            if a.output.is_dir():
                after=resource.getrusage(resource.RUSAGE_SELF);child_after=resource.getrusage(resource.RUSAGE_CHILDREN)
                save(a.output/'controller_resource_usage.json',{'wall_seconds':time.monotonic()-started,
                    'self_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                    'waited_host_tool_child_CPU_seconds':child_after.ru_utime+child_after.ru_stime-children.ru_utime-children.ru_stime,
                    'scope':'Actual host controller and waited patch/mask/docker-client; container SPICE costs separately recorded; overlapping components not added twice'})
    print(json.dumps(result,allow_nan=False),flush=True)


if __name__=='__main__':main()
