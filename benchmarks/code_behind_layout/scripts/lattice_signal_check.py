"""Exit 0 when a domain's finished rule collection shows a plan-mode anchor-area improvement of at least --minimum (default 2%).

The lattice variants only matter where the sharing plans change the layout; for circuits whose plan rules leave the
anchor area within the frozen 1% minimum effect, no lattice state can produce an SFT target or a non-tie preference, so the
stage-2 waiter skips their lattice collections. Read-only.
"""
import argparse, glob, json, os, sys
p = argparse.ArgumentParser(description=__doc__); p.add_argument('domain'); p.add_argument('--minimum', type=float, default=0.02); a = p.parse_args()
root = 'runs/train_collection/%s_rules_v1' % a.domain.lower()
if not os.path.exists(root + '/completion.json'): print(json.dumps({'domain': a.domain, 'status': 'rules collection not finished'})); sys.exit(2)
base = None; best = None
for m in glob.glob(root + '/physical/executor_*/manifest.json'):
    mf = json.load(open(m)); ctx = mf.get('context', {})
    if not ctx.get('configuration_id', '').endswith('anchor'): continue
    v = os.path.join(os.path.dirname(m), 'evidence/validation.json')
    if not os.path.exists(v): continue
    val = json.load(open(v)); area = val['observation']['corners'].get('tt', {}).get('metrics', {}).get('area', {}).get('value')
    if area is None or not val['assessment']['S2']: continue
    cid = ctx['candidate_id']
    if cid.endswith('__baseline'): base = area
    elif any(k in cid for k in ('diffusion_plan', 'gate_plan', 'combined_plan')): best = area if best is None else min(best, area)
gain = (base - best) / base if base and best else None
print(json.dumps({'domain': a.domain, 'baseline_anchor_area': base, 'best_plan_anchor_area': best, 'improvement': gain, 'lattice_worthwhile': bool(gain is not None and gain >= a.minimum)}))
sys.exit(0 if gain is not None and gain >= a.minimum else 1)
