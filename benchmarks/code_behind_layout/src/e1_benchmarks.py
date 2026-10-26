"""Build the E1 trusted benchmark capsule from explicit, retained source bodies."""
import ast
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def build_trusted(task,point,output):
    output=Path(output)
    if task.get('trusted_template'):
        template=Path(task['trusted_template'])
        for name in task['trusted_template_files']:
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(template/name,target)
        shutil.copyfile(point['reference_file'],output/'reference.spice')
        (output/'contract.json').write_text(json.dumps(point['contract'],indent=2)+'\n')
        return list(task['trusted_template_files'])
    output.mkdir(parents=True);(output/'src').mkdir();(output/'src/__init__.py').write_text('')
    for name in ['physical_drc.py','report_parsers.py','device_intent.py','measurement.py','spice_validation.py','corpus_metrics.py']:
        shutil.copyfile(ROOT/'src'/name,output/'src'/name)
    shutil.copyfile(ROOT/'scripts/e1_trusted_evaluator.py',output/'evaluate.py')
    shutil.copyfile(point['reference_file'],output/'reference.spice')
    (output/'contract.json').write_text(json.dumps(point['contract'],indent=2)+'\n')
    kind=task['target'];meta={'top_cell':task['top_cell'],'ports':task_ports(point),'circuit':kind}
    if kind=='mirror':
        text=(ROOT/'scripts/mirror_task_evaluator.py').read_text();tree=ast.parse(text)
        loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='corner')
        (output/'bench.py').write_text(ast.get_source_segment(text,loop)+'\n')
        (output/'original_bench.py').write_text(text);meta['bench_kind']='mirror'
    elif kind in ('five_t','compact_miller'):
        # Explicit fixed template path; this never searches a latest directory.
        bench=Path(task['source_template']).parent/'trusted_bench/original_retained_bench.py'
        shutil.copyfile(bench,output/'original_bench.py')
        shutil.copyfile(ROOT/'scripts/ota_frozen_bench.py',output/'ota_frozen_bench.py');meta['bench_kind']='ota'
    else:
        from scripts.independent_task_baseline import DEFINITIONS
        definition=DEFINITIONS[kind];path=ROOT/'scripts'/definition['script'];text=path.read_text()
        function=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==definition['function'])
        body=ast.get_source_segment(text,function)
        imports='import json,time,subprocess,threading\nfrom pathlib import Path\nimport numpy as np\nfrom src.spice_validation import validate_analysis\nfrom src.corpus_metrics import frequency_3db\n'
        (output/'bench.py').write_text(imports+'PORTS='+repr(meta['ports'])+'\n'+body+'\n')
        (output/'original_bench.py').write_text(text)
        meta.update(bench_kind='independent',bench_function=definition['function'],bindings=definition.get('bindings',{}),
            metric_bindings={key:{'source':values[0],'unit':values[1],'absolute':values[2]} for key,values in definition['metrics'].items()})
    (output/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
    return sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file())


def task_ports(point):
    lines=Path(point['reference_file']).read_text().splitlines()
    return next(line.split()[2:] for line in lines if line.lower().startswith('.subckt '))
