"""Audit original sampled diffs with the same patch gateway; never repair them."""
import argparse,json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import apply_source_patch
p=argparse.ArgumentParser(description=__doc__);p.add_argument('pool',type=Path);a=p.parse_args()
d=json.loads(a.pool.read_text());paths=d['identical_request']['task_packet']['allowed_paths']
if paths!=['textbook_sharing/layout.py']:raise ValueError('This actual pilot edits the complete layout module only')
result={'scope':'development_original_model_diff_audit_not_training','completed_requests':len(d['candidates']),'valid_diff':0,'changed_proposals':0,'distinct_changed_sources':0,'noops':[],'invalid':[],'source_groups':[]}
seen={}
for row in d['candidates']:
 with tempfile.TemporaryDirectory(prefix='cbl-corpus-') as tmp:
  root=Path(tmp);target=root/paths[0];target.parent.mkdir();target.write_text(d['editable_source'])
  try:apply_source_patch(root,row['patch'],paths)
  except (ValueError,subprocess.CalledProcessError) as exc:
   result['invalid'].append({'candidate_id':row['candidate_id'],'error':str(exc),'stderr':getattr(exc,'stderr','')});continue
  result['valid_diff']+=1;text=target.read_text()
  if text==d['editable_source']:result['noops'].append(row['candidate_id']);continue
  result['changed_proposals']+=1;seen.setdefault(text,[]).append(row['candidate_id'])
result['distinct_changed_sources']=len(seen);result['source_groups']=list(seen.values())
out=a.pool.with_name(a.pool.stem+'_patch_audit.json');out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
