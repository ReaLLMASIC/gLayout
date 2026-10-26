"""One isolated E3 source-to-GDS-to-physical point, without a model client."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.e3_task_prepare import capsule
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point,source_contents
from src.e1_benchmarks import build_trusted
from scripts.e1_matched_runner import visible_feedback
from src.device_intent import compare_device_intent
from src.report_parsers import magic_drc_report,netgen_lvs_report


def read(path):return json.loads(Path(path).read_text())


def trusted(task,point,output):
    original=read(task['E1_binding']);build_trusted(original,point,output)
    (output/'evaluate.py').rename(output/'original_physical_evaluate.py')
    shutil.copyfile(ROOT/'scripts/e3_trusted_objective.py',output/'evaluate.py')
    return sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())


def inspect(result,point,expected,configuration,fidelity):
    raw=result.get('physical_result') or {};run=Path(result['run_directory'])
    if fidelity=='basic' and raw.get('assessment',{}).get('S1'):
        manifest=read(run/'manifest.json');evidence=run/'evidence'
        if source_contents(run/'source',manifest['source_files'],binary=True)!=expected:raise ValueError('Actual E3 source differs')
        if read(run/'configuration.json')!=configuration or raw['contract']!=point['contract']:raise ValueError('Basic E3 point binding differs')
        provenance=read(evidence/'provenance.json');drc=read(evidence/'drc/metadata.json')
        if provenance['producer']!='trusted_container' or provenance['candidate_container_stopped'] is not True:raise ValueError('Trusted stage boundary not established')
        intent=compare_device_intent((evidence/'extracted_lvs.spice').read_text(),(run/'trusted/reference.spice').read_text())
        if not (drc['completed'] and drc['style']=='drc(full)' and magic_drc_report((evidence/'drc/direct_drc.rpt').read_text())['is_clean']
            and netgen_lvs_report((evidence/'lvs.rpt').read_text())['is_clean'] and intent['is_clean']):raise ValueError('Basic raw reports contradict S1 summary')
        return {'S0':True,'S1':True,'S2':False,'execution_integrity':'valid','failure_class':None,
            'reason':'Actual basic correctness completed; S2 and objective not evaluated'}
    return inspect_point(result,point,expected,configuration)


def evaluate(task_path,configuration_id,output,source=None,fidelity='pex_spice',deadline=None,formal=False):
    """Evaluate exact source/configuration bytes under their independent contract."""
    task_path=Path(task_path);task=read(task_path);output=Path(output)
    if formal and not (task.get('formal_admission') is True and task.get('status')=='FROZEN_E3_TASK'):
        raise ValueError('Formal E3 requires a separately frozen admitted task')
    point=next(p for p in task['configurations'] if p['configuration_id']==configuration_id)
    output.mkdir(parents=True,exist_ok=False)
    if source is None:
        source=output/'source';capsule(task_path,source)
    else:source=Path(source)
    expected=source_contents(source,task['source_files'],binary=True)
    evaluator=output/'trusted';paths=trusted(task,point,evaluator)
    executor=CandidateExecutor(ROOT/'runtime/GLdev',output/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
    result=executor.execute(source_dir=source,source_paths=task['source_files'],entrypoint=task['entrypoint'],
        representation='G2',configuration={'parameters':point['parameters']},trusted_dir=evaluator,trusted_paths=paths,
        fidelity=fidelity,phase='formal_E3' if formal else 'development_E3_physical_integration',
        context={'source_role':'formal_E3_candidate' if formal else 'development_E3_candidate','candidate_id':task['task_id'],
            'initial_state_id':task['task_id'],'parent_lineage':task['parent_lineage'],'configuration_id':configuration_id,
            'reference_id':point['reference_id'],'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'},
        generation_timeout_seconds=240,evaluator_timeout_seconds=720,
        **({'execution_deadline_utc':deadline} if deadline else {}))
    raw=result.get('physical_result') or {}
    checked=None
    try:
        execution=read(Path(result['run_directory'])/'manifest.json')
        if execution['status']=='BUDGET_EXHAUSTED':
            checked={'S0':False,'S1':False,'S2':False,'execution_integrity':'budget_exhausted',
                'failure_class':'budget','reason':'Common absolute UTC search deadline stopped physical execution; no circuit-failure label'}
        else:checked=inspect(result,point,expected,{'parameters':point['parameters']},fidelity)
    except (ValueError,OSError,KeyError,TypeError) as error:
        checked={'execution_integrity':'incomplete','failure_class':'unknown','reason':str(error),'S0':False,'S1':False,'S2':False}
    objective=None;definition=point['contract']['objective']
    if checked['S2']:
        metrics=[raw['observation']['corners'][c]['metrics'][definition['metric']] for c in point['contract']['required_corners']]
        if any(m['unit']!=definition['unit'] for m in metrics):raise ValueError('E3 objective units differ from its contract')
        values=[m['value'] for m in metrics];objective=min(values) if definition['direction']=='max' else max(values)
    record={'task_id':task['task_id'],'configuration_id':configuration_id,'fidelity':fidelity,
        'run_directory':result['run_directory'],'checked':checked,'objective':objective,'objective_definition':definition,
        'physical_feedback':visible_feedback(result),'formal_trial':formal,'created_at_utc':datetime.now(timezone.utc).isoformat()}
    (output/'point.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task',type=Path,required=True)
    p.add_argument('--configuration',default='anchor');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path);p.add_argument('--fidelity',choices=['basic','pex_spice'],default='pex_spice')
    a=p.parse_args();print(json.dumps(evaluate(a.task,a.configuration,a.output,a.source,a.fidelity)),flush=True)
