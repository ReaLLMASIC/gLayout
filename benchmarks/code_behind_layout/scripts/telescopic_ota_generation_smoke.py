"""One bounded generation smoke of the explicit v5 factory-API correction."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path('/work') if Path('/work/src').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.telescopic_ota_fullflow import bound_design


if __name__=='__main__':
    out=Path.cwd()
    result={'scope':'development_telescopic_v5_generation_only','S0':False,'S1':False,'S2':False,
        'DRC_LVS_PEX_SPICE_calls':0,'status':'RUNNING'}
    def save():
        (out/'generation_smoke.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    save()
    try:
        bound=bound_design(Path(os.environ['PROBE_INPUT']))
        if not bound['engineering_amendment']:
            raise ValueError('This single smoke requires the explicit v5 source snapshot')
        from src.generators.telescopic_ota import build
        import gdstk
        for name in ['telescopic_ota.py','telescopic_ota_reference.py','terminal_access.py']:
            shutil.copyfile(ROOT/'src/generators'/name,out/name)
        gds=build(out)
        library=gdstk.read_gds(gds)
        tops=[c for c in library.cells if c.name=='telescopic_mirror_ota']
        if len(tops)!=1 or tops[0].bounding_box() is None:
            raise ValueError('Generation lacks one nonempty contract top')
        result.update(status='COMPLETE_GENERATION_ONLY',S0=True,gds=str(gds),
            engineering_amendment=bound['engineering_amendment'],
            actual_top=tops[0].name,recursive_polygon_count=len(tops[0].get_polygons()))
    except Exception as error:
        result.update(status='INFRASTRUCTURE_UNKNOWN',error=type(error).__name__+': '+str(error));save();raise
    save();print(json.dumps(result,allow_nan=False),flush=True)
