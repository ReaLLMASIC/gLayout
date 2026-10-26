#!/usr/bin/env python3
"""Derived readonly final intent audit of saved two-z composition controls."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))

def audit(controls):
    import networkx
    from src.device_intent import compare_device_intent
    controls=Path(controls)
    if not controls.is_absolute():controls=ROOT/controls
    if str(controls).startswith('/srv/code-behind-layout/'):
        controls=ROOT/controls.relative_to('/srv/code-behind-layout')
    began=time.monotonic();rows=[]
    for name in ['zA','zB']:
        runs=list((controls/name/'physical').glob('executor_*'))
        if len(runs)!=1:raise ValueError('Expected unique saved control')
        run=runs[0];lvs=run/'evidence/extracted.spice';reference=run/'trusted/reference.spice'
        result=compare_device_intent(lvs.read_text(),reference.read_text())
        rows.append({'configuration':name,'extracted_LVS':str(lvs),'reference':str(reference),'intent':result})
    output={'scope':'development_derived_readonly_saved_LVS_intent_audit','new_physical_calls':0,'new_model_calls':0,
        'networkx_version':networkx.__version__,'all_clean':all(r['intent']['is_clean'] for r in rows),'controls':rows,'wall_seconds':time.monotonic()-began}
    (Path.cwd()/'intent_audit.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output),flush=True)
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--controls',type=Path,required=True);a=p.parse_args()
    raise SystemExit(0 if audit(a.controls)['all_clean'] else 2)
