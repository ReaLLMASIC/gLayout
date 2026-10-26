"""Separate E2 capsule binding for the newly qualified telescopic source.

Existing E1/F3 live helpers are read and copied, never modified. The only Pool
specialization replaces its derived nominal capsule with the source's actual
two-deck measurement and correct invocation count.
"""
import ast
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def write(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def variant(source,controls):
    keys={'branch_gap','stack_pitch','join_width','track_stagger'}
    if set(controls)!=keys:raise ValueError('Only the four declared geometric controls may change')
    old='def build(output, sizing=None, *, branch_gap=110., stack_pitch=80., join_width=.8, track_stagger=24.):'
    if source.count(old)!=1:raise ValueError('The frozen independent builder signature changed')
    new='def build(output, sizing=None, *, '+', '.join(name+'='+repr(controls[name]) for name in ['branch_gap','stack_pitch','join_width','track_stagger'])+'):'
    after=source.replace(old,new);ast.parse(after);return after


def point(sizing,sid,reference):
    from src.generators.telescopic_ota_reference import PORTS
    from scripts.telescopic_ota_fullflow import bench_decks
    from src.measurement import validate_contract
    declaration=json.loads((ROOT/'configs/development/telescopic_ota_fullflow.json').read_text())
    _,analyses=bench_decks(Path('/no_execution.spice'),'telescopic_mirror_ota_rc',PORTS,{'VBN_V':1.25,'VBP_V':.45},declaration)
    definitions=[('gain','dB',30,None),('ugb','Hz',1e6,None),('phase_margin','deg',60,180),
        ('power','W',0,.0005),('output_voltage','V',.7,1.2),('saturation_margin','1',1,None),
        ('minimum_channel_voltage','V',.05,None),('minimum_finger_current','A',1e-12,None),
        ('transient_incremental_gain','1',.9,1.1),('transient_plateau_error','1',None,.02),
        ('dc_incremental_gain_min','1',.9,None),('dc_incremental_gain_max','1',None,1.1),
        ('dc_output_min','V',.7,None),('dc_output_max','V',None,1.2),('original_development_predicate','1',1,1)]
    specs=[{'name':name,'unit':unit,**({'min':low} if low is not None else {}),**({'max':high} if high is not None else {})} for name,unit,low,high in definitions]
    cid='telescopic_'+sid;rid='E2_independent_'+cid
    contract={'task_id':'E2_telescopic','configuration_id':cid,'reference_id':rid,'required_corners':['tt','ss','ff'],
        'specifications':specs,'immutable_parameters':sizing,
        'analysis_contracts':{('tran' if name=='transient' else name):row[3] for name,row in analyses.items()},
        'numeric_options':declaration['numerics'],'analysis_timeout_s':180,
        'bench_parameters':{**declaration['application'],'VBN_V':1.25,'VBP_V':.45},
        'objective':{'id':'worst_corner_ugb','metric':'ugb','unit':'Hz','direction':'maximize','corner_aggregation':'worst'}}
    validate_contract(contract)
    return {'configuration_id':cid,'reference_id':rid,'parameters':sizing,'reference_file':str(reference),'contract':contract}


def trusted(point,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);(output/'src').mkdir();(output/'src/__init__.py').write_text('')
    for name in ['physical_drc.py','report_parsers.py','device_intent.py','measurement.py','spice_validation.py','corpus_metrics.py']:
        shutil.copyfile(ROOT/'src'/name,output/'src'/name)
    shutil.copyfile(ROOT/'scripts/e1_trusted_evaluator.py',output/'evaluate.py')
    shutil.copyfile(ROOT/'scripts/e2_telescopic_frozen_bench.py',output/'ota_frozen_bench.py')
    shutil.copyfile(ROOT/'scripts/e2_telescopic_frozen_bench.py',output/'telescopic_nominal_bench.py')
    shutil.copyfile(ROOT/'runtime/telescopic_sizing_qualification_20261019/qualified_default_fullflow_v5.py',output/'original_bench.py')
    shutil.copyfile(ROOT/'configs/development/telescopic_ota_fullflow.json',output/'telescopic_declaration.json')
    shutil.copyfile(point['reference_file'],output/'reference.spice');write(output/'contract.json',point['contract'])
    write(output/'telescopic_bias.json',{'id':'b00','VBN_V':1.25,'VBP_V':.45})
    from src.generators.telescopic_ota_reference import PORTS
    write(output/'meta.json',{'bench_kind':'ota','circuit':'telescopic','top_cell':'telescopic_mirror_ota','ports':PORTS,
        'new_source_lineage':'research_telescopic_cascode_mirror_ota_v5','train_or_calibration_source':False})
    return sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())


def source_pack(primitive_pack,primitive_files,output):
    """Reuse the disclosed primitive closure, remove every prior target module."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    for relative in primitive_files:
        if relative.startswith('src/generators/') or relative in ['component_build.py','generator.py']:continue
        source=Path(primitive_pack)/relative;target=output/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    directory=output/'src/generators'
    directory.mkdir(parents=True);(directory/'__init__.py').write_text('')
    for name in ['telescopic_ota.py','telescopic_ota_reference.py','terminal_access.py']:
        shutil.copyfile(ROOT/'src/generators'/name,directory/name)
    (output/'component_build.py').write_text('''from pathlib import Path
import shutil
from src.generators.telescopic_ota import build as generate
def build(parameters,output):
    result=generate(Path('/tmp/telescopic_generated'),sizing=parameters)
    shutil.copyfile(result,output)
''')
    (output/'generator.py').write_text('''import argparse,json
from pathlib import Path
from component_build import build
p=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()
build(json.loads(Path(a.configuration).read_text())['parameters'],Path(a.output))
''')
    return sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())


def pool_class():
    from scripts.e2_execution import Pool
    class TelescopicPool(Pool):
        def execute(self,source,source_paths,trusted,paths,fidelity,stage,index):
            if stage=='actual_nominal_TT_OP_AC':
                trusted=Path(trusted)
                shutil.copyfile(trusted/'telescopic_nominal_bench.py',trusted/'e2_nominal_bench.py')
                target=trusted/'evaluate.py';text=target.read_text()
                old="'physical_tool_calls':{'DRC':0,'LVS':0,'PEX':0,'SPICE':1}"
                if text.count(old)!=1:raise ValueError('The copied nominal evaluator invocation-count seam changed')
                target.write_text(text.replace(old,"'physical_tool_calls':{'DRC':0,'LVS':0,'PEX':0,'SPICE':2}"))
                (trusted/'telescopic_nominal_capsule_patch.txt').write_text('Derived capsule only: originalTT OP andAC invoke twoSPICE processes; copiedsource-specificmeasurement replaces genericcapture. Sharedhelper files untouched.\n')
                paths=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
            return super().execute(source,source_paths,trusted,paths,fidelity,stage,index)
    return TelescopicPool
