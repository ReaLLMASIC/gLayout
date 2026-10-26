#!/usr/bin/env python3
"""Backend-only generic MOS/MIM library generation from independent N(z)."""
import argparse,json,math,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))
from src.e1_packets import bind_reference,PORT_FIELDS


def prepare(reference,top_name,reference_id,output):
    import gdstk
    from glayout import sky130
    from glayout.primitives.fet import nmos,pmos
    from glayout.primitives.mimcap import mimcap
    out=Path(output);out.mkdir(parents=True,exist_ok=False);raw=out.parent/(out.name+'_raw');raw.mkdir()
    started=time.monotonic();cpu=time.process_time();graph=bind_reference(Path(reference).read_text(),top_name,reference_id)
    for specification in graph['primitives']:
        if specification['kind']!='mimcap':
            for field in ('width_um','length_um'):
                requested=specification[field];actual=sky130.snap_to_2xgrid(requested)
                if not math.isclose(actual,requested,rel_tol=0,abs_tol=1e-12):
                    raise ValueError('The declared MOS '+field+'='+str(requested)+'um is not exactly expressible by the pinned common PCell; it would snap upward to '+str(actual)+'um. Change a prospective legal domain explicitly; never substitute gold dimensions.')
    remove=[sky130.get_glayer(k) for k in sky130.glayers if k.endswith(('_label','_pin'))]+[(64,44)]
    cells=[]
    for spec in graph['primitives']:
        began=time.monotonic();used=time.process_time();ident=spec['primitive_id']
        if spec['kind']=='mimcap':
            cell=mimcap(sky130,size=(spec['width_um'],spec['length_um'])).copy()
            names={terminal:{direction:prefix+direction for direction in 'NESW'} for terminal,prefix in [('P','top_met_'),('N','bottom_met_')]}
        else:
            arguments=dict(width=spec['width_um'],length=spec['length_um'],fingers=spec['fingers'],multipliers=1,
                with_dummy=False,with_tie=True,with_substrate_tap=False)
            cell=(nmos(sky130,with_dnwell=False,**arguments) if spec['kind']=='nmos' else pmos(sky130,dnwell=False,**arguments)).copy()
            names={terminal:{direction:'multiplier_0_'+name+'_'+direction for direction in 'NESW'}
                for terminal,name in [('D','drain'),('G','gate'),('S','source')]}
            names['B']={direction:'tie_'+direction+'_top_met_'+direction for direction in 'NESW'}
        original={name:{'center_um':list(map(float,p.center)),'width_um':float(p.width),
            'orientation_degrees':float(p.orientation),'layer':list(p.layer)} for name,p in cell.ports.items()}
        rows=[]
        for terminal,access in names.items():
            for direction,name in access.items():
                port=original[name];values=port['center_um']+[port['width_um'],port['orientation_degrees']]
                if not all(math.isfinite(v) for v in values) or port['width_um']<=0:raise ValueError('Invalid actual PCell terminal')
                rows.append([terminal,direction,*port['center_um'],port['width_um'],port['orientation_degrees'],*port['layer']])
        cell=cell.remove_layers(remove,include_labels=True);cell.name=ident
        path=out/(ident+'.gds');cell.write_gds(path)
        library=gdstk.read_gds(path);flat,=library.top_level();flat.flatten();flat.name=ident
        canonical=gdstk.Library(unit=library.unit,precision=library.precision);canonical.add(flat);canonical.write_gds(path)
        bbox=flat.bounding_box();scale=canonical.unit/1e-6
        metadata={'primitive_id':ident,'cell':ident,'gds':path.name,'specification':spec,'units':'um',
            'bbox_um':[[float(v*scale) for v in point] for point in bbox],'terminal_access':rows,
            'port_count':len(rows),'internal_labels_removed':True,'target_assembly':False}
        (out/(ident+'.json')).write_text(json.dumps(metadata,separators=(',',':'))+'\n')
        (raw/(ident+'_all_ports.json')).write_text(json.dumps(original,indent=2)+'\n')
        cells.append(metadata)
        (raw/(ident+'_generation_cost.json')).write_text(json.dumps({'wall_seconds':time.monotonic()-began,
            'process_CPU_seconds':time.process_time()-used,'GPU_seconds':0})+'\n')
    result={'interface_version':'e1_graph_bound_pcell_draft_v1','binding':'independent_readonly_reference',
        'reference_id':reference_id,'graph':graph,'port_fields':PORT_FIELDS,'cells':cells,
        'generation_cost':{'wall_seconds':time.monotonic()-started,'process_CPU_seconds':time.process_time()-cpu,'GPU_seconds':0},
        'target_assembly_present':False,'sizing_source':'Backend frozen reference; candidate input is never accepted'}
    (out/'manifest.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    for p in out.iterdir():p.chmod(0o444)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--top',required=True);p.add_argument('--reference-id',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=prepare(a.reference,a.top,a.reference_id,a.output)
    print(json.dumps({'library':str(a.output),'primitive_count':len(result['cells']),'generation_cost':result['generation_cost']}),flush=True)
