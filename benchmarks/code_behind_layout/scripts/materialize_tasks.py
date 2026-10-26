#!/usr/bin/env python3
"""Materialize four real, unfrozen component tasks on the execution host.

This does not launch a policy or freeze a split. The private 25-point tables and
references are written only under the remote runtime directory. Export public/
only; never copy the private directory back to a policy host.
"""
import argparse
import ast
from datetime import datetime,timezone
import importlib
import itertools
import json
import os
from pathlib import Path
import random
import resource
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.measurement import audit_reference_ports,validate_contract

TARGETS={
    "mirror": {"lineage":"glayout_mirror","module":"cells.elementary.current_mirror.current_mirror","function":"current_mirror",
        "top":"mirror4","ports":["VREF","VOUT","VSS","B"],"bindings":{"VREF":"fet_A_drain_N","VOUT":"fet_B_drain_N","VSS":"fet_A_source_W","B":"welltie_N_top_met_N"},
        "source_record":"mirror_domain_development","anchor":{"width":1.88,"length":3.,"numcols":2,"device":"pfet"},
        "objective":{"id":"mirror_error_min","metric":"absolute_current_error","unit":"1","direction":"min","corner_aggregation":"worst"},
        "specifications":[{"name":"absolute_current_error","unit":"1","max":.05},{"name":"output_resistance","unit":"ohm","min":1e6}]},
    "pair": {"lineage":"glayout_pair","module":"cells.elementary.diff_pair.diff_pair","function":"diff_pair",
        "top":"pair6","ports":["VP","VN","VDD1","VDD2","VTAIL","B"],"bindings":{"VP":"br_multiplier_0_gate_S","VN":"bl_multiplier_0_gate_S","VDD1":"tl_multiplier_0_drain_N","VDD2":"tr_multiplier_0_drain_N","VTAIL":"bl_multiplier_0_source_S","B":"tap_N_top_met_S"},
        "source_record":"pair_three_size_domain_development","anchor":{"width":1.,"length":.5,"fingers":2},
        "objective":{"id":"pair_bandwidth_max","metric":"loaded_bandwidth","unit":"Hz","direction":"max","corner_aggregation":"worst"},
        "specifications":[{"name":"absolute_branch_imbalance","unit":"1","max":.001},{"name":"loaded_differential_gain","unit":"1","min":1.},{"name":"differential_transconductance","unit":"S","min":1e-4}]},
    "tg": {"lineage":"glayout_tg","module":"cells.elementary.transmission_gate.transmission_gate","function":"transmission_gate",
        "top":"tg6","ports":["VIN","VSS","VOUT","VCC","VGP","VGN"],"bindings":{"VIN":"N_multiplier_0_source_E","VSS":"N_tie_N_top_met_N","VOUT":"P_multiplier_0_drain_W","VCC":"P_tie_S_top_met_S","VGP":"P_multiplier_0_gate_E","VGN":"N_multiplier_0_gate_E"},
        "source_record":"tg_three_size_domain_development","anchor":{"width":2.,"length":.5},
        "objective":{"id":"tg_resistance_min","metric":"on_resistance_at_0p9V","unit":"ohm","direction":"min","corner_aggregation":"worst"},
        "specifications":[{"name":"absolute_off_current","unit":"A","max":1e-9},{"name":"high_settled_error","unit":"V","max":.3},{"name":"low_settled_error","unit":"V","max":.01}]},
    "follower": {"lineage":"glayout_fvf","module":"cells.elementary.FVF.fvf","function":"flipped_voltage_follower",
        "top":"follower4","ports":["VIN","VBULK","VOUT","IB"],"bindings":{"VIN":"A_multiplier_0_gate_N","VBULK":"B_tie_N_top_met_N","VOUT":"A_source_bottom_met_N","IB":"A_drain_bottom_met_N"},
        "source_record":"follower_two_size_domain_development","anchor":{"width":4.15,"length":2.},
        "objective":{"id":"follower_bandwidth_max","metric":"bandwidth","unit":"Hz","direction":"max","corner_aggregation":"worst"},
        "specifications":[{"name":"voltage_gain_10Hz","unit":"1","min":.8,"max":1.05},{"name":"output_impedance_10Hz","unit":"ohm","max":100.}]}}


def sizing_domain(kind):
    if kind=="mirror":return [{"width":w,"length":l,"numcols":2,"device":"pfet"} for w,l in itertools.product([1.,1.5,1.88,2.5,3.],[.5,1.,1.5,2.,3.])]
    if kind=="pair":return [{"width":w,"length":l,"fingers":2} for w,l in itertools.product([1.,1.5,2.,2.5,3.],[.5,.6,.75,.9,1.])]
    if kind=="tg":return [{"width":1.+i*.125,"length":.5} for i in range(25)]
    return [{"width":round(3.+i*.05,3),"length":2.} for i in range(23)]+[{"width":4.125,"length":2.},{"width":4.15,"length":2.}]


def reference(kind,p):
    t=TARGETS[kind];w=p["width"];l=p["length"]
    n="sky130_fd_pr__nfet_01v8";f="sky130_fd_pr__pfet_01v8"
    if kind=="mirror":
        rows=[f"XREF VREF VREF VSS B {f} w={w:g} l={l:g} m={p['numcols']}",f"XOUT VOUT VREF VSS B {f} w={w:g} l={l:g} m={p['numcols']}",f"XDUMMY B B B B {f} w={w:g} l={l:g} m=2"]
    elif kind=="pair":
        rows=[f"XPLUS VDD1 VP VTAIL B {n} w={w:g} l={l:g} m={2*p['fingers']}",f"XMINUS VDD2 VN VTAIL B {n} w={w:g} l={l:g} m={2*p['fingers']}",f"XDUMMY B B B B {n} w={w:g} l={l:g} m=4"]
    elif kind=="tg":
        rows=[f"XNMOS VOUT VGN VIN VSS {n} w={w:g} l={l:g}",f"XPMOS VOUT VGP VIN VCC {f} w={w:g} l={l:g}",f"XNDUMMY VSS VSS VSS VSS {n} w={w:g} l={l:g} m=2",f"XPDUMMY VCC VCC VCC VCC {f} w={w:g} l={l:g} m=2"]
    else:
        rows=[f"XINPUT IB VIN VOUT VBULK {n} w={w:g} l={l:g} m=2",f"XSHUNT VOUT IB VBULK VBULK {n} w={w:g} l={l:g} m=2",f"XDUMMY VBULK VBULK VBULK VBULK {n} w={w:g} l={l:g} m=4"]
    result="\n".join(["* Independent intended circuit; physical per-finger width retained", ".subckt "+t["top"]+" "+" ".join(t["ports"]),*rows,".ends "+t["top"],""])
    if audit_reference_ports(result,t["top"],t["ports"])["status"]!="PASS":raise ValueError("Disconnected declared reference port")
    return result


GENERATOR='''import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from component_build import build
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
build(json.loads(Path(a.configuration).read_text()),Path(a.output))
'''

BUILD='''import importlib
import json
from pathlib import Path
import gdstk
import numpy as np
from gdsfactory.components import rectangle
from glayout import sky130
from glayout.util.comp_utils import align_comp_to_port
TARGET={target!r}
KIND={kind!r}
def build(p,output):
    fn=getattr(importlib.import_module("glayout."+TARGET["module"]),TARGET["function"])
    w=p["width"];l=p["length"]
    if KIND=="mirror":c=fn(sky130,width=w,length=l,numcols=p["numcols"],device="pfet",fingers=1,with_labels=False).copy()
    elif KIND=="pair":c=fn(sky130,width=w,length=l,fingers=p["fingers"]).copy()
    elif KIND=="tg":c=fn(sky130,width=(w,w),length=(l,l),fingers=(1,1),multipliers=(1,1),with_labels=False).copy()
    else:c=fn(sky130,width=(w,w),length=(l,l),fingers=(2,2),multipliers=(1,1),with_dnwell=False,with_labels=False).copy()
    c=c.remove_layers([v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))])
    for label,key in TARGET["bindings"].items():
        port=c.ports[key];layer=sky130.layer_to_glayer(port.layer)
        pin=rectangle(size=(.14,.14),layer=sky130.get_glayer(layer+"_pin"),centered=True).copy()
        pin.add_label(label,layer=sky130.get_glayer(layer+"_label"))
        ref=align_comp_to_port(pin,port,("c","c"));angle=np.deg2rad(port.orientation)
        ref.move((-.1*np.cos(angle),-.1*np.sin(angle)));c.add(ref)
    c=c.remove_layers([(64,44)],include_labels=True)
    c.write_gds(output)
    top,=gdstk.read_gds(output).top_level();top.flatten();top.name=TARGET["top"]
    lib=gdstk.Library();lib.add(top);lib.write_gds(output)
    return {{"top":top.name,"bbox_um":[list(row) for row in top.bounding_box()],"polygons":len(top.polygons),"gds_bytes":output.stat().st_size}}
'''


def analyses(kind):
    op={"kind":"op","columns":5 if kind=="mirror" else 4,"expected_rows":1}
    ac={"kind":"ac","columns":3,"start":10,"end":1e9,"points":241,"scale":"log"}
    tran={"kind":"transient","columns":5 if kind=="tg" else 4,"start":0,"end":4e-6,"required_windows":[[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]}
    if kind=="mirror":return {"op":op,"compliance":{"kind":"dc","columns":5,"start":.05,"end":1.75,"points":69,"scale":"linear"},"input_gain":{"kind":"dc","columns":5,"start":2e-6,"end":20e-6,"points":10,"scale":"linear"}}
    if kind=="pair":return {"op":op,"differential":{"kind":"dc","columns":6,"start":-.1,"end":.1,"points":41,"scale":"linear"},"common_mode":{"kind":"dc","columns":6,"start":.65,"end":1.3,"points":14,"scale":"linear"},"ac":ac,"transient":tran}
    if kind=="tg":return {"on":{"kind":"dc","columns":5,"start":.05,"end":1.75,"points":35,"scale":"linear"},"off":{"kind":"dc","columns":5,"start":.05,"end":1.75,"points":35,"scale":"linear"},"transient":tran}
    return {"op":op,"gain":ac,"impedance":ac,"dc":{"kind":"dc","columns":5,"start":.75,"end":1.25,"points":11,"scale":"linear"},"transient":tran}


def observed_shortfall(kind,record):
    descriptions={
        "mirror":"The measured W1/L0.5 mirror has worst-corner 2.3439% nominal current error and 1.3285Mohm output resistance; the longer anchor is better. This is a natural quality shortfall, not proof a source-only edit can remove the intrinsic device contribution.",
        "pair":"W3/L1/fingers2 and W3/L0.5/fingers4 each preserve three post-RC transient timeouts. Prelayout and partial post-RC DC/AC values do not establish full-flow success. W1/L0.5/fingers2 is the complete anchor; candidate versus tool numerical classification still needs same-configuration controls.",
        "tg":"The measured W1/L0.5 loaded high plateau misses 1.6V by up to 0.28296V; W4 reduces the sampled error to 0.06964V. Device size is immutable within a configuration, so the intrinsic loss cannot be repaired by silently upsizing. The draft constraints are the explicit 0.3V/10mV limits, not a retroactive 0.1V pass claim.",
        "follower":"At W4.15/L2, TT bandwidth falls from 100.3049MHz prelayout to 92.1982MHz post-RC (about 8.1%). The FVF level shift is intrinsic: unity DC tracking is not the objective. Layout bandwidth degradation is a natural quality shortfall."}
    return {"origin":"unmodified_real_generator_natural_measurement","description":descriptions[kind],"evidence_file":"results/derived/"+TARGETS[kind]["source_record"]+".json","run_ids":[item["run_id"] for item in record["records"]],"repairability_established":False,"formal_or_training_use":False}


def bench(kind):
    common={"supply_V":1.8,"temperature_C":27,"corners":["tt","ss","ff"],"analysis_contracts":analyses(kind)}
    if kind=="mirror":return {**common,"reference_current_A":1e-5,"nominal_output_V":.9,"metrics_from":"steady DC row and central derivative; OP is health evidence"}
    if kind=="pair":return {**common,"tail_current_A":2e-5,"common_mode_V":.9,"drain_DC_clamp_V":1.2,"R_each_ohm":10000,"C_each_F":1e-12,"balance_scope":"deterministic only, no mismatch yield"}
    if kind=="tg":return {**common,"R_load_ohm":100000,"C_load_F":1e-12,"input_pulse_V":[.2,1.6],"terminal_difference_V":.01,"on_gates_V":{"VGN":1.8,"VGP":0},"off_gates_V":{"VGN":0,"VGP":1.8}}
    return {**common,"bias_current_A":1e-5,"nominal_input_V":.9,"C_load_F":1e-12,"level_shift":"intrinsic; no unity DC-tracking specification"}


def source_pack(path,target):
    vendor=ROOT/"vendor/glayout/src/glayout";destination=path/"glayout";destination.mkdir(parents=True)
    for name in ("pdk","placement","primitives","routing","spice","util","provenance"):
        shutil.copytree(vendor/name,destination/name,ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
    # The vendor's common-only initializer establishes primitive/router import
    # order. Replacing it with just PDK exports causes a fresh c_route cycle.
    initializer=(vendor/"__init__.py").read_text()
    if "from .cells" in initializer or "from .blocks" in initializer:raise ValueError("The common bootstrap unexpectedly includes target cells")
    (destination/"__init__.py").write_text(initializer)
    relative="glayout/"+target["module"].replace(".","/")+".py"
    result=path/relative;result.parent.mkdir(parents=True)
    for parent in result.parents:
        if parent==destination:break
        (parent/"__init__.py").write_text("")
    shutil.copyfile(vendor/(target["module"].replace(".","/")+".py"),result)
    return relative


def split_pair_module(pack):
    """Keep the exact algorithm body while freezing existing support functions."""
    module=pack/"glayout/cells/elementary/diff_pair/diff_pair.py"
    text=module.read_text();lines=text.splitlines(keepends=True);tree=ast.parse(text)
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    def full(node):
        start=min([node.lineno]+[decorator.lineno for decorator in node.decorator_list])
        return "".join(lines[start-1:node.end_lineno])+"\n"
    header="".join(lines[:min(node.lineno for node in functions.values())-1])
    support_names=["add_df_labels","add_df_generic_label_alias_ports","diff_pair_netlist"]
    support_import="from .diff_pair_support import "+", ".join(support_names)+"\n"
    (module.parent/"diff_pair_support.py").write_text(header+"\n".join(full(functions[name]) for name in support_names))
    core=module.parent/"diff_pair_core.py"
    core.write_text(header+support_import+"\n"+full(functions["diff_pair"]))
    main=next(node for node in tree.body if isinstance(node,ast.If))
    module.write_text(header+support_import+"from .diff_pair_core import diff_pair\n\n"+full(functions["diff_pair_generic"])+"\n"+"".join(lines[main.lineno-1:main.end_lineno]))
    if full(functions["diff_pair"]) not in core.read_text():raise ValueError("Pair algorithm was not preserved verbatim")
    return str(core.relative_to(pack))


def materialize(pdk_rules):
    if not (ROOT/"runtime/GLdev").is_dir():raise ValueError("Create private task tables only on the execution host")
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out=ROOT/"runtime/task_preparation"/("components_"+stamp);out.mkdir(parents=True,mode=0o700)
    public=out/"public";public.mkdir();private=out/"private";private.mkdir(mode=0o700)
    revision=subprocess.check_output(["git","-C",str(ROOT/"vendor/glayout"),"rev-parse","HEAD"],text=True).strip()
    pdk=json.loads(pdk_rules.read_text())
    pdk={"layers":pdk["layers"],"rules":{a:{b:v for b,v in values.items() if v} for a,values in pdk["rules"].items()}}
    pdk["rules"]={a:values for a,values in pdk["rules"].items() if values}
    summaries=[]
    for kind,target in TARGETS.items():
        work=private/kind;work.mkdir();pack=work/"source_pack";pack.mkdir();editable=source_pack(pack,target)
        if kind=="pair":
            (work/"original_diff_pair.py").write_text((pack/editable).read_text())
            editable=split_pair_module(pack)
        (pack/"generator.py").write_text(GENERATOR)
        (pack/"component_build.py").write_text(BUILD.format(kind=kind,target={k:target[k] for k in ("module","function","top","bindings")}))
        record=json.loads((ROOT/"results/derived"/(target["source_record"]+".json")).read_text())
        sizes=sizing_domain(kind);anchor=target["anchor"];sizes.remove(anchor);random.SystemRandom().shuffle(sizes)
        sizes=[anchor]+sizes;points=[]
        for i,parameters in enumerate(sizes):
            ident="anchor" if i==0 else ("dev_%02d"%i if i<9 else "hidden_%02d"%(i-8))
            role="anchor" if i==0 else ("development" if i<9 else "hidden")
            ref=work/"references"/(ident+".spice");ref.parent.mkdir(exist_ok=True);ref.write_text(reference(kind,parameters))
            contract={"task_id":"draft_"+kind+"_source_quality","configuration_id":ident,"reference_id":"independent_"+kind+"_"+ident,
                "required_corners":["tt","ss","ff"],"specifications":target["specifications"],"objective":target["objective"],
                "scope":"DRAFT_NOT_FROZEN_NOT_MEASURED","analysis_contracts":analyses(kind)}
            validate_contract(contract)
            points.append({"configuration_id":ident,"role":role,"parameters":parameters,"reference_file":str(ref),"reference_id":contract["reference_id"],"contract":contract,"physical_result":None})
        files=sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file())
        metadata={"status":"DRAFT_REAL_SOURCE_AND_REFERENCES_NOT_FORMAL","task_id":points[0]["contract"]["task_id"],"parent_lineage":target["lineage"],"source_revision":revision,
            "E1_stratum":"reuse","source_pack":str(pack),"source_files":files,"editable_paths":[editable],"entrypoint":"generator.py","representation":"G2",
            "configurations":points,"evidence_origin":str(ROOT/"results/derived"/(target["source_record"]+".json")),
            "bench":bench(kind),"natural_shortfall":observed_shortfall(kind,record),
            "immutable_sizing":"Per-configuration W/L/multiplicity and independent N(z) cannot be edited; the same source patch must serve the whole domain",
            "source_dependency_group":"vendor_elementary_targets_shared_with_OTA_closures; not four newly qualified independent clusters",
            "qualification":{"generation_preflight":None,"full_domain_baseline":None,"feasible_edit_witness":None,"isolated_evaluator_adapter":None,"model_context_tokens":None},
            "formal_admission":False,"formal_trials":0,"training_examples":0,"main_benchmark_frozen":False}
        (work/"task.json").write_text(json.dumps(metadata,indent=2)+"\n")
        view={k:v for k,v in metadata.items() if k not in ("configurations","source_files")}
        view["visible_configurations"]=points[:9];view["hidden_configuration_count"]=16
        view["source_snapshot"]={editable:(pack/editable).read_text()}
        view["domain_shape"]={"anchor":1,"development":8,"hidden":16}
        view["source_role"]="draft_task_materialization_not_a_new_lineage"
        destination=public/kind;destination.mkdir();(destination/"task.json").write_text(json.dumps(view,indent=2)+"\n")
        packet={"task_id":metadata["task_id"],"goal":"Improve the declared worst-corner post-RC objective by one shared source edit while preserving the independent circuit, full-rule DRC, LVS, all analysis coverage and every declared constraint. This is an unfrozen development task; layout edits cannot change circuit sizing or dummy count.",
            "contract":points[0]["contract"],"allowed_paths":[editable],"visible_sources":{editable:"Use read_source for the complete current module"},
            "documents":{"configurations":[{key:point[key] for key in ("configuration_id","parameters","reference_id")} for point in points[:9]],
                "PDK":pdk,
                "bench":{key:value for key,value in bench(kind).items() if key!="analysis_contracts"},
                "API":"Complete editable module is provided by read_source. Its exact imported common PDK/MOS/via/placement/routing/util/SPICE libraries and fixed marker/export wrapper are frozen; sibling target cells, complete OTAs, training compiler, trusted evaluator and hidden tables are absent. Import signatures match the existing module. Only ordinary unified source-content diffs are accepted.",
                "circuit":reference(kind,anchor),"natural_shortfall":observed_shortfall(kind,record)["description"]},
            "visible_configurations":[point["configuration_id"] for point in points[:9]],"budget":{"decisions":10,"physical_evaluations":9,"context_tokens":8192,"reserved_output_tokens":1024,"status":"DRAFT_BUDGET_REQUIRES_PILOT"}}
        (destination/"task_packet.json").write_text(json.dumps(packet,indent=2)+"\n")
        summaries.append({"kind":kind,"task_id":metadata["task_id"],"parent_lineage":target["lineage"],"source_bytes":len((pack/editable).read_bytes()),"source_files":len(files),"points":25,"public_file":str(destination/"task.json"),"private_file":str(work/"task.json")})
    index={"status":"DRAFT_REAL_SOURCE_NOT_FORMAL","root":str(out),"tasks":summaries,"task_count":4,"qualified_independent_clusters":None,"formal_tasks":0,"hidden_tables_exported":False}
    (out/"index.json").write_text(json.dumps(index,indent=2)+"\n");print(json.dumps(index,indent=2),flush=True)


def preflight(task_path,output=None,configuration_ids=None):
    started=time.monotonic();cpu=time.process_time()
    task=json.loads(task_path.read_text());pack=Path(task["source_pack"]);sys.path.insert(0,str(pack))
    build=importlib.import_module("component_build").build
    out=output or task_path.parent/"generation_preflight";out.mkdir();rows=[]
    points=task["configurations"]
    if configuration_ids:
        if not set(configuration_ids).issubset(point["configuration_id"] for point in points):raise ValueError("Unknown preflight point")
        points=[point for point in points if point["configuration_id"] in configuration_ids]
    for point in points:
        t=time.monotonic()
        try:result={"generation_passed":True,**build(point["parameters"],out/(point["configuration_id"]+".gds"))}
        except Exception as exc:result={"generation_passed":False,"error":type(exc).__name__+": "+str(exc)}
        rows.append({"configuration_id":point["configuration_id"],"wall_seconds":time.monotonic()-t,**result})
    result={"scope":"trusted_source_generation_preflight_not_physical_qualification","rows":rows,"wall_seconds":time.monotonic()-started,"cpu_seconds":time.process_time()-cpu,"child_cpu_seconds":resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,"all_generated":all(row["generation_passed"] for row in rows),"full_domain_generated":len(rows)==len(task["configurations"]),"DRC_LVS_RC_SPICE_established":False}
    (out/"generation.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({k:v for k,v in result.items() if k!="rows"}),flush=True)


def compare_pair_anchor(new,old):
    """Compare real filled geometry and all labels; cell names are metadata."""
    from collections import defaultdict
    import gdstk
    def contents(path):
        lib=gdstk.read_gds(path);top,=lib.top_level();top.flatten()
        groups=defaultdict(list)
        for polygon in top.get_polygons():groups[(polygon.layer,polygon.datatype)].append(polygon)
        labels=sorted((label.text,tuple(label.origin),label.layer,label.texttype,label.rotation,label.magnification,label.x_reflection) for label in top.labels)
        return lib,groups,labels
    a,ap,al=contents(new);b,bp,bl=contents(old)
    if a.unit!=b.unit:raise ValueError("GDS units differ; no geometry equivalence claimed")
    changed=[]
    for layer in sorted(set(ap)|set(bp)):
        if gdstk.boolean(ap[layer],bp[layer],"xor",precision=min(a.precision,b.precision)/a.unit):changed.append(list(layer))
    return {"new_gds":str(new),"reference_gds":str(old),"units_m":a.unit,"precision_m":min(a.precision,b.precision),"changed_layers":changed,"filled_geometry_equal":not changed,"all_labels_equal":al==bl,"cell_names_excluded":True,"physical_measurements_rerun":False}


def run_anchor_comparison(preparation):
    prefix="/headless/conda-env/miniconda3/envs/GLdev"
    references={"mirror":"phase0_20261018T234522533497Z_mirror_characterization/mirror4.gds",
        "pair":"phase0_20261019T003804699917Z_pair_characterization/pair6.gds",
        "tg":"phase0_20261018T234625109110Z_tg_characterization/tg6.gds",
        "follower":"phase0_20261019T004600334942Z_follower_characterization/follower4.gds"}
    pairs=[]
    for kind,old in references.items():
        for path in reversed(sorted((preparation/"private"/kind).glob("preflight_attempt_*/generation/generation.json"))):
            if any(row["configuration_id"]=="anchor" and row["generation_passed"] for row in json.loads(path.read_text())["rows"]):
                pairs.append((kind,str(path.parent/"anchor.gds"),str(ROOT/"runs/phase0"/old)));break
        else:raise ValueError("No generated anchor: "+kind)
    attempt=preparation/"private"/("geometry_attempt_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"));attempt.mkdir()
    program="import json,time,resource;from pathlib import Path;from scripts.materialize_tasks import compare_pair_anchor;started=time.monotonic();pairs="+repr(pairs)+";rows=[dict(kind=k,**compare_pair_anchor(Path(a),Path(b))) for k,a,b in pairs];print(json.dumps(dict(scope='development_geometry_comparison_not_new_physical_measurement',records=rows,wall_seconds=time.monotonic()-started,cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,formal_results=0),indent=2))"
    argv=["docker","run","--rm","--user",str(os.getuid())+":"+str(os.getgid()),"--network","none","--read-only","--cap-drop","ALL","--cpus","2","--memory","8g",
        "-v",str(ROOT)+":"+str(ROOT)+":ro","-v",str(ROOT/"runtime/GLdev")+":"+prefix+":ro","-w",str(ROOT),"-e","PYTHONDONTWRITEBYTECODE=1","-e","PYTHONPATH="+str(ROOT)+":"+prefix+"/lib/python3.10/site-packages",
        "--entrypoint",prefix+"/bin/python","hpretl/iic-osic-tools:chipathon","-c",program]
    started=time.monotonic();result=subprocess.run(argv,capture_output=True,text=True,timeout=120)
    (attempt/"stdout.json").write_text(result.stdout);(attempt/"stderr.log").write_text(result.stderr)
    (attempt/"invocation.json").write_text(json.dumps({"argv":argv,"returncode":result.returncode,"wall_seconds":time.monotonic()-started},indent=2)+"\n")
    if result.returncode:raise RuntimeError(result.stderr)
    data=json.loads(result.stdout);(preparation/"public/anchor_geometry_comparison.json").write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps(data,indent=2),flush=True)


def finalize_public(preparation):
    contexts=json.loads((preparation/"public/context_calibration.json").read_text())
    context={row["kind"]:row for row in contexts["records"]}
    geometries=json.loads((preparation/"public/anchor_geometry_comparison.json").read_text())
    geometry={row["kind"]:row for row in geometries["records"]}
    rows=[];cpu=0.;child_cpu=0.;stage_wall=0.;missing_cpu=0;attempt_count=0
    for kind in TARGETS:
        private=preparation/"private"/kind;generated=set();failed=0;generations=0
        records=[]
        for path in sorted(private.glob("preflight_attempt_*/generation/generation.json")):
            record=json.loads(path.read_text());records.append(str(path))
            generated.update(row["configuration_id"] for row in record["rows"] if row["generation_passed"])
            failed += sum(not row["generation_passed"] for row in record["rows"]);generations+=len(record["rows"])
            cpu+=record["cpu_seconds"];child_cpu+=record["child_cpu_seconds"]
        invocations=list(private.glob("preflight_attempt_*/invocation.json"))
        if (private/"preflight_invocation.json").is_file():invocations.append(private/"preflight_invocation.json")
        for path in invocations:
            record=json.loads(path.read_text());stage_wall+=record["wall_seconds"];attempt_count+=1
            if not (path.parent/"generation/generation.json").exists():missing_cpu+=1
        metadata=json.loads((private/"task.json").read_text())
        q={"unique_parameter_points_with_actual_GDS":len(generated),"generation_attempts":generations,"failed_generation_attempts":failed,
            "current_snapshot_all_25_generated_in_one_run":kind in ("tg","follower"),"raw_generation_records":records,"establishes_S2":False}
        metadata["qualification"].update(generation_preflight=q,model_context_tokens=context[kind],anchor_geometry_equivalence=geometry[kind])
        metadata["pdk_revision"]="0fe599b2afb6708d281543108caf8310912f54af"
        metadata["frozen_source_pack"]=metadata["source_pack"]
        metadata["frozen_source_files"]=[name for name in metadata["source_files"] if name not in metadata["editable_paths"]]
        (private/"task.json").write_text(json.dumps(metadata,indent=2)+"\n")
        public=preparation/"public"/kind/"task.json";view=json.loads(public.read_text())
        for key in ("qualification","pdk_revision","frozen_source_pack","frozen_source_files"):view[key]=metadata[key]
        public.write_text(json.dumps(view,indent=2)+"\n")
        rows.append({"kind":kind,"task_id":metadata["task_id"],"parent_lineage":metadata["parent_lineage"],"source_files":len(metadata["source_files"]),"editable_paths":metadata["editable_paths"],
            "GDS_parameter_points":len(generated),"failed_generation_attempts":failed,"generation_attempts":generations,"reference_count":25,
            "anchor_geometry_equal":geometry[kind]["filled_geometry_equal"],"anchor_labels_equal":geometry[kind]["all_labels_equal"],"input_tokens":context[kind]["input_tokens_with_complete_source"],"formal_admission":False})
    comparison_invocations=list((preparation/"private").glob("geometry_attempt_*/invocation.json"))+list((preparation/"private").glob("anchor_geometry*invocation.json"))
    comparison_costs=[json.loads(path.read_text()) for path in comparison_invocations]
    summary={"phase":"development_component_task_materialization","preparation":str(preparation),"task_count":4,"records":rows,
        "generation_container_attempts":attempt_count,"generation_attempt_stage_wall_seconds":stage_wall,"generation_process_CPU_seconds":cpu,"generation_child_CPU_seconds":child_cpu,
        "container_attempts_without_CPU_records":missing_cpu,"preparation_failures":[{"error":"provenance was a package, not provenance.py","CPU_and_wall_cost":"unmeasured; original failed preparation directory retained"}],
        "geometry_comparison":{**{key:value for key,value in geometries.items() if key!="records"},"invocation_attempts":len(comparison_costs),"failed_attempts":sum(record["returncode"]!=0 for record in comparison_costs),"all_attempt_stage_wall_seconds":sum(record["wall_seconds"] for record in comparison_costs)},
        "hidden_tables_exported":False,"new_physical_measurements":0,"formal_tasks":0,
        "remaining_qualification":["full-domain baseline physics","same-configuration gold controls for numerical failures","feasible oracle source-edit witness","isolated task-specific trusted evaluator adapters","policy episode context/history and budget freeze"]}
    (preparation/"public/materialization_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)


def run_generation_preflights(preparation,kinds=None,configuration_ids=None):
    from concurrent.futures import ThreadPoolExecutor
    prefix="/headless/conda-env/miniconda3/envs/GLdev"
    def run(kind):
        work=preparation/"private"/kind
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        attempt=work/("preflight_attempt_"+stamp);attempt.mkdir()
        name="task-generation-"+kind+"-"+stamp.lower()
        argv=["docker","run","--rm","--name",name,"--user",str(os.getuid())+":"+str(os.getgid()),"--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--cpus","2","--memory","8g","--tmpfs","/tmp:rw,nosuid,nodev,size=512m",
            "-v",str(ROOT)+":"+str(ROOT)+":ro","-v",str(attempt)+":"+str(attempt)+":rw","-v",str(ROOT/"runtime/GLdev")+":"+prefix+":ro",
            "-e","HOME=/tmp","-e","OMP_NUM_THREADS=1","-e","OPENBLAS_NUM_THREADS=1","-e","PYTHONDONTWRITEBYTECODE=1","-e","PYTHONPATH="+str(work/"source_pack")+":"+prefix+"/lib/python3.10/site-packages",
            "--entrypoint",prefix+"/bin/python","hpretl/iic-osic-tools:chipathon",str(ROOT/"scripts/materialize_tasks.py"),"--preflight",str(work/"task.json"),"--preflight-output",str(attempt/"generation")]
        if configuration_ids:argv += ["--configuration-ids",*configuration_ids]
        began=time.monotonic();record={"argv":argv,"started_at_utc":datetime.now(timezone.utc).isoformat(),"timeout_seconds":480}
        with (attempt/"console.log").open("w") as log:
            try:record["returncode"]=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=480).returncode
            except subprocess.TimeoutExpired:
                subprocess.run(["docker","kill",name],stdout=log,stderr=subprocess.STDOUT,timeout=20);record.update(returncode=None,status="TIMEOUT")
        record.update(wall_seconds=time.monotonic()-began,ended_at_utc=datetime.now(timezone.utc).isoformat())
        (attempt/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps({"kind":kind,"attempt":str(attempt),"returncode":record["returncode"],"wall_seconds":record["wall_seconds"]}),flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,kinds or TARGETS))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--preflight",type=Path);parser.add_argument("--preflight-output",type=Path)
    parser.add_argument("--generation-preflight-root",type=Path);parser.add_argument("--pdk-rules",type=Path)
    parser.add_argument("--compare-anchor-preparation",type=Path)
    parser.add_argument("--finalize-public",type=Path)
    parser.add_argument("--kinds",nargs="+",choices=list(TARGETS));parser.add_argument("--configuration-ids",nargs="+");args=parser.parse_args()
    if args.preflight:preflight(args.preflight,args.preflight_output,args.configuration_ids)
    elif args.generation_preflight_root:run_generation_preflights(args.generation_preflight_root.resolve(),args.kinds,args.configuration_ids)
    elif args.compare_anchor_preparation:run_anchor_comparison(args.compare_anchor_preparation.resolve())
    elif args.finalize_public:finalize_public(args.finalize_public.resolve())
    else:
        if not args.pdk_rules:parser.error("--pdk-rules is required when materializing a task capsule")
        materialize(args.pdk_rules)
