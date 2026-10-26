#!/usr/bin/env python3
"""Actual common-only G2 primitive composition control, with no target assembly."""
import argparse,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.e1_primitive_handoff import GENERATOR,EVALUATOR
from src.candidate_executor import CandidateExecutor

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepared',type=Path,required=True);p.add_argument('--common-pack',type=Path,required=True);a=p.parse_args()
    out=ROOT/'runs/development/E1_G2_composition_controls'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    source=out/'source';shutil.copytree(a.common_pack,source)
    imports='''from glayout import sky130
from gdsfactory.port import Port
from glayout.routing.straight_route import straight_route
from glayout.routing.L_route import L_route
from glayout.routing.c_route import c_route
from glayout.primitives.via_gen import via_stack
# Actual generic route construction; the independent device-control target is
# assembled below only from the readonly graph-bound primitive GDS.
probe_a=Port(name="a",center=(0,0),width=.3,orientation=0,layer=sky130.get_glayer("met2"))
probe_b=Port(name="b",center=(2,0),width=.3,orientation=180,layer=sky130.get_glayer("met2"))
route_probe=straight_route(sky130,probe_a,probe_b,width=.3)
via_probe=via_stack(sky130,glayer1="met2",glayer2="met3",fullbottom=True,fulltop=True)
'''
    (source/'generator.py').write_text(imports+GENERATOR)
    trusted=out/'trusted';trusted.mkdir();(trusted/'src').mkdir();(trusted/'src/__init__.py').write_text('');(trusted/'evaluate.py').write_text(EVALUATOR)
    for name in ['physical_drc.py','report_parsers.py','device_intent.py']:shutil.copyfile(ROOT/'src'/name,trusted/'src'/name)
    shutil.copyfile(a.prepared/'zA/reference.spice',trusted/'reference.spice');library=a.prepared/'zA/library'
    result=CandidateExecutor(ROOT/'runtime/GLdev',out/'physical',ROOT/'runtime/magic-8.3.685',timeout=240).execute(
        source_dir=source,source_paths=sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()),entrypoint='generator.py',representation='G2',
        configuration=json.loads((a.prepared/'zA/configuration.json').read_text()),library_dir=library,library_paths=sorted(p.name for p in library.iterdir()),
        trusted_dir=trusted,trusted_paths=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file()),
        fidelity='basic',phase='development_E1_common_only_G2_composition_control',context={'source_role':'transparent_interface_control','configuration_id':'zA','reference_id':'independent_zA'})
    save={'scope':'development_actual_generic_G2_composition_interface_no_target_assembly','formal_trials':0,'model_calls':0,'result':result,
        'common_source_pack':str(a.common_pack),'frozen_candidate_files':sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file())}
    (out/'summary.json').write_text(json.dumps(save,indent=2)+'\n');print(json.dumps({'summary':str(out/'summary.json'),'result':result}),flush=True)
