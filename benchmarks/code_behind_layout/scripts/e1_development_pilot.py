#!/usr/bin/env python3
"""Fresh GPT composition pilots, with real G0/G1/G2 candidate execution.

The mirror is assembled from primitive geometry, never a target-cell import.
These development anchors are neither a formal test set nor training examples.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SSH=["ssh","-i","~/.ssh/cbl_server_key","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=12","cbl-server"]
REMOTE="/srv/code-behind-layout"
G2_FILES=["pdk/mappedpdk.py","pdk/sky130_mapped/sky130_mapped.py","pdk/sky130_mapped/sky130_grules.py",
    "pdk/sky130_mapped/sky130_add_npc.py","util/comp_utils.py","util/port_utils.py","util/snap_to_grid.py",
    "primitives/via_gen.py","routing/straight_route.py","routing/L_route.py","routing/c_route.py",
    "provenance/__init__.py","provenance/runtime.py","provenance/netlist_summary.py"]
INITIALIZERS=["glayout/__init__.py","glayout/pdk/__init__.py","glayout/pdk/sky130_mapped/__init__.py",
    "glayout/util/__init__.py","glayout/primitives/__init__.py","glayout/routing/__init__.py"]
INITIAL='''import argparse,json
import gdstk
p=argparse.ArgumentParser()
p.add_argument("--configuration");p.add_argument("--output")
a=p.parse_args();configuration=json.load(open(a.configuration))
library=gdstk.Library();top=library.new_cell("mirror4")
# Implement the declared mirror topology here using only the allowed interface.
library.write_gds(a.output)
'''


def logical_primitive(metadata):
    """Expose physical access to four electrical terminals, not via-array internals."""
    names={"D":["drain_"+s for s in "NESW"],"G":["gate_"+s for s in "NESW"],
        "S":["source_"+s for s in "NESW"],"B":["tie_"+s+"_top_met_"+s for s in "NESW"]}
    ports={name:metadata["ports"][name] for group in names.values() for name in group}
    return {**{k:v for k,v in metadata.items() if k!="ports"},"units":"um","logical_terminals":names,"ports":ports}


def effective_pdk_rules(data):
    # Empty entries represent no declared pair rule. Preserve every actual rule
    # and every layer while avoiding thousands of empty pair placeholders.
    return {"layers":data["layers"],"rules":{a:{b:value for b,value in row.items() if value}
        for a,row in data["rules"].items() if any(row.values())}}


def visible_physical_feedback(result):
    physical=result.get("physical_result") or {};observation=physical.get("observation",{})
    return {"status":result["status"],"tiers":result.get("tiers",physical.get("assessment")),
        "checks":observation.get("checks",{}),"pex":observation.get("pex",{}),
        "corners":observation.get("corners",{}),"candidate_error":result.get("candidate_error"),
        "analysis_validation":physical.get("analysis_validation",{})}


def contract():
    return {"task_id":"development_E1_mirror_composition","configuration_id":"anchor",
        "reference_id":"independent_pfet_w1p88_l3_main_m2_dummy_m2","required_corners":["tt","ss","ff"],
        "specifications":[{"name":"relative_current_error","unit":"1","min":-.02,"max":.02},
            {"name":"output_resistance","unit":"ohm","min":5e6}],
        "analysis_contracts":{"OP":{"kind":"op","columns":5,"expected_rows":1},
            "compliance":{"kind":"dc","columns":5,"start":.05,"end":1.75,"points":69,"scale":"linear"},
            "input_gain":{"kind":"dc","columns":5,"start":2e-6,"end":20e-6,"points":10,"scale":"linear"}}}


EVALUATOR=r'''import argparse,json,math,pathlib,subprocess
import gdstk,numpy as np
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report,rc_netlist_inventory
from src.spice_validation import validate_analysis
from src.measurement import assess
p=argparse.ArgumentParser();p.add_argument("--gds");p.add_argument("--output");p.add_argument("--fidelity");a=p.parse_args()
out=pathlib.Path(a.output);gds=pathlib.Path(a.gds);contract=json.loads(pathlib.Path('/trusted/contract.json').read_text())
top,=gdstk.read_gds(gds).top_level()
if top.name!='mirror4':raise ValueError('Candidate top must be mirror4')
observation={k:contract[k] for k in ['task_id','configuration_id','reference_id']}
observation.update(executed=True,gds_emitted=True,checks={},corners={})
artifacts={'spice':{}}
def save():
 result={'contract':contract,'observation':observation,'artifacts':artifacts,'assessment':assess(contract,observation)}
 (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n');return result
def magic(tcl,stem):
 (out/(stem+'.tcl')).write_text(tcl)
 with (out/(stem+'.log')).open('w') as log:
  result=subprocess.run(['magic','-rcfile','/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],input=tcl,text=True,stdout=log,stderr=subprocess.STDOUT,cwd=out,timeout=120)
 if result.returncode:raise RuntimeError('Magic failed')
drc=check_gds(gds,out/'drc',timeout=120)
(out/'drc/metadata.json').write_text(json.dumps(drc,indent=2)+'\n')
artifacts['drc']={'report':'drc/direct_drc.rpt','metadata':'drc/metadata.json'}
observation['checks']['drc']=drc['is_clean'];save()
magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load mirror4','select top cell','flatten mirror4_lvs','load mirror4_lvs','select top cell','extract all','ext2spice lvs','ext2spice -o extracted_lvs.spice','puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'lvs_extract')
with (out/'netgen.log').open('w') as log:
 result=subprocess.run(['netgen','-batch','lvs',str(out/'extracted_lvs.spice')+' mirror4_lvs','/trusted/reference.spice mirror4','/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl',str(out/'lvs.rpt')],stdout=log,stderr=subprocess.STDOUT,timeout=120)
lvs=netgen_lvs_report((out/'lvs.rpt').read_text() if (out/'lvs.rpt').exists() else '')
clean=lvs['is_clean'] and result.returncode==0
for key in ['lvs','devices','ports','intent']:observation['checks'][key]=clean
artifacts['lvs']={'report':'lvs.rpt'};save()
if not drc['completed']:raise RuntimeError('DRC did not complete')
if not drc['is_clean'] or not clean:raise SystemExit(2)
if a.fidelity=='pex_spice':
 magic('\n'.join(['drc off','gds read {'+str(gds)+'}','load mirror4','select top cell','flatten mirror4_rc','load mirror4_rc','select top cell','extract do local','extract all','feedback save extraction_feedback.tcl','ext2sim labels on','ext2sim','extresist simplify off','extresist all','ext2spice lvs','ext2spice cthresh 0','ext2spice extresist on','ext2spice -o mirror4_pex.spice','puts stdout EXTRACTION_COMPLETE','quit -noprompt','']),'rc_extract')
 net=out/'mirror4_pex.spice';text=net.read_text();ports=['VREF','VOUT','VSS','B']
 inventory=rc_netlist_inventory(text,'mirror4_rc',ports)
 (out/'rc_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
 artifacts['pex']={'netlist':'mirror4_pex.spice','top_cell':'mirror4_rc','ports':ports}
 observation['pex']={'executed':True,'kind':'physical_rc','resistance_extracted':inventory['has_real_RC'],'capacitance_extracted':inventory['has_real_RC']};save()
 if not inventory['has_real_RC']:raise SystemExit(2)
 declaration=next(line.split() for line in text.splitlines() if line.lower().startswith('.subckt mirror4_rc '))
 bindings={'VREF':'ref','VOUT':'out','VSS':'vdd','B':'vdd'};nodes=[bindings[n.upper()] for n in declaration[2:]]
 for corner in contract['required_corners']:
  work=out/corner;work.mkdir();(work/'.spiceinit').write_text('set ngbehavior=hsa\n')
  common=['Mirror composition development DC qualification','.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice '+corner,'.option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16','.temp 27','.include '+str(net),'VSUPPLY vdd 0 1.8','VOUT out 0 .9','IREF ref 0 10u','XDUT '+' '.join(nodes)+' mirror4_rc','.save v(ref) v(out) i(vout) i(vsupply)','.control','set wr_vecnames','set wr_singlescale']
  analyses={'OP':['op','wrdata OP.dat v(ref) v(out) i(vout) i(vsupply)'],'compliance':['dc VOUT .05 1.75 .025','wrdata compliance.dat v(ref) v(out) i(vout) i(vsupply)'],'input_gain':['dc IREF 2u 20u 2u','wrdata input_gain.dat v(ref) v(out) i(vout) i(vsupply)']}
  artifacts['spice'][corner]={'analyses':{}};validations={}
  for name,commands in analyses.items():
   (work/(name+'.spice')).write_text('\n'.join(common+commands+['quit','.endc','.end','']))
   with (work/(name+'_console.log')).open('w') as log:
    sim=subprocess.run(['ngspice','-b','-o',name+'.log',name+'.spice'],cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=90)
   artifacts['spice'][corner]['analyses'][name]={'data':corner+'/'+name+'.dat','log':corner+'/'+name+'.log','returncode':sim.returncode}
   validations[name]=validate_analysis(work/(name+'.dat'),work/(name+'.log'),contract['analysis_contracts'][name],sim.returncode)
  (work/'analysis_validation.json').write_text(json.dumps(validations,indent=2)+'\n')
  complete=all(v['complete'] for v in validations.values());metrics={};healthy=False
  if complete:
   op=np.loadtxt(work/'OP.dat',skiprows=1,ndmin=2)[0];curve=np.loadtxt(work/'compliance.dat',skiprows=1,ndmin=2);gain=np.loadtxt(work/'input_gain.dat',skiprows=1,ndmin=2)
   index=int(np.argmin(np.abs(curve[:,0]-.9)));current=curve[:,3];conductance=float(np.gradient(current,curve[:,0])[index]);ratio=float(current[index]/1e-5)
   healthy=0<float(op[1])<1.8 and abs(float(op[2])-.9)<1e-6 and float(current[index])>0
   metrics={'relative_current_error':{'value':ratio-1,'unit':'1'},'output_resistance':{'value':1/abs(conductance) if conductance else None,'unit':'ohm'},'incremental_input_gain':{'value':float(np.gradient(gain[:,3],gain[:,0])[4]),'unit':'1'}}
  observation['corners'][corner]={'converged':complete,'operating_point_valid':healthy,'metrics':metrics};save()
result=save();print(json.dumps(result),flush=True)
raise SystemExit(0 if result['assessment']['S2'] else 2)
'''


def prepare_primitives():
    import gdstk
    from glayout import sky130
    from glayout.primitives.fet import pmos
    out=Path.cwd()
    component=pmos(sky130,width=1.88,length=3,fingers=1,multipliers=2,with_dummy=False,
        with_tie=True,with_substrate_tap=False).copy()
    component=component.remove_layers([v for k,v in sky130.glayers.items() if k.endswith(("_label","_pin"))])
    component=component.remove_layers([(64,44)],include_labels=True);component.name="pmos_m2"
    component.write_gds(out/"pmos_m2.gds")
    metadata={"cell":"pmos_m2","model":"sky130_fd_pr__pfet_01v8","width_um":1.88,"length_um":3,
        "parallel_multiplier":2,"fingers_per_multiplier":1,"dummy_devices":0,
        "bbox_um":[list(map(float,row)) for row in component.bbox],
        "ports":{name:{"center_um":list(map(float,port.center)),"width_um":float(port.width),
            "orientation_degrees":float(port.orientation),"layer":list(port.layer)} for name,port in component.ports.items()}}
    (out/"pmos_m2.json").write_text(json.dumps(metadata,indent=2)+"\n")
    (out/"pdk_rules.json").write_text(json.dumps({"layers":sky130.glayers,"rules":sky130.grules},indent=2)+"\n")
    print(json.dumps({"prepared":"generic PMOS m2 primitive; no mirror target geometry","gds":"pmos_m2.gds"}),flush=True)


def prepare_bundle(preparation):
    out=ROOT/"runs/development/e1_bundles"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True)
    for method in ["G0","G1","G2"]:
        library=out/method;library.mkdir()
        if method!="G0":
            shutil.copyfile(preparation/"pmos_m2.gds",library/"pmos_m2.gds")
            (library/"pmos_m2.json").write_text(json.dumps(logical_primitive(json.loads((preparation/"pmos_m2.json").read_text())),separators=(",",":"))+"\n")
        if method=="G2":
            for name in G2_FILES:
                path=library/"glayout"/name;path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/"vendor/glayout/src/glayout"/name,path)
            for name in INITIALIZERS:
                path=library/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("")
    (out/"raw").mkdir()
    shutil.copyfile(preparation/"pmos_m2.json",out/"raw/pmos_m2_all_ports.json")
    shutil.copyfile(preparation/"pdk_rules.json",out/"raw/pdk_rules_all_entries.json")
    (out/"pdk_rules.json").write_text(json.dumps(effective_pdk_rules(json.loads((preparation/"pdk_rules.json").read_text())),separators=(",",":"))+"\n")
    metadata=logical_primitive(json.loads((preparation/"pmos_m2.json").read_text()))
    # This public artifact contains only one generic primitive, not a target.
    (out/"public.json").write_text(json.dumps({"bundle":str(out),"primitive":metadata,
        "pdk_rules":json.loads((out/"pdk_rules.json").read_text()),"contract":contract(),
        "preparation_run":str(preparation),"formal_trials":0,"training_examples":0},indent=2)+"\n")
    print(json.dumps({"bundle":str(out),"public_file":str(out/"public.json")}),flush=True)


def evaluate(args):
    import fcntl
    from src.candidate_executor import CandidateExecutor
    from src.model_adapter import check_utc_budget
    budget_packet={"budget":{"deadline_utc":args.deadline_utc}} if args.deadline_utc else {"budget":{}}
    check_utc_budget(budget_packet)
    work=ROOT/"runs/development/e1_trusted_inputs"/str(uuid.uuid4());trusted=work/"trusted";trusted.mkdir(parents=True)
    source=args.source;source_paths=["generator.py"]
    if args.gold_control:
        source=work/"control_source";source.mkdir()
        shutil.copyfile(args.gold_control,source/"control.gds")
        (source/"generator.py").write_text('import argparse,shutil\np=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args();shutil.copyfile("/source/control.gds",a.output)\n')
        source_paths.append("control.gds")
    (trusted/"evaluate.py").write_text(EVALUATOR)
    (trusted/"reference.spice").write_text(".subckt mirror4 VREF VOUT VSS B\nXREF VREF VREF VSS B sky130_fd_pr__pfet_01v8 w=1.88 l=3 m=2\nXOUT VOUT VREF VSS B sky130_fd_pr__pfet_01v8 w=1.88 l=3 m=2\nXDUMMY B B B B sky130_fd_pr__pfet_01v8 w=1.88 l=3 m=2\n.ends mirror4\n")
    (trusted/"contract.json").write_text(json.dumps(contract(),indent=2)+"\n")
    paths=["evaluate.py","reference.spice","contract.json","src/__init__.py"]
    (trusted/"src").mkdir();(trusted/"src/__init__.py").write_text("")
    for name in ["physical_drc.py","report_parsers.py","measurement.py","spice_validation.py"]:
        shutil.copyfile(ROOT/"src"/name,trusted/"src"/name);paths.append("src/"+name)
    library=args.bundle/args.method;library_paths=[str(p.relative_to(library)) for p in library.rglob("*") if p.is_file()]
    executor=CandidateExecutor(ROOT/"runtime/GLdev",ROOT/"runs/development/e1_physical",ROOT/"runtime/magic-8.3.685",timeout=420)
    queued=time.monotonic();slot=None
    # Three fresh policies run concurrently; at most two 2CPU physical pipelines
    # from this pilot run at once. Kernel file locks release on process exit.
    while slot is None:
        check_utc_budget(budget_packet)
        for index in range(2):
            handle=(ROOT/"runtime"/("e1_execution_slot_%d"%index)).open("a")
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);slot=handle;break
            except BlockingIOError:handle.close()
        if slot is None:time.sleep(.1)
    queue_wait=time.monotonic()-queued
    try:
        check_utc_budget(budget_packet)
        result=executor.execute(source_dir=source,source_paths=source_paths,entrypoint="generator.py",representation=args.method,
            configuration={"width":1.88,"length":3,"multipliers":2,"top_cell":"mirror4","ports":["VREF","VOUT","VSS","B"],
                "pdk_rules":json.loads((args.bundle/"pdk_rules.json").read_text())},trusted_dir=trusted,trusted_paths=paths,
            library_dir=library,library_paths=library_paths,fidelity=args.fidelity,
            context={"phase":"development_E1_evaluator_gold_control" if args.gold_control else "development_E1_composition_pilot","configuration_id":"anchor","source_role":"trusted_evaluator_control" if args.gold_control else "fresh_GPT_development_candidate",
                "reference_id":contract()["reference_id"],"pdk_revision":"0fe599b2afb6708d281543108caf8310912f54af"})
    finally:slot.close()
    physical=Path(result["run_directory"]);manifest=json.loads((physical/"manifest.json").read_text())
    boundary=json.loads((physical/"evidence/gds_boundary.json").read_text()) if (physical/"evidence/gds_boundary.json").exists() else {}
    result["tiers"]=(result.get("physical_result") or {}).get("assessment",{"S0":manifest["candidate"]["returncode"]==0 and boundary.get("gds_parse_complete") is True,"S1":False,"S2":False})
    result["queue_wait_seconds"]=queue_wait;result["fidelity"]=args.fidelity
    result["physical_wall_seconds"]=sum(manifest[stage]["wall_seconds"] for stage in ["candidate","trusted"] if stage in manifest)
    cpu=0.;missing=0
    for stage in ["candidate","trusted"]:
        if stage not in manifest:continue
        path=physical/(stage+"_stage/resource_usage.json")
        if path.exists():
            usage=json.loads(path.read_text());cpu+=usage["child_user_cpu_seconds"]+usage["child_system_cpu_seconds"]
        else:missing+=1
    result["physical_waited_child_cpu_seconds"]=cpu;result["physical_cpu_records_missing"]=missing
    console=(physical/"candidate_stage/console.log").read_text(errors="replace")
    errors=[line.strip() for line in console.splitlines() if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):",line.strip())]
    if errors:
        message=errors[-1];kind=message.split(":",1)[0]
        if kind=="KeyError":
            requested=re.search(r"['\"]([^'\"]+)['\"]",message)
            result["candidate_error"]={"type":kind,"requested_name":requested.group(1) if requested else None,
                "message":"Requested name is unavailable; consult the declared four-terminal metadata"}
        else:result["candidate_error"]={"type":kind,"message":message[:1000]}
    print(json.dumps(result,indent=2),flush=True)


def task_packet(public,method,deadline_utc):
    docs={"scope":"Development-only mirror composition from primitive devices; no target-cell geometry or complete generator is supplied.",
        "CLI":"python generator.py --configuration PATH --output /output/candidate.gds. Emit only candidate.gds; top=mirror4. All cell and label text must be nonempty ASCII letters/digits/_/$.",
        "patch_format":"Ordinary unified diff with --- a/generator.py and +++ b/generator.py, accurate hunk counts, final newline; malformed patches are rejected and consume a decision.",
        "netlist":"XREF VREF VREF VSS B pfet w=1.88 l=3 m=2; XOUT VOUT VREF VSS B pfet w=1.88 l=3 m=2; XDUMMY B B B B pfet w=1.88 l=3 m=2. Pin VSS is the positive source supply for this PMOS mirror. B and VSS are distinct top ports, though both bench-biased to1.8V. No other device sizes or dummy count are permitted.",
        "bench":"Supply/body1.8V; IREF10u ref→ground; VOUT.9V. Complete TT/SS/FF OP,69point VOUT .05..1.75/.025,10point IREF2u..20u/2u. At.9V DC current error≤2%; output resistance from DC derivative≥5Mohm.",
        "PDK":public["pdk_rules"],"labels":"For metal1 layer67/20, pin67/16,label67/5; metal2 layer68/20,pin68/16,label68/5; metal3 layer69/20,pin69/16,label69/5. Use exported labels VREF VOUT VSS B only; remove internal primitive labels. Physical .005um grid."}
    if method!="G0":docs["primitive"]={"read_only_gds":"/library/pmos_m2.gds","read_only_metadata":"/library/pmos_m2.json",**public["primitive"]}
    if method=="G0":docs["API"]="Only gdstk/numpy/math and generic Python are available; no PCell library or glayout/gdsfactory import. Draw actual layers/devices/contacts/metal geometry with gdstk. PDK rules are data in the configuration JSON."
    elif method=="G1":docs["API"]="Only gdstk/numpy/math and generic Python are available. Import the generic PMOS GDS, instantiate independently as needed, and route using explicit rectangles/polygons/vias. The PCell has two parallel PMOS fingers W1.88/L3, a bulk tie and no dummy. Metadata gives local coordinates; each reference origin translates them. It is not a mirror. No glayout/gdsfactory import."
    else:docs["API"]="G1 generic PMOS GDS+metadata plus gdsfactory and only cropped glayout pdk/ports/placement/routing utilities. Use from gdsfactory import Component,import_gds; from gdsfactory.port import Port; from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk; from glayout.routing.straight_route import straight_route; from glayout.routing.L_route import L_route; from glayout.routing.c_route import c_route. Build a Component from imported GDS, reconstruct ports from metadata, refs=top<<device, move refs before routes. Ports use center,width,orientation,layer. straight_route(pdk,port1,port2,width=.3), L_route(pdk,port1,port2), c_route(pdk,port1,port2,extension=2) return route Components; add them to the actual circuit. No fet/current_mirror/full-target generator is present. Export GDS then rename top mirror4 with gdstk if needed."
    packet={"task_id":"development_E1_mirror_composition","goal":"Implement the declared physical PMOS mirror in generator.py using the "+method+" interface. Read source, propose code patches, inspect real anchor feedback, and finish within the fixed budget. All failures count. This is development calibration, excluded from formal results and training.",
        "contract":public["contract"],"allowed_paths":["generator.py"],"visible_sources":{"generator.py":"Use read_source for the scaffold and any patched contents"},
        "documents":docs,"visible_configurations":["anchor"],"budget":{"decisions":10,"physical_evaluations":3,"deadline_utc":deadline_utc}}
    return packet


def run_policy(args):
    from src.candidate_executor import VisibleActionGateway
    from src.model_adapter import GptDecisionAdapter,check_utc_budget
    public=json.loads(args.public_bundle.read_text());out=ROOT/"runs/development/e1_policy"/(args.method+"_"+str(uuid.uuid4()))
    source=out/"source";source.mkdir(parents=True);(source/"generator.py").write_text(INITIAL)
    packet=task_packet(public,args.method,args.deadline_utc)
    adapter=GptDecisionAdapter(out/"decisions");config=json.loads((ROOT/"configs/models/gpt.json").read_text());session=adapter.start(packet,config)
    remote_source=REMOTE+"/runs/development/e1_policy/"+session["session_id"]+"/source";evaluations=[];actions=[];rejections=[];started=time.monotonic()
    def callback(name,fidelity):
        check_utc_budget(packet)
        if name!="anchor" or len(evaluations)>=3:raise ValueError("Visible physical evaluation budget exhausted")
        subprocess.run(SSH+["mkdir -p "+shlex.quote(remote_source)],check=True,capture_output=True,text=True)
        subprocess.run(["scp"]+SSH[1:-1]+[str(source/"generator.py"),"cbl-server:"+remote_source+"/generator.py"],check=True,capture_output=True,text=True)
        check_utc_budget(packet)
        command=" ".join(map(shlex.quote,["python3",REMOTE+"/scripts/e1_development_pilot.py","--evaluate","--method",args.method,"--bundle",public["bundle"],"--source",remote_source,"--fidelity",fidelity,"--deadline-utc",args.deadline_utc]))
        index=len(evaluations);result=subprocess.run(SSH+[command],text=True,capture_output=True,timeout=480)
        (out/("physical_%02d.json"%index)).write_text(result.stdout);(out/("physical_%02d_stderr.log"%index)).write_text(result.stderr)
        record=json.loads(result.stdout);record["N_z"]=index+1;record["source"]=(source/"generator.py").read_text();record["elapsed_wall_seconds"]=time.monotonic()-started;evaluations.append(record)
        # Exact trusted visible reports may be observed; evaluator implementation and hidden points are not sent.
        return visible_physical_feedback(record)
    gateway=VisibleActionGateway(packet,source,callback);observation={"status":"begin"};error=None
    try:
        for _ in range(10):
            try:
                check_utc_budget(packet)
                action=adapter.step(session,observation);check_utc_budget(packet);actions.append(action["action"])
                observation=gateway.dispatch(action)
                if action["action"]=="finish":break
            except (ValueError,subprocess.CalledProcessError) as exc:
                detail=(exc.stderr or str(exc)) if isinstance(exc,subprocess.CalledProcessError) else str(exc)
                observation={"status":"rejected_action","error":detail};rejections.append(observation)
        # Charge one declared final verification when the last evaluated bytes are stale or absent.
        check_utc_budget(packet)
        if len(evaluations)<3 and (not evaluations or evaluations[-1]["source"]!=(source/"generator.py").read_text() or evaluations[-1].get("fidelity")!="pex_spice"):callback("anchor","pex_spice")
    except Exception as exc:error=type(exc).__name__+": "+str(exc)
    finally:adapter.finish(session)
    curve=[{"N_z":r["N_z"],"run_directory":r["run_directory"],"status":r["status"],"elapsed_wall_seconds":r["elapsed_wall_seconds"],
        **r.get("tiers",{}),"physical_wall_seconds":r.get("physical_wall_seconds"),"physical_waited_child_cpu_seconds":r.get("physical_waited_child_cpu_seconds"),"queue_wait_seconds":r.get("queue_wait_seconds")} for r in evaluations]
    summary={"phase":"development_E1_composition_pilot","task":"mirror_anchor","method":args.method,"trial":1,"model_session_id":session["session_id"],
        "actions":actions,"rejections":rejections,"resource_curve":curve,"actual_N_z":len(evaluations),"usage":session["usage"],"error":error,
        "elapsed_wall_seconds":time.monotonic()-started,"output":str(out),"formal_trials":0,"training_examples":0}
    (out/"calibration.json").write_text(json.dumps(summary,indent=2)+"\n");print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True)
    m.add_argument("--prepare-primitives",action="store_true");m.add_argument("--prepare-bundle",type=Path);m.add_argument("--evaluate",action="store_true");m.add_argument("--policy",action="store_true")
    p.add_argument("--method",choices=["G0","G1","G2"]);p.add_argument("--bundle",type=Path);p.add_argument("--source",type=Path)
    p.add_argument("--gold-control",type=Path,help="Backend-only known GDS evaluator control, never a composition policy candidate")
    p.add_argument("--deadline-utc",help="Absolute UTC deadline required for policy runs; also checked on the physical host before launch")
    p.add_argument("--public-bundle",type=Path);p.add_argument("--fidelity",choices=["basic","pex_spice"],default="pex_spice");a=p.parse_args()
    if a.prepare_primitives:prepare_primitives()
    elif a.prepare_bundle:prepare_bundle(a.prepare_bundle)
    elif a.evaluate:evaluate(a)
    else:
        if not a.deadline_utc:p.error("--policy requires an explicit frozen --deadline-utc")
        run_policy(a)
