"""Future post-release, read-only server consumer of the sealed QoR supplement.

Uses the explicit main GPT suite search_index.json and original baseline output.
It calls no model/EDA, changes no original evidence and exports no hidden vector.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from src.e3_qor_supplement import read_backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','declaration','baseline-output','episode-index','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args(); output = args.output.resolve()
    if output.exists() or output.is_relative_to(args.manifest.resolve().parent) or output.is_relative_to(args.baseline_output.resolve()):
        raise ValueError('Write a fresh independent analysis output, never replace evidence or freeze files')
    began = time.monotonic(); cpu = resource.getrusage(resource.RUSAGE_SELF)
    result = read_backend(args.manifest,args.declaration,args.baseline_output,args.episode_index)
    after = resource.getrusage(resource.RUSAGE_SELF)
    result['analysis_cost'] = {'wall_seconds':time.monotonic()-began,
        'process_CPU_seconds':after.ru_utime+after.ru_stime-cpu.ru_utime-cpu.ru_stime,
        'model_calls':0,'EDA_calls':0,'GPU_loads':0}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream: stream.write(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'output':str(output),'hidden_vectors_exported':False}))


if __name__=='__main__': main()
