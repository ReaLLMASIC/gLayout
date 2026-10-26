"""Declare development C05/C08 geometry domains and golds before generation."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
public=ROOT/'vendor/textbook-sharing-readonly'
revision=subprocess.check_output(['git','-C',str(public),'rev-parse','HEAD'],text=True).strip()
if revision!='1f90e33913208e572744b7c5a144a7da8c073235':raise ValueError('Public source revision changed')
sys.path.insert(0,str(public/'benchmarks/textbook_sharing'))
from textbook_sharing.netlist import Circuit,emit_subckt

inputs={'C05':ROOT/'runs/phase0/phase0_20261019T004102705242Z_corpus_yield_pilot/base_source',
        'C08':ROOT/'runs/phase0/phase0_20261018T234220871091Z_fvf_textbook_cropped_source_smoke/source_pack'}
points=[('anchor',1,.5,.3),('dev_nf_half',.5,.5,.3),('dev_nf_3quarters',.75,.5,.3),
        ('dev_nf_1half',1.5,.5,.3),('dev_nf_double',2,.5,.3),('dev_len045',1,.5,.45),
        ('dev_len060',1,.5,.6),('dev_unit075',1,.75,.3),('dev_unit100',1,1.,.3)]
for cid,source in inputs.items():
    root=ROOT/'configs/development'/(cid.lower()+'_family')
    if root.exists():raise ValueError('Preserve the previously declared domain: '+str(root))
    (root/'references').mkdir(parents=True);(root/'contracts').mkdir()
    circuit=Circuit.from_json(json.loads((source/'circuit_input.json').read_text()))
    nominal=json.loads((source/'sizing_input.json').read_text());rows=[]
    for name,scale,width,length in points:
        sizing={device:{'w':int(size['nf']*scale)*width,'l':length,'nf':int(size['nf']*scale)} for device,size in nominal.items()}
        if any(size['nf']*scale!=int(size['nf']*scale) for size in nominal.values()):raise ValueError('Fingers must remain integral and matched')
        reference=root/'references'/(name+'.spice');reference.write_text(emit_subckt('sky130',circuit,sizing,'corpus_'+cid.lower(),per_finger=True,lvs=True))
        contract={'task_id':'development_train_domain_'+cid,'configuration_id':name,'reference_id':cid.lower()+'_'+name+'_independent_perfinger',
            'required_corners':['tt','ss','ff'],'scope':'DRAFT_DEVELOPMENT_QUALIFICATION_NOT_FORMAL',
            'objective':{'id':cid.lower()+'_area_min','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'},
            'specifications':([{'name':'gain_10Hz_real','unit':'1','min':.6}] if cid=='C05' else [
                {'name':'gain_10Hz_dB','unit':'dB','min':25},{'name':'phase_margin_deg','unit':'deg','min':60},{'name':'settled_tracking_error_V','unit':'V','max':.015}]),
            'pending_before_freeze':['bandwidth_floor_Hz_from_actual_baseline_qualification','DUT_supply_power_ceiling_W_from_actual_baseline_qualification'],
            'power_definition':'VSUPPLY supplies DUT only; separate VBIASSUPPLY feeds external diode replica. Power is -1.8*i(VSUPPLY).',
            'nominal_operating_point':{'supply_V':1.8,'temperature_C':27,'input_V':1.17 if cid=='C05' else .9,'load_C_F':1e-12,'replica_current_A':20e-6 if cid=='C05' else 40e-6},
            'analysis_contracts':{'op':{'kind':'op','columns':4,'expected_rows':1},
                'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':161 if cid=='C05' else 241,'scale':'log'},
                'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6]] if cid=='C05' else [[1.8e-6,1.99e-6],[2.8e-6,2.99e-6]]},
                'dc':{'kind':'dc','columns':3,'start':.8 if cid=='C05' else .6,'end':1.4 if cid=='C05' else 1.2,'points':13 if cid=='C05' else 7,'scale':'linear'}}}
        contract_path=root/'contracts'/(name+'.json');contract_path.write_text(json.dumps(contract,indent=2)+'\n')
        rows.append({'configuration_id':name,'role':'anchor' if name=='anchor' else 'development','parameters':{'sizing':sizing},
            'reference_file':str(reference.relative_to(ROOT)),'contract_file':str(contract_path.relative_to(ROOT))})
    table={'scope':'development_only_train_domain_qualification_not_frozen','source_revision':revision,
        'parent_lineage':'textbook_universal_compiler_cropped','circuit_id':cid,'configurations':rows,
        'identity_note':'One universal compiler lineage; geometry points are not independent source programs. No old data are relabeled.'}
    (root/'configurations.json').write_text(json.dumps(table,indent=2)+'\n');print(json.dumps({'circuit':cid,'table':str(root/'configurations.json'),'points':len(rows),'status':'DRAFT_NOT_LAUNCHED'}))
