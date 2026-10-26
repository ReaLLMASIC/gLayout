"""Audit textbook candidates evaluated under the v1 bench for the port-order limitation (read-only).

For every candidate directory with completed points under an acceptance output (candidates/<id>/points/<cfg>/physical/executor_*)
or a rule collection (physical/executor_* with context.candidate_id), compare the extracted DUT subcircuit pin order in the PEX
netlist with the reference netlist's pin order. Under the v1 bench a different order means the simulation was mis-wired, so the
point's electrical verdict is an evaluator artifact and the candidate must be excluded from labels (never a negative).
"""
import argparse
import glob
import json
from pathlib import Path


def subckt(text, name=None):
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == '.subckt' and (name is None or parts[1] == name): return parts[1], parts[2:]
    return None, None


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, required=True); p.add_argument('--output', type=Path); a = p.parse_args()
    rows = {}
    for manifest in glob.glob(str(a.root / '**/executor_*/manifest.json'), recursive=True):
        m = json.loads(Path(manifest).read_text()); run = Path(manifest).parent; ctx = m.get('context', {})
        if 'trusted' not in m: continue
        validation = run / 'evidence/validation.json'
        if not validation.is_file(): continue
        v = json.loads(validation.read_text()); pex = v.get('artifacts', {}).get('pex')
        if not pex: continue
        _, pins = subckt((run / 'evidence' / pex['netlist']).read_text(), pex['top_cell'])
        reference = run / 'trusted/references' / (ctx['configuration_id'] + '.spice')
        _, ref_pins = subckt(reference.read_text()) if reference.is_file() else (None, None)
        rows.setdefault(ctx.get('candidate_id'), []).append({'configuration_id': ctx.get('configuration_id'), 'extracted_pins': pins, 'reference_pins': ref_pins,
                                                             'order_matches_reference': pins == ref_pins, 'S2': v.get('assessment', {}).get('S2'), 'run': str(run)})
    report = {'root': str(a.root), 'candidates': len(rows), 'mismatched_candidates': sorted(c for c, pts in rows.items() if any(not q['order_matches_reference'] for q in pts)),
              'details': {c: [{k: q[k] for k in ('configuration_id', 'order_matches_reference', 'S2')} for q in pts] for c, pts in rows.items() if any(not q['order_matches_reference'] for q in pts)}}
    text = json.dumps(report, indent=2)
    if a.output: a.output.write_text(text + '\n')
    print(json.dumps({'candidates': report['candidates'], 'mismatched_candidates': report['mismatched_candidates']}))


if __name__ == '__main__': main()
