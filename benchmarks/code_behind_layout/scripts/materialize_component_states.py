#!/usr/bin/env python3
"""Materialize distinct development source states, never additional lineages."""
import argparse,difflib,json,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import copy_declared_files

def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('Expected one declared source mutation: '+old)
    return source.replace(old,new)

def variants(kind,source):
    rows=[('natural_quality','natural_clean_but_poor',source,None)]
    if kind=='mirror':
        line=next(line for line in source.splitlines(keepends=True) if 'interdigitized_fets << L_route' in line)
        rows.append(('reference_link_open','predeclared_injection',replace_once(source,line,''),'Remove the rendered reference gate-drain link; intended N(z) unchanged'))
        rows.append(('source_bus_open','predeclared_injection',replace_once(source,'source_short = interdigitized_fets << c_route','source_short = c_route'),'Construct but omit rendering the source bus; ports remain available'))
    elif kind=='pair':
        rows.append(('gate_branch_open','predeclared_injection',replace_once(source,'PLUSgate_routeE = diffpair << c_route','PLUSgate_routeE = c_route'),'Construct but omit rendering one plus-gate branch'))
        rows.append(('drain_branch_open','predeclared_injection',replace_once(source,'drain_routeTR_BL = diffpair << c_route','drain_routeTR_BL = c_route'),'Construct but omit rendering one drain branch'))
    elif kind=='tg':
        line=next(line for line in source.splitlines(keepends=True) if 'top_level << c_route' in line and 'multiplier_0_drain_W' in line)
        rows.append(('drain_bridge_open','predeclared_injection',replace_once(source,line,''),'Omit the NMOS-PMOS output bridge'))
        old='pfet_ref.movey(nfet_ref.ymax + evaluate_bbox(pfet_ref)[1]/2 + pdk.util_max_metal_seperation())'
        rows.append(('placement_overlap','predeclared_injection',replace_once(source,old,old.replace('+ pdk.util_max_metal_seperation()', '- pdk.util_max_metal_seperation()')),'Reverse the declared inter-device spacing margin'))
    else:
        historical=subprocess.check_output(['git','-C',str(ROOT/'vendor/glayout'),'show','53786a8:src/glayout/cells/elementary/FVF/fvf.py'],text=True)
        rows.append(('historical_route','historical_natural_unqualified',historical,'Actual historical source53786a8; commit claims are not physical evidence'))
        line=next(line for line in source.splitlines(keepends=True) if 'top_level << c_route' in line and 'drain_1_via.ports["top_met_S"]' in line)
        rows.append(('feedback_open','predeclared_injection',replace_once(source,line,''),'Omit the drain-to-feedback-gate route'))
    return rows

def materialize(preparation):
    out=ROOT/'runtime/task_preparation'/('component_states_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,mode=0o700);records=[]
    for kind in ('mirror','pair','tg','follower'):
        original=Path(preparation)/'private'/kind;task=json.loads((original/'task.json').read_text())
        names=sorted(set(task['frozen_source_files'])|set(task['editable_paths']))
        if len(task['editable_paths'])!=1:raise ValueError('Expected one complete editable module')
        name=task['editable_paths'][0];source=(original/'source_pack'/name).read_text();seen=[]
        for suffix,origin,text,description in variants(kind,source):
            compile(text,name,'exec')
            if text in seen:raise ValueError('Initial source states must differ in bytes')
            seen.append(text);ident=kind+'_'+suffix;state=out/ident;pack=state/'source_pack';copy_declared_files(original/'source_pack',names,pack)
            target=pack/name;target.chmod(0o644);target.write_text(text);target.chmod(0o444)
            patch=''.join(difflib.unified_diff(source.splitlines(keepends=True),text.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name))
            (state/'initial_state.diff').write_text(patch)
            record={'initial_state_id':ident,'kind':kind,'parent_lineage':task['parent_lineage'],'source_dependency_group':task['source_dependency_group'],
                'origin':origin,'source_origin_revision':'53786a8' if suffix=='historical_route' else task['source_revision'],
                'description':description or task['natural_shortfall']['description'],'editable_paths':[name],
                'base_source_pack':str(original/'source_pack'),'source_pack':str(pack),'source_files':names,
                'source_snapshot':{name:text},'initial_patch':patch,'domain_template_private':str(original/'task.json'),
                'independent_reference_binding':'Unchanged per-configuration intended devices/widths/lengths/multipliers/ports; never generated from edited source',
                'objective':task.get('configurations',[{}])[0].get('contract',{}).get('objective'),
                'formal_admission':False,'formal_trials':0,'training_examples':0,
                'physical_qualification':'NOT_RUN','freeze_blockers':['Actual initial-state physical anchor required','Complete 25-point reference-bound domain and baseline required','Same-core feasible source edit witness required','Common1024/8192 context and UTC budget task packet must be frozen']}
            (state/'initial_state.json').write_text(json.dumps(record,indent=2)+'\n');records.append(record)
    record={'phase':'development_distinct_component_initial_states','directory':str(out),'states':records,
        'source_bodies':4,'source_dependency_groups':1,'initial_states':len(records),'formal_admitted_tasks':0,
        'natural_current_states':4,'historical_natural_unqualified_states':1,'predeclared_injected_states':7,
        'notes':['No source count is increased by an initial state','Historical commit messages do not establish a defect','Natural current source bytes are shared with existing measured baselines; changed injection/historical states require new evidence']}
    (out/'initial_states.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'directory':str(out),'states':len(records),'natural_current':4,'historical_unqualified':1,'injected':7}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);a=p.parse_args();materialize(a.preparation)
