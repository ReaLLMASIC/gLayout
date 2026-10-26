"""Declare the E4 pools file from the textbook collections and Claude acceptances present on this host (read-only scan).

Included:
  * rule collections runs/train_collection/<domain>_rules_v1 with completion_recovered.json (recovered candidate file) or a
    plain COMPLETED_INITIAL_BATCH completion (candidates.jsonl), excluding the two port-order rules of the v1 bench;
  * multi-state collections <domain>_{lattice,faults}_v2 that completed (candidates.jsonl; lattice order = its 4 rules);
  * Claude span acceptances runs/train_collection/*_physical_v2 whose state is COMPLETE (candidates.jsonl, trial order),
    with candidates flagged by the pin-order audit excluded when the parent used the v1 bench.
Collections still running or paused are listed under "skipped" and never included.

    runtime/training-venv/bin/python scripts/declare_e4_pools.py --output configs/training/e4_pools_<date>.json
"""
import argparse
import glob
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(p): return json.loads(Path(p).read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    pools = []; skipped = []
    for root in sorted(glob.glob(str(ROOT / 'runs/train_collection/c*_rules_v1'))) + sorted(glob.glob(str(ROOT / 'runs/train_collection/c*_lattice_v2'))) + sorted(glob.glob(str(ROOT / 'runs/train_collection/c*_faults_v2'))):
        root = Path(root); cid = root.name
        if cid in ('c01_rules_v1', 'c05_rules_v1', 'c08_rules_v1'): skipped.append({'id': cid, 'reason': 'earlier non-textbook-bench collection'}); continue  # the c01_cfg* parents are textbook-bench domains (same rule as the collection scheduler)
        manifest_path = root / 'collection_manifest.json'
        if not manifest_path.exists(): skipped.append({'id': cid, 'reason': 'no manifest'}); continue
        manifest = read(manifest_path); recovered = root / 'completion_recovered.json'; completion = root / 'completion.json'
        if recovered.exists(): candidates = 'candidates_recovered.jsonl'
        elif completion.exists() and read(completion).get('status') == 'COMPLETED_INITIAL_BATCH': candidates = 'candidates.jsonl'
        else: skipped.append({'id': cid, 'reason': 'not complete or not recovered: ' + str(read(completion).get('status') if completion.exists() else 'running')}); continue
        rules = manifest['sampling']['rule_ids']
        if not rules: skipped.append({'id': cid, 'reason': 'baseline-only collection (states enter through their Claude repair acceptance)'}); continue
        pool = {'id': cid, 'kind': 'rule_collection' if cid.endswith('_rules_v1') else 'multistate_collection', 'root': str(root.relative_to(ROOT)), 'candidates': candidates,
                'registry': 'effective_registry.json', 'label_rule': str(Path(manifest['label_rule_path']).relative_to(ROOT)), 'order_field': 'rule_id', 'declared_order': list(rules), 'evidence_relative_to_root': True}
        bench = Path(manifest['trusted_bundle']) / 'textbook_physical.py'
        pool['bench_binds_pins_by_extracted_order'] = bench.is_file() and 'def dut_line' in bench.read_text()
        if cid.endswith('_rules_v1') and not pool['bench_binds_pins_by_extracted_order']: pool['exclude_rules'] = ['reverse_port_track_order', 'reverse_ports_combined']
        pools.append(pool)
    for root in sorted(glob.glob(str(ROOT / 'runs/train_collection/textbook_claude_*_physical*'))):
        root = Path(root); cid = root.name; state = root / 'state.json'
        if not state.exists() or read(state).get('status') != 'COMPLETE': skipped.append({'id': cid, 'reason': 'acceptance not COMPLETE: ' + str(read(state).get('status') if state.exists() else 'absent')}); continue
        definition = read(root / 'acceptance.json'); plan = read(definition['proposal_collection'])
        parents = sorted({c['parent_collection'] for c in definition['contexts']})
        rules = [read(ROOT / 'runtime/train_collections' / p_ / 'label_rule.json') for p_ in parents]
        if len(parents) == 1: label_path = ROOT / 'runtime/train_collections' / parents[0] / 'label_rule.json'
        else:
            # one acceptance may cover several parent domains: union their per-domain objectives under identical shared settings
            merged = {**rules[0], 'objectives': {}, 'version': cid + '_merged_parent_rules_v1', 'parent_rule_versions': [r['version'] for r in rules]}
            for r in rules:
                if {k: r.get(k) for k in ('coverage_absolute_tolerance', 'family_quality_aggregation', 'status')} != {k: rules[0].get(k) for k in ('coverage_absolute_tolerance', 'family_quality_aggregation', 'status')}: raise ValueError('Parent label rules differ in shared settings: ' + cid)
                for name, definition_ in r['objectives'].items():
                    if merged['objectives'].get(name, definition_) != definition_: raise ValueError('Conflicting objective across parents: ' + name)
                    merged['objectives'][name] = definition_
            label_path = ROOT / 'configs/training/e4_pool_label_rules' / (cid + '.json'); label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_text(json.dumps(merged, indent=2) + '\n')
        pool = {'id': cid, 'kind': 'span_acceptance', 'root': str(root.relative_to(ROOT)), 'candidates': 'candidates.jsonl', 'registry': 'effective_registry.json',
                'label_rule': str(label_path.relative_to(ROOT)), 'order_field': 'trial_id', 'declared_order': list(definition['trials']),
                'evidence_relative_to_root': False, 'parents': parents}
        old_bench = any(not (Path(read(ROOT / 'runtime/train_collections' / p_ / 'collection.json')['trusted_bundle']) / 'textbook_physical.py').read_text().__contains__('def dut_line') for p_ in parents)
        pool['parents_use_v1_bench'] = old_bench
        if old_bench:
            audit = root / 'pin_order_audit.json'
            if not audit.exists():
                subprocess.run([sys.executable, str(ROOT / 'scripts/audit_textbook_pin_order.py'), '--root', str(root), '--output', str(audit)], check=True, stdout=subprocess.DEVNULL)
            pool['exclude_candidates'] = read(audit)['mismatched_candidates']; pool['audit'] = str(audit.relative_to(ROOT))
        pools.append(pool)
    a.output.write_text(json.dumps({'pools': pools, 'skipped': skipped}, indent=2) + '\n')
    print(json.dumps({'pools': [(p_['id'], p_['kind']) for p_ in pools], 'skipped': skipped}, indent=1)[:3000])


if __name__ == '__main__': main()
