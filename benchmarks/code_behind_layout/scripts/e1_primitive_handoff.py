#!/usr/bin/env python3
"""Two-size generic MOS/MIM composition control; not a complete target oracle."""
import argparse,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))

GENERATOR='''import argparse,json,math
from pathlib import Path
import gdstk
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
configuration=json.load(open(a.configuration));manifest=json.load(open("/library/manifest.json"))
graph=configuration["graph"];library=gdstk.Library();top=library.new_cell(graph["top_cell"])
for index,device in enumerate(graph["instances"]):
    meta=next(c for c in manifest["cells"] if c["primitive_id"]==device["primitive_id"])
    imported=gdstk.read_gds("/library/"+meta["gds"]);cell=next(c for c in imported.cells if c.name==meta["cell"])
    library.add(cell);origin=(50.*index,0.);top.add(gdstk.Reference(cell,origin))
    for terminal,net in device["nets"].items():
        direction="S" if terminal=="B" else "W"
        row=next(r for r in meta["terminal_access"] if r[:2]==[terminal,direction])
        angle=math.radians(row[5]);x=origin[0]+row[2]-.1*math.cos(angle);y=origin[1]+row[3]-.1*math.sin(angle)
        metal=next(k for k,v in configuration["layers"].items() if k in ["met1","met2","met3","met4","met5"] and v==row[6:8])
        pin=configuration["layers"][metal+"_pin"];label=configuration["layers"][metal+"_label"]
        top.add(gdstk.rectangle((x-.05,y-.05),(x+.05,y+.05),layer=pin[0],datatype=pin[1]))
        top.add(gdstk.Label(net,(x,y),layer=label[0],texttype=label[1]))
library.write_gds(a.output)
'''

EVALUATOR='''import argparse,json,pathlib,subprocess
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report
from src.device_intent import compare_device_intent
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=pathlib.Path(a.output);gds=pathlib.Path(a.gds);top="pcell_handoff"
drc=check_gds(gds,out/"drc",top_name=top);(out/"drc/metadata.json").write_text(json.dumps(drc,indent=2)+"\\n")
tcl="\\n".join(["drc off","gds read {"+str(gds)+"}","load "+top,"select top cell","flatten handoff_lvs","load handoff_lvs","select top cell","extract all","ext2spice lvs","ext2spice -o extracted.spice","puts stdout EXTRACTION_COMPLETE","quit -noprompt",""])
(out/"extract.tcl").write_text(tcl)
with (out/"magic_extract.log").open("w") as log:r=subprocess.run(["magic","-rcfile","/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc","-noconsole","-dnull"],input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
with (out/"netgen.log").open("w") as log:r=subprocess.run(["netgen","-batch","lvs",str(out/"extracted.spice")+" handoff_lvs","/trusted/reference.spice pcell_handoff","/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",str(out/"lvs.rpt")],stdout=log,stderr=subprocess.STDOUT,timeout=120)
lvs=netgen_lvs_report((out/"lvs.rpt").read_text())
intent=compare_device_intent((out/"extracted.spice").read_text(),pathlib.Path("/trusted/reference.spice").read_text())
result={"scope":"development_generic_PCell_composition_interface_control","formal_trials":0,"training_examples":0,"DRC":drc,"LVS":lvs,"device_intent":intent,"interface_control_passed":drc["is_clean"] and lvs["is_clean"] and intent["is_clean"] and r.returncode==0,"S2_established":False}
(out/"validation.json").write_text(json.dumps(result,indent=2)+"\\n");print(json.dumps(result),flush=True)
raise SystemExit(0 if result["interface_control_passed"] else 2)
'''

def prepare():
    from scripts.e1_pcell_prepare import prepare as primitives
    from glayout import sky130
    out=Path.cwd();cases=[]
    for ident,nw,nl,pw,pl,f,cap in [('zA',2.,.5,3.,1.,2,5.),('zB',2.5,.75,4.,1.5,3,6.)]:
        work=out/ident;work.mkdir()
        reference='\n'.join(['.subckt pcell_handoff ND NG NS NB PD PG PS PB CP CN',
            f'XN ND NG NS NB sky130_fd_pr__nfet_01v8 w={nw:g} l={nl:g} m={f}',
            f'XP PD PG PS PB sky130_fd_pr__pfet_01v8 w={pw:g} l={pl:g} m={f}',
            f'XC CP CN sky130_fd_pr__cap_mim_m3_1 w={cap:g} l={cap:g}', '.ends pcell_handoff',''])
        (work/'reference.spice').write_text(reference)
        result=primitives(work/'reference.spice','pcell_handoff','independent_'+ident,work/'library')
        layers={name:sky130.get_glayer(name) for name in sky130.glayers}
        (work/'configuration.json').write_text(json.dumps({'graph':result['graph'],'layers':layers},indent=2)+'\n')
        (work/'layer_aliases.json').write_text(json.dumps(sky130.glayers,indent=2)+'\n')
        cases.append({'id':ident,'cells':result['cells'],'generation_cost':result['generation_cost']})
    (out/'preparation.json').write_text(json.dumps({'cases':cases,'target_assembly_present':False},indent=2)+'\n')
    print(json.dumps({'prepared_generic_cases':[c['id'] for c in cases]}),flush=True)

def execute(prepared):
    from datetime import datetime,timezone
    from src.candidate_executor import CandidateExecutor
    out=ROOT/'runs/development/e1_primitive_controls'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    records=[]
    for ident in ('zA','zB'):
        work=out/ident;source=work/'source';source.mkdir(parents=True);(source/'generator.py').write_text(GENERATOR)
        trusted=work/'trusted';trusted.mkdir();(trusted/'evaluate.py').write_text(EVALUATOR);(trusted/'src').mkdir();(trusted/'src/__init__.py').write_text('')
        for name in ('physical_drc.py','report_parsers.py','device_intent.py'):shutil.copyfile(ROOT/'src'/name,trusted/'src'/name)
        shutil.copyfile(prepared/ident/'reference.spice',trusted/'reference.spice')
        library=prepared/ident/'library';paths=sorted(p.name for p in library.iterdir())
        executor=CandidateExecutor(ROOT/'runtime/GLdev',work/'physical',ROOT/'runtime/magic-8.3.685',timeout=240)
        result=executor.execute(source_dir=source,source_paths=['generator.py'],entrypoint='generator.py',representation='G1',
            configuration=json.loads((prepared/ident/'configuration.json').read_text()),trusted_dir=trusted,
            trusted_paths=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file()),library_dir=library,library_paths=paths,
            fidelity='basic',phase='development_E1_graph_bound_primitive_control',context={'source_role':'transparent_interface_control','configuration_id':ident,'reference_id':'independent_'+ident})
        records.append(result);(out/'controls.json').write_text(json.dumps({'scope':'development_E1_generic_primitive_interface','formal_trials':0,'training_examples':0,'controls':records},indent=2)+'\n')
        print(json.dumps({'configuration_id':ident,**result}),flush=True)
        if not (result.get('physical_result') or {}).get('interface_control_passed'):raise SystemExit(2)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True);m.add_argument('--prepare',action='store_true');m.add_argument('--execute',type=Path);a=p.parse_args()
    if a.prepare:prepare()
    else:execute(a.execute)
