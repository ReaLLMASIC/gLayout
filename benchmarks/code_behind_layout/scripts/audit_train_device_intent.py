"""Independently audit completed train-collection raw LVS netlists, without relabelling raw runs."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.device_intent import compare_device_intent
from src.training import TrustedPhysicalStore


def audit(root):
    rows=[]
    for manifest_path in sorted(root.glob('*/physical/*/manifest.json')):
        run=manifest_path.parent;manifest=json.loads(manifest_path.read_text())
        row={'collection_id':run.parent.parent.name,'run_id':manifest['run_id']}
        states=[manifest.get(stage,{}).get('container_state',{}).get('Running') for stage in ('candidate','trusted')]
        validation=run/'evidence/validation.json'
        if states!=[False,False] or not validation.is_file():
            rows.append(row|{'status':'NOT_COMPLETED_S1_EVIDENCE'});continue
        record=json.loads(validation.read_text())
        if record.get('assessment',{}).get('S1') is not True:
            rows.append(row|{'status':'NOT_CLAIMED_S1'});continue
        try:
            cid=manifest['context']['configuration_id'];ref='references/'+cid+'.spice'
            if ref not in manifest['trusted_files']:
                raise ValueError('Missing independently snapshotted per-configuration reference')
            lvs=record['artifacts']['lvs']
            if lvs.get('reference',ref)!=ref:raise ValueError('Unexpected reference binding')
            actual=TrustedPhysicalStore._file(run/'evidence',lvs.get('netlist','layout_lvs.spice'))
            gold=TrustedPhysicalStore._file(run/'trusted',ref)
            result=compare_device_intent(actual.read_text(),gold.read_text())
            rows.append(row|{'configuration_id':cid,'actual':str(actual),'independent_reference':str(gold),
                'status':'PASS' if result['is_clean'] else 'INTENT_MISMATCH','audit':result})
        except (ValueError,KeyError) as error:
            rows.append(row|{'status':'AUDIT_UNRESOLVED','error':str(error)})
    return {'scope':'Retrospective independent train raw-device audit; original outcomes and collection denominators unchanged',
        'at_utc':datetime.now(timezone.utc).isoformat(),'root':str(root.resolve()),
        'counts':dict(Counter(row['status'] for row in rows)),'rows':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=audit(a.root);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'output':str(a.output),'counts':report['counts']}))


if __name__=='__main__':main()
