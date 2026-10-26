"""Exactly six new ideal calls and at most two full sizing controls.

The already declared s0/s2 input widths and b00 bias are fixed. No alternate
size, load, bias, limit or timeout is selected using these outcomes.
"""
import argparse
import ast
import copy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path('/work') if Path('/work/src').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.generators.telescopic_ota_reference import DEFAULT,schematic

BASELINE='runs/phase0/phase0_20261019T051625997960Z_telescopic_ota_fullflow'
SOURCES=['src/generators/telescopic_ota.py','src/generators/telescopic_ota_reference.py',
    'src/generators/terminal_access.py','scripts/telescopic_ota_fullflow.py',
    'scripts/telescopic_ota_characterization.py','scripts/telescopic_sizing_qualification.py']


def read(p):return json.loads(Path(p).read_text())
def save(p,v):Path(p).write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def functions(source,names):
    return {n.name:ast.get_source_segment(source,n) for n in ast.parse(source).body
        if isinstance(n,ast.FunctionDef) and n.name in names}


def prepare(output):
    from scripts.telescopic_ota_characterization import analysis_deck
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    proposal=read(ROOT/'configs/experiments/e2_telescopic_draft.json')
    sizes={r['sizing_id']:r['sizing'] for r in proposal['sizings']}
    if sizes['s1']!=DEFAULT or sizes['s0']!={**DEFAULT,'input_width':2.7} or sizes['s2']!={**DEFAULT,'input_width':3.3}:
        raise ValueError('The original three predeclared sizing dictionaries changed')
    original=read(ROOT/'runtime/telescopic_ota_draft/local_v4_portable_probe_20261019/design_manifest.json')
    manifest={key:copy.deepcopy(original[key]) for key in ['design','analysis_contracts','per_corner_wall_limit_s']}
    manifest.update(status='PREPARED_NO_NEW_MEASUREMENTS',scope='development_telescopic_s0_s2_fixed_qualification',
        prepared_at_utc=datetime.now(timezone.utc).isoformat(),sizing_declaration='configs/experiments/e2_telescopic_draft.json',
        fixed_sizings=sizes,measure_sizing_ids=['s0','s2'],fixed_bias={'id':'b00','VBN_V':1.25,'VBP_V':.45},
        original_default_full_control=BASELINE,planned_new_ideal_calls=6,planned_new_full_controls_max=2,
        new_bias_or_load_search=False,formal_trials=0,training_examples=0,controls=[])
    snapshot=output/'source_snapshot'
    for relative in SOURCES:
        p=snapshot/relative;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,p)
    shutil.copyfile(ROOT/'runtime/telescopic_sizing_qualification_20261019/qualified_default_fullflow_v5.py',output/'qualified_default_fullflow_v5.py')
    shutil.copyfile(ROOT/'configs/development/telescopic_ota_fullflow.json',output/'fullflow_declaration.json')
    shutil.copyfile(ROOT/'configs/experiments/e2_telescopic_draft.json',output/'original_sizing_declaration.json')
    for sid in manifest['measure_sizing_ids']:
        directory=output/sid;directory.mkdir();reference=directory/'independent_reference.spice';reference.write_text(schematic(sizes[sid]))
        control={**manifest['fixed_bias'],'id':sid,'bias_control_id':'b00',
            'container_reference_file':'/work/'+str(reference.relative_to(ROOT)),'predeclared_decks':{}}
        decks=directory/'decks';decks.mkdir()
        for corner in ['tt','ss','ff']:
            p=decks/(corner+'.spice');p.write_text(analysis_deck(manifest,control,corner));control['predeclared_decks'][corner]=str(p.relative_to(output))
        manifest['controls'].append(control)
    save(output/'manifest.json',manifest)
    return {'prepared':str(output),'new_ideal_calls':0,'new_full_controls':0,'planned_ideal':6,'planned_full_max':2}


def binding(prepared):
    prepared=Path(prepared);manifest=read(prepared/'manifest.json')
    for relative in SOURCES:
        if (ROOT/relative).read_bytes()!=(prepared/'source_snapshot'/relative).read_bytes():
            raise ValueError('Explicit sized-control source snapshot drifted: '+relative)
    baseline=ROOT/manifest['original_default_full_control'];record=read(baseline/'qualification.json')
    if record['status']!='COMPLETE' or any(record[k] is not True for k in ['S0','S1','S2']):
        raise ValueError('Original actual default full control is not complete S2')
    if any(not row['complete'] or not row['specifications_passed'] for row in record['corners'].values()):
        raise ValueError('Original actual default corner evidence lacks complete specification checks')
    if (baseline/'telescopic_ota.py').read_bytes()!=(ROOT/'src/generators/telescopic_ota.py').read_bytes():
        raise ValueError('The actual qualified generator source differs')
    if (baseline/'independent_reference.spice').read_text()!=schematic(DEFAULT):
        raise ValueError('Original actual default independent N(z) differs')
    original=(prepared/'qualified_default_fullflow_v5.py').read_text()
    if (baseline/'telescopic_ota_fullflow.py').read_text()!=original:
        raise ValueError('Actual qualified default physical source snapshot differs')
    names={'bench_decks','electrical','printed_mos_OP','power'}
    if functions(original,names)!=functions((ROOT/'scripts/telescopic_ota_fullflow.py').read_text(),names):
        raise ValueError('Default qualified electrical bench functions changed')
    declaration=read(prepared/'fullflow_declaration.json')
    if declaration!=read(baseline/'frozen_fullflow_declaration.json'):
        raise ValueError('Original application, limits, analyses or solver changed')
    if declaration!=read(ROOT/'configs/development/telescopic_ota_fullflow.json'):
        raise ValueError('Live fullflow declaration drifted')
    for sid in manifest['measure_sizing_ids']:
        if (prepared/sid/'independent_reference.spice').read_text()!=schematic(manifest['fixed_sizings'][sid]):
            raise ValueError('Independent per-finger sizing intent changed')
    return manifest,declaration


def ideal(prepared,output):
    from scripts.telescopic_ota_characterization import measure
    prepared,output=Path(prepared),Path(output);manifest,_=binding(prepared)
    save(output/'input_preparation_binding.json',{'preparation':str(prepared),'new_declared_sizing_selection':False})
    rows=[]
    for control in manifest['controls']:
        for corner in ['tt','ss','ff']:
            row=measure(output/control['id']/corner,prepared,manifest,control,corner);rows.append(row)
            save(output/'progress.json',{'records':rows,'actual_new_ideal_calls':len(rows)})
    positive=[sid for sid in manifest['measure_sizing_ids'] if all(r['ideal_OP_AC_requirements_passed'] for r in rows if r['control_id']==sid)]
    summary={'scope':manifest['scope'],'all6_corner_calls_complete':len(rows)==6 and all(r['complete'] for r in rows),
        'actual_new_ideal_calls':len(rows),'positive_sizing_ids':positive,'records':rows,
        'actual_ngspice_CPU_seconds':sum(r['actual_ngspice_CPU_seconds'] for r in rows),
        'actual_SPICE_wall_seconds_sum':sum(r['simulation_wall_seconds'] for r in rows),
        'new_GDS_DRC_LVS_PEX_calls':0,'S1_S2_established':False,'formal_trials':0,'training_examples':0}
    save(output/'summary.json',summary);return summary


def full(ideal_run,output,sid):
    from scripts.telescopic_ota_fullflow import physical_control
    ideal_run=Path(ideal_run);prepared=Path(read(ideal_run/'input_preparation_binding.json')['preparation'])
    manifest,declaration=binding(prepared);prior=read(ideal_run/'summary.json')
    measured=[r for r in prior['records'] if r['control_id']==sid]
    if (sid not in manifest['measure_sizing_ids'] or prior['actual_new_ideal_calls']!=6
            or sid not in prior['positive_sizing_ids'] or len(measured)!=3 or not all(r['complete'] for r in measured)):
        raise ValueError('One of the exact six ideal controls lacks a true positive; no physical call allowed')
    control=next(c for c in manifest['controls'] if c['id']==sid)
    sizing=manifest['fixed_sizings'][sid]
    return physical_control(output,sizing,control,declaration,
        identity='research_telescopic_cascode_mirror_ota_v5_'+sid,
        provenance={'scope':'predeclared_nondefault_sizing_control_not_formal','ideal_run':str(ideal_run),
            'preparation':str(prepared),'sizing_id':sid,'original_default_full_control':manifest['original_default_full_control'],
            'full_electrical_bench_functions_and_declaration_unchanged':True,'bias_control_id':'b00'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['prepare','ideal','full'],required=True)
    p.add_argument('--output',type=Path);p.add_argument('--sizing-id',choices=['s0','s2']);a=p.parse_args()
    if a.mode=='prepare':
        if a.output is None:p.error('prepare requires --output')
        result=prepare(a.output)
    else:
        input_path=Path(os.environ['PROBE_INPUT'])
        if a.mode=='full' and a.sizing_id is None:p.error('full requires the explicit predeclared --sizing-id')
        result=ideal(input_path,Path.cwd()) if a.mode=='ideal' else full(input_path,Path.cwd(),a.sizing_id)
    print(json.dumps(result,indent=2,allow_nan=False),flush=True)
