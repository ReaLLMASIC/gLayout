"""Check the literal flat SKY130 device graph independently of LVS merging.

The study's independent references and Magic ext2spice LVS outputs use bare
micrometre W/L values. This is deliberately not a general SPICE elaborator.
Expand parallel multiplicity before matching devices and their terminals. This
preserves per-finger dimensions on each branch, which a parallel merge obscures.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def flat_device_inventory(text):
    lines=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith(('*',';')):continue
        if line.startswith('+'):
            if not lines:raise ValueError('Continuation has no preceding literal line')
            lines[-1]+=' '+line[1:]
        else:lines.append(line)
    inventory=Counter();instances=[];ports=None;active=False;tops=0
    for line in lines:
        fields=line.split()
        if fields[0].lower()=='.subckt':
            tops+=1;active=True;ports=[p.upper() for p in fields[2:]];continue
        if fields[0].lower()=='.ends':active=False;continue
        if not active or fields[0].startswith('.'):continue
        if not fields[0].upper().startswith(('X','M')):
            raise ValueError('Study device type needs an explicit intent binding: '+fields[0])
        model_index=next((i for i,value in enumerate(fields) if value.lower().startswith('sky130_fd_pr__')),None)
        if model_index is None:raise ValueError('Reference/extraction is not a flat literal primitive netlist: '+fields[0])
        model=fields[model_index].lower()
        if 'nfet_' not in model and 'pfet_' not in model and 'cap_mim_' not in model:
            raise ValueError('Study device type needs an explicit intent binding: '+model)
        nodes=[value.upper() for value in fields[1:model_index]]
        expected_terminals=2 if 'cap_mim_' in model else 4
        if len(nodes)!=expected_terminals:
            raise ValueError('Unexpected primitive terminal count on '+fields[0])
        params={}
        for key,value in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s]+)', ' '.join(fields[model_index+1:])):
            key=key.lower()
            if key in params:raise ValueError('Duplicate device parameter: '+key)
            params[key]=value
        def literal(key,default=None):
            value=params.get(key,default)
            if value is None or not re.fullmatch(NUMBER,value):
                raise ValueError('Expected bare literal micrometre/multiplicity parameter '+key+' on '+fields[0])
            try:number=Decimal(value)
            except InvalidOperation as error:raise ValueError('Invalid literal dimension') from error
            if not number.is_finite() or number<=0:raise ValueError('Nonpositive device dimension/multiplicity')
            return number
        width,length=literal('w'),literal('l')
        multiplicity=literal('m','1');nf=literal('nf','1')
        if multiplicity!=multiplicity.to_integral_value() or nf!=nf.to_integral_value():
            raise ValueError('The fixed per-finger contracts require integral multiplicity and nf')
        # Magic emits micrometre dimensions with finite decimal precision. A
        # picometre key preserves every physically representable 1nm GDS step.
        key=(model,int((width*Decimal(1000000)).to_integral_value()),
             int((length*Decimal(1000000)).to_integral_value()),int(nf))
        inventory[key]+=int(multiplicity)
        instances.append({'name':fields[0],'model':model,'width_um':str(width),'length_um':str(length),
            'm':int(multiplicity),'nf':int(nf),'nodes':nodes,'device_key':key})
    if tops!=1 or not instances:raise ValueError('Exactly one nonempty flat literal primitive subcircuit is required')
    return {'counts':inventory,'instances':instances,'ports':ports}


def _device_graph(inventory):
    import networkx as nx
    graph=nx.MultiGraph()
    ports=set(inventory['ports'])
    for port in ports:
        graph.add_node(('net',port),color=('net',port))
    parallel=Counter()
    for instance in inventory['instances']:
        nodes=instance['nodes']
        signature=tuple(nodes) if 'cap_mim_' in instance['model'] else (tuple(sorted((nodes[0],nodes[2]))),nodes[1],nodes[3])
        parallel[(instance['device_key'],signature)]+=instance['m']
    for index,((key,signature),multiplicity) in enumerate(parallel.items()):
        mim='cap_mim_' in key[0]
        nodes=signature if mim else (signature[0][0],signature[1],signature[0][1],signature[2])
        roles=('positive','negative') if mim else ('sd','gate','sd','bulk')
        device=('device',index)
        # Compress only identical per-finger devices on identical terminals.
        # Multiplicity remains a required color, never an aggregate width.
        graph.add_node(device,color=('device',)+key+(multiplicity,))
        for net,role in zip(nodes,roles):
            graph.add_node(('net',net),color=('net',net if net in ports else ''))
            graph.add_edge(device,('net',net),role=role)
    return graph


def _graphs_match(extracted,reference):
    from networkx.algorithms.isomorphism import MultiGraphMatcher
    matcher=MultiGraphMatcher(_device_graph(extracted),_device_graph(reference),
        node_match=lambda left,right:left['color']==right['color'],
        edge_match=lambda left,right:Counter(edge['role'] for edge in left.values())==
                                    Counter(edge['role'] for edge in right.values()))
    return matcher.is_isomorphic()


def compare_device_intent(extracted_text,reference_text):
    extracted=flat_device_inventory(extracted_text);reference=flat_device_inventory(reference_text)
    def describe(counter):
        return [{'model':key[0],'width_pm':key[1],'length_pm':key[2],'nf':key[3],'count':count}
                for key,count in sorted(counter.items())]
    missing=reference['counts']-extracted['counts'];extra=extracted['counts']-reference['counts']
    ports_equal=(len(extracted['ports'])==len(reference['ports']) and set(extracted['ports'])==set(reference['ports']))
    graph_equal=not missing and not extra and ports_equal and _graphs_match(extracted,reference)
    return {'per_device_dimensions_match':not missing and not extra,'ports_match':ports_equal,
        'device_terminal_graph_match':graph_equal,'is_clean':graph_equal,'missing':describe(missing),'extra':describe(extra),
        'expected_expanded_devices':sum(reference['counts'].values()),'actual_expanded_devices':sum(extracted['counts'].values()),
        'reference_inventory':describe(reference['counts']),'extracted_inventory':describe(extracted['counts']),
        'scope':'Flat literal SKY130 MOS/MIM graph; W/L in micrometres, m expanded, nf retained. External ports, gate/bulk and MIM plate roles are fixed; internal nets may rename and MOS D/S may swap. Netgen remains independently required.'}
