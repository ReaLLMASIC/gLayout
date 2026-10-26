"""Prospective validation-only mirror domain; no checkpoint/model selection.

The fixed nine ideal controls use the retained OP/DC bench and independent
per-finger N. Full physical qualification and registry admission are later gates.
"""
import argparse
import ast
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir(): ROOT = Path('/work')
sys.path.insert(0, str(ROOT))
WIDTHS = (2.94, 3., 3.06)
LENGTHS = (.98, 1., 1.02)
PORTS = ['REF', 'OUT', 'GND']
TASK = 'E4_validation_mirror_editing'
SOURCE = 'src/generators/validation_mirror.py'
BENCH = 'scripts/validation_task_evaluator.py'
PDK = '0fe599b2afb6708d281543108caf8310912f54af'


def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text())
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n'); temporary.replace(path)


def reference(width, length, fingers=2):
    """Independent electrical specification; never imports an editable generator."""
    lines = ['* Independent E4 validation-only per-finger NMOS mirror', '.subckt validation_mirror REF OUT GND']
    for branch, drain in [('REF', 'REF'), ('OUT', 'OUT')]:
        for finger in range(fingers):
            lines.append('X%s%d %s REF GND GND sky130_fd_pr__nfet_01v8 w=%g l=%g' %
                (branch, finger, drain, width, length))
    return '\n'.join(lines+['.ends validation_mirror', ''])


def contract(ident):
    return {'task_id': TASK, 'configuration_id': ident, 'reference_id': 'independent_'+ident+'_nf2',
        'required_corners': ['tt', 'ss', 'ff'],
        'specifications': [{'name': 'absolute_current_error', 'unit': '1', 'max': .03},
            {'name': 'output_resistance', 'unit': 'ohm', 'min': 1e6}],
        'analysis_contracts': {'op': {'kind': 'op', 'columns': 4, 'expected_rows': 1},
            'dc': {'kind': 'dc', 'columns': 4, 'start': .1, 'end': 1.7, 'points': 17, 'scale': 'linear'}},
        'objective': {'id': 'actual_GDS_bbox_area', 'metric': 'area', 'unit': 'um2',
            'direction': 'min', 'corner_aggregation': 'worst'}}


def retained_deck_assignment(text):
    found = [node for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'deck' for target in node.targets)]
    if len(found) != 1: raise ValueError('Retained validation bench has no unique deck assignment')
    return ast.get_source_segment(text, found[0])


def adapter(text):
    """Only raw artifact/intent/objective bindings change; original bench retained."""
    changes = [
        ('from src.measurement import assess', 'from src.measurement import assess\nfrom src.device_intent import compare_device_intent'),
        ("artifacts['lvs']={'report':'lvs.rpt'};save()", "intent=compare_device_intent((out/'extracted_lvs.spice').read_text(),pathlib.Path('/trusted/reference.spice').read_text())\nclean=clean and intent['is_clean']\nfor key in ('lvs','devices','ports','intent'):observation['checks'][key]=clean\nartifacts['lvs']={'report':'lvs.rpt','netlist':'extracted_lvs.spice','reference':'reference.spice'}\nartifacts['device_intent']=intent\nsave()"),
        ("'output_resistance':{'value':1/conductance if conductance>0 else None,'unit':'ohm'}}",
         "'output_resistance':{'value':1/conductance if conductance>0 else None,'unit':'ohm'},'area':{'value':area_um2,'unit':'um2'}}"),
        ("observation['checks']['drc']=drc['is_clean'];save()", "observation['checks']['drc']=drc['is_clean'];save()\nlib=gdstk.read_gds(str(gds));target=next(c for c in lib.cells if c.name=='validation_mirror');box=target.bounding_box()\narea_um2=float((box[1][0]-box[0][0])*(box[1][1]-box[0][1]))*(lib.unit/1e-6)**2")]
    original_assignment = retained_deck_assignment(text)
    for before, after in changes:
        if text.count(before) != 1: raise ValueError('Retained adapter binding site changed: '+before)
        text = text.replace(before, after)
    if retained_deck_assignment(text) != original_assignment:
        raise ValueError('The actual original SPICE deck changed')
    compile(text, 'prospective_validation_evaluate.py', 'exec')
    return text


def prepare(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    original = (ROOT/SOURCE).read_text(); bench = (ROOT/BENCH).read_text()
    (output/'original_source.py').write_text(original); (output/'original_bench.py').write_text(bench)
    (output/'deck_assignment.py').write_text(retained_deck_assignment(bench)+'\n')
    evaluator = output/'prospective_evaluate.py'; evaluator.write_text(adapter(bench))
    # This is common primitive code only, never a train/compiler or test assembly.
    from scripts.materialize_e1_packets import generic_pack
    pack = output/'source_pack'; files = generic_pack(pack)
    (pack/'validation_layout.py').write_text(original)
    (pack/'generator.py').write_text('''import argparse,json,shutil,tempfile
from pathlib import Path
from validation_layout import build
p=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()
values=json.load(open(a.configuration))
with tempfile.TemporaryDirectory() as tmp:
    gds=build(tmp,width=values['width'],length=values['length'],fingers=values['fingers'],channel=values['channel'])
    shutil.copyfile(gds,a.output)
''')
    files = sorted(files+['generator.py', 'validation_layout.py'])
    points = []
    # Freeze the whole Cartesian before observing its first ideal result.
    for width in WIDTHS:
        for length in LENGTHS:
            ident = 'w%d_l%d' % (round(width*100), round(length*100))
            folder = output/'points'/ident; folder.mkdir(parents=True)
            gold = folder/'reference.spice'; gold.write_text(reference(width, length))
            cfg = {'width': width, 'length': length, 'fingers': 2, 'channel': 24.}
            trusted = folder/'trusted'; trusted.mkdir()
            shutil.copyfile(evaluator, trusted/'evaluate.py'); shutil.copyfile(gold, trusted/'reference.spice')
            c = contract(ident); save(trusted/'contract.json', c)
            (trusted/'src').mkdir(); (trusted/'src/__init__.py').write_text('')
            for name in ('physical_drc.py', 'report_parsers.py', 'measurement.py', 'spice_validation.py', 'device_intent.py'):
                shutil.copyfile(ROOT/'src'/name, trusted/'src'/name)
            trusted_files = {str(p.relative_to(trusted)): p.read_text() for p in trusted.rglob('*') if p.is_file()}
            point = {'configuration_id': ident, 'role': 'anchor' if cfg['width'] == 3 and cfg['length'] == 1 else 'development',
                'split': 'validation', 'parent_lineage': 'research_validation_mirror', 'pdk_revision': PDK,
                'reference_id': c['reference_id'], 'reference_file': str(gold), 'contract': c, 'parameters': cfg,
                'source_files': files, 'editable_paths': ['validation_layout.py'], 'lineage_editable_paths': ['validation_layout.py'],
                'frozen_source_files': [f for f in files if f != 'validation_layout.py'], 'frozen_source_pack': str(pack),
                'trusted_evaluator_files': trusted_files, 'intent_reference_path': 'reference.spice',
                'qualification': 'PENDING_NEW_WHOLE_DOMAIN_IDEAL_AND_FULL_PHYSICAL_CONTROLS'}
            save(folder/'point.json', point); points.append(point)
    result = {'status': 'DRAFT_E4_VALIDATION_DOMAIN_NOT_ADMITTED', 'created_at_utc': now(),
        'scope': 'One independent validation family only; not broad validation generalization',
        'lineage_id': 'research_validation_mirror', 'source': SOURCE, 'original_bench': BENCH,
        'fixed_Cartesian': {'width': list(WIDTHS), 'length': list(LENGTHS), 'fingers': [2], 'channel': [24.]},
        'points': points, 'source_pack': str(pack), 'source_files': files, 'entrypoint': 'generator.py',
        'editable_paths': ['validation_layout.py'], 'formal_admission': False,
        'training_or_test_sources_used': False, 'new_model_or_physical_calls': 0,
        'old_evidence': 'phase0_20261018T234605309409Z_validation_mirror_probe/default_only',
        'freeze_blockers': ['Nine ideal controls not yet run', 'Nine new full raw-bound physical controls not yet run',
            'Validation editing repair/shortfall signal not yet qualified', 'Prospective validation-only registry/selection plan not frozen']}
    save(output/'domain.json', result)
    return result


def inside():
    import numpy as np
    from src.spice_validation import validate_analysis
    preparation = Path(os.environ['PROBE_INPUT']); domain = read(preparation/'domain.json')
    declaration = (preparation/'deck_assignment.py').read_text(); out = Path.cwd()
    result = {'status': 'RUNNING_IDEAL_CONTROLS', 'scope': 'validation_only_schematic_N_not_S1_S2',
        'preparation': str(preparation), 'declared_configurations': 9, 'required_corners': ['tt', 'ss', 'ff'],
        'points': [], 'model_calls': 0, 'layout_DRC_LVS_PEX_calls': 0, 'ngspice_calls': 0,
        'original_solver_stimuli_and_deck_assignment_preserved': True}
    for point in domain['points']:
        ident = point['configuration_id']; work = out/ident; work.mkdir()
        # Host preparation paths are rebased into the trusted /work mount.
        gold = preparation/'points'/ident/'reference.spice'
        text = gold.read_text(); expected = reference(point['parameters']['width'], point['parameters']['length'])
        if text != expected: raise ValueError('Independent frozen N changed before ideal analysis')
        alias = work/'bench_alias_no_parasitics.spice'
        alias.write_text(text.replace('.subckt validation_mirror ', '.subckt validation_mirror_rc ').replace('.ends validation_mirror\n', '.ends validation_mirror_rc\n'))
        corners = {}; row = {'configuration_id': ident, 'reference': str(gold), 'corners': corners}
        result['points'].append(row)
        for corner in domain['required_corners'] if 'required_corners' in domain else ['tt', 'ss', 'ff']:
            bench = work/corner; bench.mkdir(); (bench/'.spiceinit').write_text('set ngbehavior=hsa\n')
            namespace = {'corner': corner, 'net': alias, 'nodes': ['ref', 'out', '0']}
            exec(compile(declaration, str(preparation/'deck_assignment.py'), 'exec'), namespace)
            (bench/'dc.spice').write_text('\n'.join(namespace['deck']))
            result['ngspice_calls'] += 1; save(out/'ideal_control.json', result)
            with (bench/'console.log').open('w') as log:
                try:
                    run = subprocess.run(['ngspice', '-b', '-o', 'ngspice.log', 'dc.spice'], cwd=bench,
                        stdout=log, stderr=subprocess.STDOUT, timeout=120); code = run.returncode
                except subprocess.TimeoutExpired: code = None
            validations = {name: validate_analysis(bench/(name+'.dat'), bench/'ngspice.log', spec, code)
                for name, spec in point['contract']['analysis_contracts'].items()}
            complete = all(v['complete'] for v in validations.values()); metrics = {}; healthy = False
            if complete:
                op = np.loadtxt(bench/'op.dat', skiprows=1, ndmin=2)[0]; data = np.loadtxt(bench/'dc.dat', skiprows=1, ndmin=2)
                index = int(np.argmin(abs(data[:, 2]-.9))); current = -data[:, 3]
                conductance = float(np.gradient(current, data[:, 2])[index])
                healthy = bool(0 < op[1] < 1.8 and current[index] > 0 and abs(data[index, 2]-.9) < 1e-6)
                metrics = {'absolute_current_error': float(abs(current[index]/1e-5-1)),
                    'output_resistance': 1/conductance if conductance > 0 else None}
            passed = bool(complete and healthy and metrics['absolute_current_error'] <= .03
                and metrics['output_resistance'] is not None and metrics['output_resistance'] >= 1e6)
            corners[corner] = {'complete': complete, 'operating_point_valid': healthy, 'metrics': metrics,
                'meets_original_electrical_specifications': passed, 'analysis_validation': validations}
            save(out/'ideal_control.json', result)
            if not complete:
                result.update(status='PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY', NOT_RUN_configurations=9-len(result['points']))
                save(out/'ideal_control.json', result); return 2
        row['complete'] = True; row['meets_original_electrical_specifications'] = all(c['meets_original_electrical_specifications'] for c in corners.values())
        save(out/'ideal_control.json', result)
    result.update(status='COMPLETE_IDEAL_ONLY_NOT_S1_S2', complete_configurations=9,
        meet_specifications=sum(r['meets_original_electrical_specifications'] for r in result['points']),
        formal_admission=False, S1_or_S2_established=False)
    save(out/'ideal_control.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'points'}), flush=True)
    return 0


def launch(preparation, output):
    from scripts.e1_schematic_parallel import resources
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); deadline = started+1800
    ledger = {'status': 'WAITING_RESOURCE_GATE', 'started_at_utc': now(), 'preparation': str(Path(preparation).resolve()),
        'maximum_total_dispatch_and_execution_seconds': 1800, 'CPU_quota': 2, 'memory_GiB': 8,
        'automatic_retry': False, 'model_calls': 0}; save(output/'dispatch.json', ledger)
    while time.monotonic() < deadline:
        sample = resources(); sample['disk_free_GiB'] = shutil.disk_usage(ROOT).free/2**30
        ledger['last_resource_sample'] = sample; save(output/'dispatch.json', ledger)
        if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_free_GiB'] >= 4: break
        time.sleep(min(10, max(0, deadline-time.monotonic())))
    remaining = int(deadline-time.monotonic())
    if remaining <= 0:
        ledger.update(status='DISPATCH_WINDOW_EXHAUSTED_NOT_RUN', ended_at_utc=now()); save(output/'dispatch.json', ledger); return 2
    argv = [sys.executable, str(ROOT/'scripts/run_eda_probe.py'), '--script', 'e4_validation_mirror_domain.py',
        '--input-dir', str(Path(preparation).resolve()), '--timeout', str(remaining), '--', '--inside']
    with (output/'producer.log').open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        ledger.update(status='DISPATCHED_ONCE', pid=process.pid, argv=argv, dispatched_at_utc=now()); save(output/'dispatch.json', ledger)
        code = process.wait()
    ledger.update(status='PROCESS_RETURNED', returncode=code, ended_at_utc=now(), actual_host_wall_seconds=time.monotonic()-started)
    lines = (output/'producer.log').read_text().splitlines()
    if lines:
        producer = json.loads(lines[0]); ledger['producer'] = producer
        evidence = Path(producer['output'])/'ideal_control.json'
        if evidence.is_file():
            record = read(evidence); ledger['summary'] = {k: v for k, v in record.items() if k != 'points'}
    save(output/'dispatch.json', ledger)
    return code


def qualify_full(preparation, output):
    """One fresh full raw-bound gold control per fixed point, never model data."""
    from scripts.e1_schematic_parallel import resources
    from src.candidate_executor import CandidateExecutor
    from src.training import TrustedPhysicalStore
    preparation = Path(preparation).resolve(); domain = read(preparation/'domain.json')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    if domain['status'] != 'DRAFT_E4_VALIDATION_DOMAIN_NOT_ADMITTED' or len(domain['points']) != 9:
        raise ValueError('Expected the original fixed nine-point validation-only DRAFT')
    # Positive ideal evidence must bind every retained original independent N.
    ideal_link = read(preparation/'ideal_launch.json'); dispatch = read(Path(ideal_link['output'])/'dispatch.json')
    producer = Path(dispatch['producer']['output']); ideal = read(producer/'ideal_control.json')
    if (ideal.get('complete_configurations') != 9 or ideal.get('meet_specifications') != 9
            or ideal.get('ngspice_calls') != 27 or ideal.get('status') != 'COMPLETE_IDEAL_ONLY_NOT_S1_S2'):
        raise ValueError('Whole-domain actual ideal qualification is incomplete or failed')
    for point in domain['points']:
        ident = point['configuration_id']; gold = preparation/'points'/ident/'reference.spice'
        if gold.read_text() != reference(point['parameters']['width'], point['parameters']['length']):
            raise ValueError('Independent reference differs from the predeclared grid')
        alias = (producer/ident/'bench_alias_no_parasitics.spice').read_text()
        expected = gold.read_text().replace('.subckt validation_mirror ', '.subckt validation_mirror_rc ').replace('.ends validation_mirror\n', '.ends validation_mirror_rc\n')
        if alias != expected: raise ValueError('Actual ideal run used a different independent N')
    started = time.monotonic(); deadline = datetime.now(timezone.utc).timestamp()+1800
    result = {'status': 'RUNNING_FULL_GOLD_QUALIFICATION', 'scope': 'validation_only_development_gold_not_model_episode',
        'declared_configurations': 9, 'preparation': str(preparation), 'ideal_raw': str(producer),
        'model_calls': 0, 'formal_admission': False, 'automatic_retry': False, 'points': []}
    save(output/'progress.json', result)
    pack = Path(domain['source_pack']); sources = {'validation_layout.py': (pack/'validation_layout.py').read_text()}
    executor = CandidateExecutor(ROOT/'runtime/GLdev', output/'physical', ROOT/'runtime/magic-8.3.685', timeout=720)
    for point in sorted(domain['points'], key=lambda p: (p['role'] != 'anchor', p['configuration_id'])):
        while datetime.now(timezone.utc).timestamp() < deadline:
            sample = resources(); sample['disk_free_GiB'] = shutil.disk_usage(ROOT).free/2**30
            if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_free_GiB'] >= 4: break
            time.sleep(min(10, max(0, deadline-datetime.now(timezone.utc).timestamp())))
        if datetime.now(timezone.utc).timestamp() >= deadline:
            result['status'] = 'DISPATCH_WINDOW_EXHAUSTED_NOT_RUN'; break
        ident = point['configuration_id']; slot = output/ident; slot.mkdir()
        row = {'configuration_id': ident, 'status': 'RESERVED_ONCE', 'resources': sample}
        result['points'].append(row); save(output/'progress.json', result)
        trusted = preparation/'points'/ident/'trusted'
        execution = executor.execute(source_dir=pack, source_paths=domain['source_files'], entrypoint='generator.py',
            representation='G2', configuration=point['parameters'], trusted_dir=trusted,
            trusted_paths=sorted(point['trusted_evaluator_files']), fidelity='pex_spice',
            phase='development_E4_validation_domain_qualification',
            context={'source_role': 'trusted_evaluator_control', 'evidence_roles': ['trusted_evaluator_control'],
                'configuration_id': ident, 'reference_id': point['reference_id'], 'pdk_revision': PDK},
            generation_timeout_seconds=240, evaluator_timeout_seconds=720,
            execution_deadline_utc=datetime.fromtimestamp(deadline, timezone.utc).isoformat())
        row.update(execution=execution, status='RETURNED')
        try:
            checked = TrustedPhysicalStore._inspect_execution_run(execution['run_directory'], point, sources)
            row['checked'] = checked
            if not checked['S2']:
                row['status'] = 'FULL_GOLD_NOT_S2'; result['status'] = 'PAUSED_GOLD_SHORTFALL_NOT_ADMITTED'; break
        except Exception as error:
            row.update(status='UNKNOWN_NOT_ADMITTED', error=type(error).__name__+': '+str(error))
            result['status'] = 'PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY'; break
        finally:
            save(output/'progress.json', result)
    if len(result['points']) == 9 and all(r.get('checked', {}).get('S2') for r in result['points']):
        result['status'] = 'COMPLETE_NINE_FULL_GOLD_CONTROLS_NOT_YET_TASK_ADMITTED'
    result.update(ended_at_utc=now(), actual_host_wall_seconds=time.monotonic()-started,
        completed_S2_controls=sum(bool(r.get('checked', {}).get('S2')) for r in result['points']),
        NOT_RUN_configurations=9-len(result['points']))
    save(output/'summary.json', result); save(output/'progress.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'points'}), flush=True)
    return 0 if result['completed_S2_controls'] == 9 else 2


def injected_source(original):
    """One prospective active output-source wire open, all device sizes fixed."""
    before = '"GND":([("reference","S"),("reference","B"),("output","S"),("output","B")],low)'
    after = '"GND":([("reference","S"),("reference","B"),("output","B")],low)'
    if original.count(before) != 1: raise ValueError('The original explicit active wire site changed')
    revised = original.replace(before, after)
    compile(revised, 'validation_layout.py', 'exec')
    return revised


def prepare_editing_task(preparation, full_output, output):
    """Only after nine raw full controls; no candidate/model execution here."""
    from src.training import TrustedPhysicalStore
    preparation = Path(preparation).resolve(); domain = read(preparation/'domain.json')
    full_output = Path(full_output).resolve(); full = read(full_output/'summary.json')
    if (full.get('status') != 'COMPLETE_NINE_FULL_GOLD_CONTROLS_NOT_YET_TASK_ADMITTED'
            or full.get('completed_S2_controls') != 9 or len(full['points']) != 9
            or Path(full['preparation']).resolve() != preparation):
        raise ValueError('All nine actual gold controls must qualify before preparing a useful editing state')
    gold_pack = Path(domain['source_pack']); gold_source = (gold_pack/'validation_layout.py').read_text()
    original_sources = {'validation_layout.py': gold_source}
    controls = {row['configuration_id']: row['execution']['run_directory'] for row in full['points']}
    if set(controls) != {p['configuration_id'] for p in domain['points']}: raise ValueError('Gold controls dropped a fixed point')
    for point in domain['points']:
        checked = TrustedPhysicalStore._inspect_execution_run(controls[point['configuration_id']], point, original_sources)
        if not checked['S2']: raise ValueError('A complete fixed gold domain no longer rebinds')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    pack = output/'initial_source_pack'; shutil.copytree(gold_pack, pack)
    for folder in [pack]+[p for p in pack.rglob('*') if p.is_dir()]: folder.chmod(folder.stat().st_mode | 0o700)
    target = pack/'validation_layout.py'; target.chmod(0o644); target.write_text(injected_source(gold_source))
    points = []
    for original in domain['points']:
        point = {**original, 'gold_control': {'run_directory': controls[original['configuration_id']]}}
        save(output/'points'/point['configuration_id']/'point.json', point); points.append(point)
    result = {'status': 'DRAFT_E4_VALIDATION_EDITING_TASK_NOT_ADMITTED', 'task_id': TASK,
        'split': 'validation', 'parent_lineage': domain['lineage_id'], 'source_group': 'independent_validation_mirror',
        'origin': 'prospective_injected_active_output_source_wire_open', 'production_natural_bug_claimed': False,
        'created_at_utc': now(), 'configuration_ids': [p['configuration_id'] for p in points],
        'source_pack': str(pack), 'source_files': domain['source_files'], 'entrypoint': domain['entrypoint'],
        'editable_paths': domain['editable_paths'], 'qualification_sources': original_sources,
        'qualification_runs': controls, 'points': points, 'formal_admission': False,
        'private_gold_witness_source_pack': str(gold_pack), 'full_gold_control_directory': str(full_output),
        'scope': 'One validation family/task; nine configurations are not independent source families',
        'freeze_blockers': ['Actual initial connectivity failure not yet measured',
            'Complete visible packet/tokenizer preflight and prospective combined registry/plan not yet frozen'],
        'new_model_or_EDA_calls': 0}
    save(output/'task.json', result)
    return result


def qualify_initial(task_directory, output):
    """One bounded negative connectivity control against its real gold witness."""
    from scripts.e1_schematic_parallel import resources
    from src.candidate_executor import CandidateExecutor
    from src.training import TrustedPhysicalStore
    task_directory = Path(task_directory).resolve(); task = read(task_directory/'task.json')
    if task['status'] != 'DRAFT_E4_VALIDATION_EDITING_TASK_NOT_ADMITTED':
        raise ValueError('Expected the prospective validation-only injected task')
    source = Path(task['source_pack']); gold_pack = Path(task['private_gold_witness_source_pack'])
    current = (source/'validation_layout.py').read_text()
    if current != injected_source((gold_pack/'validation_layout.py').read_text()):
        raise ValueError('The prospective active-wire-open initial source changed')
    point, = [p for p in task['points'] if p['role'] == 'anchor']
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); deadline = datetime.now(timezone.utc).timestamp()+1800
    result = {'status': 'WAITING_RESOURCE_GATE', 'task_id': TASK, 'started_at_utc': now(),
        'maximum_attempts': 1, 'automatic_retry': False, 'model_calls': 0, 'formal_admission': False,
        'task_directory': str(task_directory)}
    save(output/'control.json', result)
    while datetime.now(timezone.utc).timestamp() < deadline:
        sample = resources(); sample['disk_free_GiB'] = shutil.disk_usage(ROOT).free/2**30
        if sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_free_GiB'] >= 4: break
        time.sleep(min(10, max(0, deadline-datetime.now(timezone.utc).timestamp())))
    if datetime.now(timezone.utc).timestamp() >= deadline:
        result.update(status='DISPATCH_WINDOW_EXHAUSTED_NOT_RUN', ended_at_utc=now())
        save(output/'control.json', result); return 2
    trusted = output/'trusted'; trusted.mkdir()
    for name, content in point['trusted_evaluator_files'].items():
        target = trusted/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
    result.update(status='RESERVED_ONCE', resources=sample); save(output/'control.json', result)
    executor = CandidateExecutor(ROOT/'runtime/GLdev', output/'physical', ROOT/'runtime/magic-8.3.685', timeout=720)
    execution = executor.execute(source_dir=source, source_paths=task['source_files'], entrypoint=task['entrypoint'],
        representation='G2', configuration=point['parameters'], trusted_dir=trusted,
        trusted_paths=sorted(point['trusted_evaluator_files']), fidelity='pex_spice',
        phase='development_E4_validation_initial_control', context={'source_role': 'validation_injected_initial_control',
            'configuration_id': point['configuration_id'], 'reference_id': point['reference_id'], 'pdk_revision': PDK},
        generation_timeout_seconds=240, evaluator_timeout_seconds=720,
        execution_deadline_utc=datetime.fromtimestamp(deadline, timezone.utc).isoformat())
    result['execution'] = execution; save(output/'control.json', result)
    try:
        checked = TrustedPhysicalStore._inspect_execution_run(execution['run_directory'], point, {'validation_layout.py': current})
        result['checked'] = checked
        raw = read(Path(execution['run_directory'])/'evidence/validation.json')
        checks = raw['observation']['checks']
        established = checked['S0'] and not checked['S1'] and checks['drc'] is True and checks['lvs'] is False
        result['status'] = 'COMPLETE_INITIAL_CONNECTIVITY_FAILURE_AND_GOLD_WITNESS' if established else 'NO_DECLARED_EDITING_SIGNAL_NOT_ADMITTED'
        if established:
            signal = {'configuration_id': point['configuration_id'], 'actual_initial_failure_verified': True,
                'feasible_repair_verified': True, 'initial_run_directory': execution['run_directory'],
                'witness_run_directory': point['gold_control']['run_directory'],
                'initial_source': {'validation_layout.py': current}, 'witness_source': task['qualification_sources'],
                'origin': task['origin'], 'actual_control': str(output/'control.json'), 'model_calls': 0}
            save(task_directory/'useful_editing_signal.json', signal)
            task['useful_editing_signal_evidence'] = str(task_directory/'useful_editing_signal.json')
            task['freeze_blockers'] = ['Complete visible packet/tokenizer preflight and prospective combined registry/plan not yet frozen']
            save(task_directory/'task.json', task)
    except Exception as error:
        result.update(status='PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY', error=type(error).__name__+': '+str(error))
    result.update(ended_at_utc=now(), actual_host_wall_seconds=time.monotonic()-started)
    save(output/'control.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('checked', 'execution')}), flush=True)
    return 0 if result['status'] == 'COMPLETE_INITIAL_CONNECTIVITY_FAILURE_AND_GOLD_WITNESS' else 2


def prepare_packet(task_directory, budget_path, tokenizer_snapshot):
    """Complete source and effective PDK data; pinned CPU tokenizer only."""
    from src.e4_validation import validate_budget
    from src.e4_methods import REVISION
    from src.policy_state import current_state_request
    from src.local_model_adapter import decision_prompt
    from transformers import AutoTokenizer
    task_directory = Path(task_directory).resolve(); task = read(task_directory/'task.json')
    budget = read(budget_path); validate_budget(budget)
    snapshot = Path(tokenizer_snapshot).resolve()
    if snapshot.name != REVISION: raise ValueError('Use the actual pinned tokenizer revision without truncation')
    pack = Path(task['source_pack'])
    # Keep the working physical dependency environment and tokenizer environment
    # separate. This CPU-only child reads PDK data; it calls no PCell/generator.
    pdk_path = task_directory/'public_pdk.json'
    code = '''import sys,json,pathlib,os
sys.dont_write_bytecode=True
pack=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(pack))
os.environ['PDK_ROOT']='/foss/pdks'
import glayout
assert pathlib.Path(glayout.__file__).resolve().is_relative_to(pack)
from glayout import sky130
rules={a:{b:value for b,value in row.items() if value} for a,row in sky130.grules.items() if any(row.values())}
pathlib.Path(sys.argv[2]).write_text(json.dumps({'layers':sky130.glayers,'rules':rules}))
'''
    subprocess.run([str(ROOT/'runtime/GLdev/bin/python'), '-c', code, str(pack), str(pdk_path)], check=True)
    pdk = read(pdk_path)
    source = {name: (pack/name).read_text() for name in task['editable_paths']}
    public_contract = {key: task['points'][0]['contract'][key] for key in
        ('task_id', 'required_corners', 'specifications', 'analysis_contracts', 'objective')}
    packet = {'task_id': TASK,
        'goal': 'Repair this complete layout generator so the immutable intended circuit passes every declared physical and electrical constraint across the visible sizing family.',
        'contract': public_contract, 'allowed_paths': task['editable_paths'], 'visible_sources': source,
        'documents': {'action_gateway': {'read_source_paths': task['editable_paths'],
                'runtime_only_files': 'The generator wrapper, common glayout library and configuration files are candidate runtime inputs; read_source serves only the complete editable module listed above.'},
            'patch_format': 'Return the ordinary ACTION_JSON. propose_patch.patch is an executable unified diff with exact --- a/validation_layout.py, +++ b/validation_layout.py, accurate hunk counts and a final newline. No source_text or markdown.',
            'source_edit_policy': 'Edit layout/planning code only. Preserve the build API and immutable independent device model, per-finger W/L/finger counts, declared external ports, reference wiring and bench. Read-only wrappers/libraries/specifications cannot be edited.',
            'circuit': 'REF OUT GND. Reference drain/gate and output gate connect to REF; output drain connects to OUT; all source/body terminals connect to GND. Two identical NMOS devices, each two parallel fingers, no dummy; four extracted sky130_fd_pr__nfet_01v8 total. W/L are immutable per configuration.',
            'visible_parameters': {p['configuration_id']: p['parameters'] for p in task['points']},
            'bench': '1.8V supply; IREF supply to REF10uA; OUT clamp .9V; TT/SS/FF at27C; OP and17-point .1..1.7V DC sweep. Steady-DC current error <=3%, output resistance >=1Mohm. Full DRC/LVS/per-finger terminal graph/positiveRC and all analyses establish S2.',
            'API': 'The complete source imports gdstk, gdsfactory Component, glayout.sky130, nmos and via_stack. Common primitive/runtime modules are frozen. Current complete source includes the actual port names and full assembly API.',
            'PDK': pdk, 'units': 'Geometry in um on .005um construction grid. Top cell validation_mirror; exported ports REF/OUT/GND.',
            'feedback': 'Every queried configuration returns verification states and all corner measurements/units in lossless table form; complete parser/raw logs remain in the trusted evidence store.',
            'output_budget': 'Complete ordinary ACTION_JSON including final EOS <=1024tokens; full current source/contract/history plus1024reserve <=16384. Sources and measured feedback are not truncated.'},
        'visible_configurations': task['configuration_ids'], 'budget': budget}
    request = current_state_request(packet, [], source)
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    encoded = tokenizer.apply_chat_template([{'role': 'user', 'content': decision_prompt(request)}], tokenize=True, add_generation_prompt=True)
    tokens = len(encoded['input_ids'] if hasattr(encoded, 'keys') else encoded)
    preflight = {'tokenizer_snapshot': str(snapshot), 'input_tokens': tokens, 'output_reserve': 1024,
        'maximum_context_tokens': 16384, 'complete_source_and_contract': True, 'initial_fit': tokens+1024 <= 16384,
        'model_or_GPU_calls': 0, 'EDA_calls': 0, 'scope': 'Initial exact ordinary payload only; actual later history is checked on every decision'}
    save(task_directory/'packet.json', packet); save(task_directory/'context_preflight.json', preflight)
    task.update(packet=str(task_directory/'packet.json'), actual_context_preflight=str(task_directory/'context_preflight.json'))
    save(task_directory/'task.json', task)
    if not preflight['initial_fit']: raise ValueError('Whole source/PDK/contract does not fit; no source truncation permitted')
    return preflight


def freeze_task(task_directory, output):
    """Snapshot an actually qualified task after its budget/packet is approved.

    This does not edit the assignment registry or perform checkpoint selection.
    """
    from src.training import TrustedPhysicalStore
    from src.candidate_executor import copy_declared_files
    from src.e4_methods import REVISION
    from src.local_model_adapter import decision_prompt
    from src.policy_state import current_state_request
    from transformers import AutoTokenizer
    task_directory = Path(task_directory).resolve(); task = read(task_directory/'task.json')
    if task['status'] != 'DRAFT_E4_VALIDATION_EDITING_TASK_NOT_ADMITTED': raise ValueError('Expected the qualified prospective DRAFT')
    sources = {name: (Path(task['source_pack'])/name).read_text() for name in task['editable_paths']}
    gold = task['qualification_sources']; points = {p['configuration_id']: p for p in task['points']}
    if len(points) != 9 or set(points) != set(task['configuration_ids']): raise ValueError('The original fixed nine-point task changed')
    for ident, point in points.items():
        checked = TrustedPhysicalStore._inspect_execution_run(task['qualification_runs'][ident], point, gold)
        if not checked['S2']: raise ValueError('Whole independent gold domain is not actually S2')
    signal = read(task['useful_editing_signal_evidence']); anchor = points[signal['configuration_id']]
    if signal['initial_source'] != sources or signal['witness_source'] != gold:
        raise ValueError('Current initial source or gold witness differs from its actual control')
    before = TrustedPhysicalStore._inspect_execution_run(signal['initial_run_directory'], anchor, sources)
    after = TrustedPhysicalStore._inspect_execution_run(signal['witness_run_directory'], anchor, gold)
    checks = read(Path(signal['initial_run_directory'])/'evidence/validation.json')['observation']['checks']
    if not (before['S0'] and not before['S1'] and checks['drc'] and not checks['lvs'] and after['S2']):
        raise ValueError('The prospective active-wire-open repair signal is not established')
    packet = read(task['packet']); preflight = read(task['actual_context_preflight'])
    if packet['visible_sources'] != sources or packet['visible_configurations'] != task['configuration_ids']:
        raise ValueError('Whole editable source or visible family differs from the actual packet')
    snapshot = Path(preflight['tokenizer_snapshot'])
    if snapshot.name != REVISION: raise ValueError('Pinned tokenizer required')
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    encoded = tokenizer.apply_chat_template([{'role': 'user', 'content': decision_prompt(current_state_request(packet, [], sources))}], tokenize=True, add_generation_prompt=True)
    count = len(encoded['input_ids'] if hasattr(encoded, 'keys') else encoded)
    if count != preflight['input_tokens'] or count+1024 > 16384: raise ValueError('Exact initial capacity changed')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    (output/'source_pack').mkdir(); (output/'gold_source_pack').mkdir()
    copy_declared_files(task['source_pack'], task['source_files'], output/'source_pack')
    copy_declared_files(task['private_gold_witness_source_pack'], task['source_files'], output/'gold_source_pack')
    for point in points.values():
        point['frozen_source_pack'] = str(output/'gold_source_pack')
        reference_file = output/'references'/(point['configuration_id']+'.spice'); reference_file.parent.mkdir(exist_ok=True)
        reference_file.write_text(point['trusted_evaluator_files']['reference.spice']); point['reference_file'] = str(reference_file)
        save(output/'points'/point['configuration_id']/'point.json', point)
    save(output/'packet.json', packet); save(output/'context_preflight.json', preflight)
    save(output/'useful_editing_signal.json', signal)
    task.update(status='FROZEN_E4_VALIDATION_TASK', formal_admission=True, frozen_at_utc=now(),
        source_pack=str(output/'source_pack'), private_gold_witness_source_pack=str(output/'gold_source_pack'),
        packet=str(output/'packet.json'), actual_context_preflight=str(output/'context_preflight.json'),
        useful_editing_signal_evidence=str(output/'useful_editing_signal.json'), points=list(points.values()),
        original_draft_task_file=str(task_directory/'task.json'), freeze_blockers=[],
        checkpoint_model_or_EDA_calls_during_freeze=0)
    save(output/'task.json', task); save(output/'task_index.json', [{'task_file': str(output/'task.json')}])
    save(output/'validation_configurations.json', list(points.values()))
    for target in output.rglob('*'):
        target.chmod(0o555 if target.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': task['status'], 'task_file': str(output/'task.json'), 'configuration_count': 9,
        'global_registry_modified': False, 'checkpoint_model_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--prepare', action='store_true'); choice.add_argument('--inside', action='store_true'); choice.add_argument('--launch', action='store_true'); choice.add_argument('--qualify-full', action='store_true'); choice.add_argument('--prepare-editing-task', action='store_true'); choice.add_argument('--qualify-initial', action='store_true'); choice.add_argument('--prepare-packet', action='store_true'); choice.add_argument('--freeze-task', action='store_true')
    parser.add_argument('--output', type=Path); parser.add_argument('--preparation', type=Path); parser.add_argument('--full-output', type=Path)
    parser.add_argument('--budget', type=Path); parser.add_argument('--tokenizer-snapshot', type=Path)
    args = parser.parse_args()
    if args.inside: raise SystemExit(inside())
    if args.prepare_packet:
        if args.preparation is None or args.budget is None or args.tokenizer_snapshot is None:
            parser.error('--prepare-packet requires --preparation, --budget and --tokenizer-snapshot')
        print(json.dumps(prepare_packet(args.preparation, args.budget, args.tokenizer_snapshot))); raise SystemExit(0)
    if args.output is None: parser.error('Fresh --output is required')
    if args.prepare:
        value = prepare(args.output); print(json.dumps({'status': value['status'], 'domain': str(args.output/'domain.json'), 'points': len(value['points'])}))
    else:
        if args.preparation is None: parser.error('--launch requires --preparation')
        if args.freeze_task:
            print(json.dumps(freeze_task(args.preparation, args.output))); raise SystemExit(0)
        elif args.qualify_initial: raise SystemExit(qualify_initial(args.preparation, args.output))
        elif args.prepare_editing_task:
            if args.full_output is None: parser.error('--prepare-editing-task requires --full-output')
            value = prepare_editing_task(args.preparation, args.full_output, args.output)
            print(json.dumps({'status': value['status'], 'task_file': str(args.output/'task.json'), 'new_model_or_EDA_calls': 0}))
        else: raise SystemExit(qualify_full(args.preparation, args.output) if args.qualify_full else launch(args.preparation, args.output))
