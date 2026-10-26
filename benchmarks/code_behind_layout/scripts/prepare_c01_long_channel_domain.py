"""Predeclare one complete long-channel nf grid; never simulate or select points."""
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def main():
    prior=ROOT/'configs/development/c01_per_device_nf_family'
    table=json.loads((prior/'configurations.json').read_text())
    out=ROOT/'configs/development/c01_per_device_nf_long_family'
    if out.exists():raise FileExistsError('Do not alter a declared grid after measurements')
    (out/'references').mkdir(parents=True);(out/'contracts').mkdir()
    (out/'circuit_input.json').write_bytes((prior/'circuit_input.json').read_bytes())
    points=[]
    for old in table['configurations']:
        identifier='long_'+old['configuration_id'];sizing={name:{**value,'w':15.0,'l':3.0} for name,value in old['parameters']['sizing'].items()}
        original=(ROOT/old['reference_file']).read_text()
        def scale(match):return match.group(1)+'='+format(Decimal(match.group(2))*5,'f')
        reference=re.sub(r'\b([wl])=([0-9.eE+-]+)',scale,original)
        n=sum(value['nf'] for value in sizing.values())
        if reference.count(' l=3.0')!=n or len([line for line in reference.splitlines() if line.startswith('XM')])!=n:
            raise ValueError('Preserve each actual expanded finger while scaling W/L together by five')
        ref=out/'references'/(identifier+'.spice');ref.write_text(reference)
        contract=json.loads((ROOT/old['contract_file']).read_text());contract.update(task_id='development_train_domain_c01_long_nf',configuration_id=identifier,
            reference_id='c01_long_'+old['configuration_id']+'_perfinger',scope='DRAFT_PREDECLARED_LONG_CHANNEL_IDEAL_QUALIFICATION_PENDING',
            sizing_semantics={'total_width_um':15.0,'length_um':3.0,'nf':{name:value['nf'] for name,value in sizing.items()},
                'per_finger_width_um':{name:15/value['nf'] for name,value in sizing.items()},'matched_ratio':'1:1','total_W_over_L':5.0})
        file=out/'contracts'/(identifier+'.json');file.write_text(json.dumps(contract,indent=2)+'\n')
        points.append({'configuration_id':identifier,'role':old['role'],'parameters':{'circuit_id':'C01','sizing':sizing},
            'reference_file':str(ref.relative_to(ROOT)),'contract_file':str(file.relative_to(ROOT)),
            'same_nf_pair_as':old['configuration_id'],'grouping_expectation':old['predicted_grouping']})
    result={'status':'DRAFT_NOT_APPROVED_NOT_SIMULATED','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'source_revision':table['source_revision'],'parent_lineage':table['parent_lineage'],'source_lineages':1,'circuit_id':'C01',
        'development_domain_id':'C01_long_channel_per_device_nf','circuit_input_file':str((out/'circuit_input.json').relative_to(ROOT)),
        'configurations':points,'nf_grid':{'M1':[2,4,6],'M2':[2,4,6]},
        'hypothesis':'Scale original totalW3/L.6 together by five to totalW15/L3, preserving total W/L5 while changing physical channel length and per-finger widths to2.5/3.75/7.5um. No electrical equivalence or qualification is assumed.',
        'application_and_bench_unchanged':['20uA reference','1.8V supply','27C','tt/ss/ff','0.9V nominal output','complete0..1.8V/.1V DC','5percent nominal and .7..1.0V sampled compliance error','ro>=300kohm','original AC/transient analyses and tight tolerances'],
        'domain_selection_rule':'All nine nf pairs fixed before any new simulation; no post-result screening or adaptive resizing.',
        'causal_limitations':'Original ideal narrow-width-partition failures precede RC; internal BSIM gm/gds/vth/vdsat absent. Existing wide-domain failure causes require its raw fields, not inference from its1/9 summary.',
        'requires_root_approval_before_one_complete_ideal_nine_point_run':True,'layout_prohibited_before_whole_ideal_domain_qualified':True,
        'old_results_contracts_or_training_labels_changed':False,'new_model_calls':0,'new_physical_calls':0,'new_training_examples':0}
    (out/'configurations.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'table':str(out/'configurations.json'),'points':len(points),'model_or_physical_calls':0,'approval':'REQUIRED_BEFORE_IDEAL_RUN'}))


if __name__=='__main__':main()
