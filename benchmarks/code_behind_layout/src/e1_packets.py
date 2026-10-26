"""Draft matched E1 packets and readonly graph-to-primitive binding.

The backend reads an independent flat reference for the current configuration.
Policy code cannot provide or edit that input. This module imports no layout
assembly and is deliberately limited to the MOS/MIM models used by the study.
"""
import math
import re
from collections import OrderedDict
from pathlib import Path

from src.model_adapter import PACKET_FIELDS

MOS_MODELS={'sky130_fd_pr__nfet_01v8':'nmos','sky130_fd_pr__pfet_01v8':'pmos'}
MIM_MODEL='sky130_fd_pr__cap_mim_m3_1'
PUBLIC_CONTRACT_FIELDS=('task_id','configuration_id','reference_id','required_corners',
    'specifications','objective','analysis_contracts','immutable_parameters',
    'strict_development_predicate','numeric_options')
PORT_FIELDS=['terminal','direction','x_um','y_um','width_um','orientation_degrees','gds_layer','datatype']
HISTORY_POLICY={'version':'current_source_and_feedback_v1',
    'current_state':'Every decision receives the complete current editable source, physical contract, effective PDK rules and interface.',
    'history':'Remove historical read_source.content and historical action.patch payloads only. Preserve every physical feedback/error/action summary and count verbatim. Preserve raw histories separately.',
    'consumer':'Every adapter.step receives current_sources containing the complete current text for every visible source path, read from the trusted workspace.',
    'limits':'8192 total common-tokenizer tokens including1024 reserved output; reject overflow without truncating source or core rules.'}


def bind_reference(text,top_name,reference_id):
    """Bind actual per-finger dimensions and connectivity, never a candidate graph."""
    lines=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('*')]
    headers=[line.split() for line in lines if line.lower().startswith('.subckt ')]
    if len(headers)!=1 or headers[0][1]!=top_name:raise ValueError('Expected one independent flat circuit with the declared top')
    ports=headers[0][2:];groups=OrderedDict();instance_names=set()
    for line in lines:
        if line.startswith('.'):continue
        tokens=line.split();name=tokens[0]
        if not name.upper().startswith('X') or name.casefold() in instance_names:raise ValueError('Expected distinct flat model instances')
        instance_names.add(name.casefold())
        if len(tokens)>5 and tokens[5] in MOS_MODELS:
            model=tokens[5];nodes=tokens[1:5];terminals=['D','G','S','B'];params=tokens[6:];kind=MOS_MODELS[model]
        elif len(tokens)>3 and tokens[3]==MIM_MODEL:
            model=tokens[3];nodes=tokens[1:3];terminals=['P','N'];params=tokens[4:];kind='mimcap'
        else:raise ValueError('Reference uses a primitive outside the declared study interface')
        values={}
        for parameter in params:
            key,value=parameter.lower().split('=',1)
            if key not in ('w','l','m') or key in values:raise ValueError('Undeclared or duplicate primitive parameter')
            values[key]=float(value)
        if not {'w','l'}<=set(values) or not all(math.isfinite(v) and v>0 for v in values.values()):raise ValueError('Primitive dimensions must be positive finite micrometres')
        count=values.get('m',1.)
        if int(count)!=count or (kind=='mimcap' and count!=1):raise ValueError('Current interface requires integral MOS multiplicity and one MIM plate pair')
        key=(kind,model,tuple(n.casefold() for n in nodes),values['w'],values['l'])
        if key not in groups:groups[key]={'kind':kind,'model':model,'nets':dict(zip(terminals,nodes)),
            'width_um':values['w'],'length_um':values['l'],'parallel_devices':0,'reference_instances':[]}
        groups[key]['parallel_devices']+=int(count);groups[key]['reference_instances'].append(name)
    if not groups:raise ValueError('The circuit has no declared primitives')
    primitives=[];specs={};instances=[]
    for index,row in enumerate(groups.values()):
        key=(row['kind'],row['model'],row['width_um'],row['length_um'],row['parallel_devices'])
        if key not in specs:
            ident='primitive_%02d'%len(specs);specs[key]=ident
            spec={k:row[k] for k in ('kind','model','width_um','length_um')}
            spec.update(primitive_id=ident,units='um')
            if row['kind']=='mimcap':spec['model_pin_order']=['P_top_plate','N_bottom_plate']
            else:spec.update(fingers=row['parallel_devices'],multipliers=1,with_dummy=False,with_tie=True,with_substrate_tap=False,with_dnwell=False)
            primitives.append(spec)
        instances.append({'instance_id':'device_%02d'%index,'primitive_id':specs[key],'nets':row['nets'],
            'reference_instances':row['reference_instances'],'parallel_devices':row['parallel_devices']})
    return {'binding':'independent_readonly_reference','reference_id':reference_id,'top_cell':top_name,'ports':ports,
        'primitives':primitives,'instances':instances,'expanded_MOS_count':sum(r['parallel_devices'] for r in groups.values() if r['kind']!='mimcap'),
        'MIM_count':sum(r['parallel_devices'] for r in groups.values() if r['kind']=='mimcap')}


def empty_scaffold(top_name):
    if not re.fullmatch('[A-Za-z0-9_$]+',top_name):raise ValueError('Unsupported target identifier')
    return ('import argparse,json\nimport gdstk\np=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output")\n'
        'a=p.parse_args();configuration=json.load(open(a.configuration))\nlibrary=gdstk.Library();top=library.new_cell('+repr(top_name)+')\n'
        '# Construct the declared circuit using the permitted interface.\nlibrary.write_gds(a.output)\n')


def public_graph(graph):
    """Represent the complete circuit once with fixed shared table schemas."""
    specs=graph['primitives']
    return {**{k:graph[k] for k in ('binding','reference_id','top_cell','ports','expanded_MOS_count','MIM_count')},
        'units':'um','models':{**{kind:model for model,kind in MOS_MODELS.items()},'mimcap':MIM_MODEL},
        'primitive_fields':['primitive_id','kind','width_per_finger_um','length_um','parallel_fingers'],
        'primitives':[[p['primitive_id'],p['kind'],p['width_um'],p['length_um'],p.get('fingers',1)] for p in specs],
        'MOS_defaults':{'multipliers':1,'with_dummy':False,'with_tie':True,'with_substrate_tap':False,'with_dnwell':False},
        'MOS_terminal_order':['D','G','S','B'],'MIM_terminal_order':['P_top_plate','N_bottom_plate'],
        'instance_fields':['instance_id','primitive_id','ordered_nets'],
        'instances':[[p['instance_id'],p['primitive_id'],list(p['nets'].values())] for p in graph['instances']],
        'runtime':'configuration.graph and /library/manifest.json contain the same graph as full named records; this table repeats no default fields.'}


def public_cells(cells):
    """Lossless physical-resolution table: every actual port, no repeated labels."""
    layers=sorted({tuple(row[6:8]) for cell in cells for row in cell['terminal_access']})
    def nm(value):
        number=round(value*1000,3)
        return int(number) if number==int(number) else number
    compact={}
    orientations={'N':90,'E':0,'S':270,'W':180}
    for cell in cells:
        rows=cell['terminal_access'];terminals=['P','N'] if len(rows)==8 else ['D','G','S','B']
        expected=[(t,d) for t in terminals for d in 'NESW']
        if [tuple(row[:2]) for row in rows]!=expected:raise ValueError('Unexpected actual terminal access ordering')
        if any(row[5]!=orientations[row[1]] for row in rows):raise ValueError('Actual port orientation differs from cardinal access')
        paired=[]
        for terminal in terminals:
            n,e,s,w=[row for row in rows if row[0]==terminal]
            center=[(n[i]+s[i])/2 for i in (2,3)]
            if any(abs((e[i]+w[i])/2-center[i-2])>1e-9 for i in (2,3)) or n[4:]!=[s[4],n[5],*s[6:]] or e[4:]!=[w[4],e[5],*w[6:]]:
                raise ValueError('Actual terminal does not have the declared twofold port symmetry')
            paired.append([nm(v) for v in center+[n[2]-center[0],n[3]-center[1],n[4]]]+[layers.index(tuple(n[6:8]))]+
                [nm(v) for v in [e[2]-center[0],e[3]-center[1],e[4]]]+[layers.index(tuple(e[6:8]))])
        compact[cell['primitive_id']]={'bbox_um':cell['bbox_um'],'terminal_pairs':paired}
    return {'layers':layers,'terminal_pair_fields':['center_x_nm','center_y_nm','N_dx_nm','N_dy_nm','N_width_nm','N_S_layer_index','E_dx_nm','E_dy_nm','E_width_nm','E_W_layer_index'],
        'terminal_order':{'MOS':['D','G','S','B'],'MIM':['P','N']},
        'reconstruction':'For each terminal, N=center+(N_dx,N_dy), S=center-(N_dx,N_dy); E=center+(E_dx,E_dy), W=center-(E_dx,E_dy). Paired widths/layers are identical and verified against every original actual port. All16 MOS or8 MIM ports are represented.',
        'MOS_access_order':[t+'_'+d for t in ['D','G','S','B'] for d in 'NESW'],
        'MIM_access_order':[t+'_'+d for t in ['P','N'] for d in 'NESW'],
        'orientation_degrees':orientations,'cell_and_GDS_name':'primitive_id and primitive_id+.gds',
        'cells':compact,'precision':'Coordinates represented to .001nm; below the physical1nm GDS resolution. Original full metadata stays in each readonly library.'}


def public_sizings(points):
    names=list(points[0]['parameters'])
    if any(set(p['parameters'])!=set(names) for p in points):raise ValueError('Expected one full parameter schema in a task family')
    fixed={name:points[0]['parameters'][name] for name in names
        if all(p['parameters'][name]==points[0]['parameters'][name] for p in points)}
    variable=[name for name in names if name not in fixed]
    return {'fixed_parameters':fixed,'variable_parameter_names':variable,
        'configurations':{p['configuration_id']:[p['parameters'][name] for name in variable] for p in points},
        'meaning':'Every sizing is fixed_parameters merged with this row under variable_parameter_names; no parameter is omitted.'}


def policy_packet(task,method,*,pdk,anchor_graph,anchor_primitives=None,reuse_api=None,budget=None):
    """Whitelist public fields; task ancestry, oracle patches and hidden rows stay out."""
    if method not in ('G0','G1','G2') or task['stratum'] not in ('reuse','composition'):raise ValueError('Unknown E1 representation or stratum')
    public_contract={key:task['anchor_contract'][key] for key in PUBLIC_CONTRACT_FIELDS if key in task['anchor_contract']}
    source=empty_scaffold(task['top_cell'])
    documents={'status':'DRAFT_E1_FAMILY_PACKET','stratum':task['stratum'],'history_policy':HISTORY_POLICY,
        'PDK':pdk,'intended_anchor_graph':public_graph(anchor_graph),
        'visible_sizings':public_sizings(task['visible_configurations']),
        'CLI':'python generator.py --configuration PATH --output PATH. Emit only candidate.gds. Read graph from configuration["graph"], immutable sizing from configuration["parameters"], and numeric layers/rules from configuration["pdk_rules"]. The graph dimensions and intended nets are immutable.',
        'target_selection':'The contract-named target must exist exactly once; its complete referenced hierarchy and recursive bbox are evaluated. Unreferenced cells are allowed. All cell/label names use ASCII letters/digits/_/$.',
        'geometry_units':'Micrometres, .005um construction grid. MOS width is per finger; each supplied MOS PCell has exactly the declared fingers, no hidden dummy.',
        'patch_format':'Ordinary unified diff for a/generator.py and b/generator.py, accurate hunk counts and final newline.',
        'fidelity':'Actual full DRC, independent fixed-reference LVS, positive unsimplified RC and all required SPICE analyses determine S0/S1/S2.'}
    if task.get('application'):
        documents['application']={k:v for k,v in task['application'].items()
            if k not in ('existing_development_feasibility','bench_source_unchanged')}
    if task.get('shared_domain_id'):
        documents['family_relationship']={'shared_domain_id':task['shared_domain_id'],
            'note':'Three sized task families share this target logic and its declared domain. A fresh trial has one fixed visible/hidden assignment; configurations are not independent circuits.'}
    if method=='G0':documents['API']='gdstk/numpy/math and generic Python only. Construct complete geometry from the common PDK rules and graph-derived device definitions; no PCell/GDS library or circuit generator is mounted.'
    else:
        if not anchor_primitives:raise ValueError('G1/G2 packets require actual graph-bound anchor primitive metadata')
        documents['primitive_interface']={'manifest':'/library/manifest.json','generation':'A new readonly library is bound to the current z by the backend, not only the anchor. Candidate code loads that current manifest; cells differ with actual W/L/finger/MIM dimensions.',
            'port_fields':PORT_FIELDS,'MOS_terminal_access':'Four D/G/S/B terminals, four actual N/E/S/W access ports per terminal.',
            'MIM_terminal_access':'Two real P(top/model pin1) and N(bottom/model pin2) plates, with actual cardinal access; no invented body terminals.',
            'anchor_cells':public_cells(anchor_primitives)}
        documents['API']='G0 geometry API plus readonly generic MOS/MIM GDS and compact terminal metadata. No target assembly is present in this primitive library.'
    if method=='G2':
        documents['API']+=' Also gdsfactory Component/import_gds/Port and explicitly cropped common placement/port/routing/via utilities.'
        documents['routing_API']='from glayout import sky130; from glayout.routing.straight_route import straight_route; from glayout.routing.L_route import L_route; from glayout.routing.c_route import c_route; from glayout.primitives.via_gen import via_stack. straight_route(sky130,port1,port2,width=.3), L_route(sky130,port1,port2), c_route(sky130,port1,port2,extension=2), via_stack(sky130,glayer1="met2",glayer2="met3",fullbottom=True,fulltop=True) return Components. Reconstruct gdsfactory.port.Port(name,center,width,orientation,layer) from actual access rows, translate with the PCell reference, and add returned route Components. Component references support move/movex/movey; glayout.util.comp_utils supplies align_comp_to_port.'
        if task['stratum']=='reuse':
            if not reuse_api:raise ValueError('A reuse packet must declare its concrete additional block API')
            documents['reuse_blocks']=reuse_api;documents['knowledge_benefit']='Explicit higher-level prior layout knowledge is supplied in this reuse stratum; this is separate from the composition comparison.'
        else:documents['composition_boundary']='No target generator, complete target cell or equivalent target assembly is mounted. Only the generic primitive library and common utilities are available.'
    limits={'decisions':10,'physical_evaluations':3,'wall_seconds':1200,'deadline_utc':None,
        'maximum_context_tokens':8192,'maximum_output_tokens':1024,**(budget or {})}
    result={'task_id':task['task_id'],'goal':'Construct the independent intended '+task['target']+' circuit as one shared parameter-aware generator across the declared family using '+method+'.',
        'contract':public_contract,'allowed_paths':['generator.py'],'visible_sources':{'generator.py':source},
        'documents':documents,'visible_configurations':[r['configuration_id'] for r in task['visible_configurations']],'budget':limits}
    if set(result)!=PACKET_FIELDS:raise AssertionError('Packet whitelist drifted')
    return result
