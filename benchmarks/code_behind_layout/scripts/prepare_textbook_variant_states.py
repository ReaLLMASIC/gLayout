"""Declare a multi-state textbook train collection (E4 stage 2): plan/order lattice variants or injected faults.

Every state derives from the unmodified original layout module of the frozen parent rule collection
runtime/train_collections/<domain>_rules_v1 (same capsule, registry, trusted evaluator and label rule).
  lattice (origin natural): the three non-combined plan modes x device order {netlist, reversed, gate_sorted}
    x port order {netlist, reversed}, minus the original: 17 clean-but-different programs per domain. Their
    candidates are the four set_plan_* rules of scripts/corpus_rule_proposer_v2.py (three effective per state).
  faults (origin injected): six fixed text templates on the original (gate/drain swap, width doubled, gate tied to
    body, dropped port label, fingers dropped, polarity rows swapped; the C03 pilot used body-tied-to-source instead of
    width-doubled, which LVS does not detect). The collection declares no rule, so
    it only establishes the states and their fresh nine-point baselines; repair proposals come from the Claude
    span teacher through its separate proposal collection and physical acceptance. The inverse edit is recorded in
    the state's ancestry for audit and is never offered as a candidate.
  faults_extra / faults_more / faults_more2 (origin injected): further fixed template sets on the same original
    (five, three and six templates; faults_more2 was added on 2026-10-24 under protocol amendment A8 to reach the
    Minimum-tier SFT target). Same collector, acceptance and counting as faults.
The first state of each collection is the unmodified original, so fresh gold controls are obtained as usual.
No model call and no EDA call happen here.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.collect_training import source_identity, source_patch
from scripts.corpus_rule_proposer_v2 import RULE_IDS, propose as set_plan

PATH = 'textbook_sharing/layout.py'
PLAN = 'plan = nm.get(mode) or nm["independent"]'
ORDER = '    return out\n'
PORTS = 'assemble(pdk, row_specs, circuit.ports, name=top)'
LATTICE_MODES = ('independent', 'diffusion_only', 'gate_only')
DEVICE_ORDERS = {'netlist': ORDER, 'reversed': '    return list(reversed(out))\n', 'gate_sorted': '    return sorted(out, key=lambda d: (d.g, d.d, d.logical_id))\n'}
PORT_ORDERS = {'netlist': PORTS, 'reversed': 'assemble(pdk, row_specs, list(reversed(circuit.ports)), name=top)'}
FAULTS = {
    'gate_drain_swap': ('d.nets[0], d.nets[1], d.nets[2], d.nets[3], float(sz["w"])', 'd.nets[1], d.nets[0], d.nets[2], d.nets[3], float(sz["w"])'),
    'width_doubled': ('float(sz["w"]), float(sz["l"])', '2 * float(sz["w"]), float(sz["l"])'),
    'gate_tied_to_body': ('d.nets[0], d.nets[1], d.nets[2], d.nets[3], float(sz["w"])', 'd.nets[0], d.nets[3], d.nets[2], d.nets[3], float(sz["w"])'),
    'dropped_port_label': (PORTS, 'assemble(pdk, row_specs, circuit.ports[:-1], name=top)'),
    'fingers_dropped': ('int(sz.get("nf", 1))', '1'),
    'polarity_rows_swapped': ('pol = "n" if g[0].model_role == "nfet" else "p"', 'pol = "p" if g[0].model_role == "nfet" else "n"'),
}
EXTRA_FAULTS = {
    'length_doubled': ('float(sz["w"]), float(sz["l"])', 'float(sz["w"]), 2 * float(sz["l"])'),
    'fingers_doubled': ('int(sz.get("nf", 1))', '2 * int(sz.get("nf", 1))'),
    'width_halved': ('float(sz["w"]), float(sz["l"])', '0.5 * float(sz["w"]), float(sz["l"])'),
    'ports_dropped_two': (PORTS, 'assemble(pdk, row_specs, circuit.ports[:-2], name=top)'),
    'taps_removed_n': ('RowSpec(rows["n"], "n", False, rows["n"][0].body_net)', 'RowSpec(rows["n"], "n", False, rows["n"][0].body_net, taps=False)'),
}
MORE_FAULTS = {
    'gate_tied_to_drain': ('d.nets[0], d.nets[1], d.nets[2], d.nets[3], float(sz["w"])', 'd.nets[0], d.nets[0], d.nets[2], d.nets[3], float(sz["w"])'),
    'device_types_swapped': ('out.append(DeviceSpec(d.name, d.kind, ', 'out.append(DeviceSpec(d.name, "pfet" if d.kind == "nfet" else "nfet", '),
    'last_device_dropped': ('    for d in circuit.devices:\n        if d.kind in ("nfet", "pfet"):', '    for d in circuit.devices[:-1]:\n        if d.kind in ("nfet", "pfet"):'),
}
MORE2_FAULTS = {  # protocol amendment A8 (2026-10-24); each template matches the original module exactly once
    'length_halved': ('float(sz["w"]), float(sz["l"])', 'float(sz["w"]), 0.5 * float(sz["l"])'),
    'fingers_tripled': ('int(sz.get("nf", 1))', '3 * int(sz.get("nf", 1))'),
    'gate_tied_to_source': ('d.nets[0], d.nets[1], d.nets[2], d.nets[3], float(sz["w"])', 'd.nets[0], d.nets[2], d.nets[2], d.nets[3], float(sz["w"])'),
    'body_tied_to_gate_net': ('rows[pol].append(from_group_result(res, f"grp{gi}", pol, g[0].b))', 'rows[pol].append(from_group_result(res, f"grp{gi}", pol, g[0].g))'),
    'port_labels_lowercased': ('assemble(pdk, row_specs, circuit.ports, name=top)', 'assemble(pdk, row_specs, [p.lower() for p in circuit.ports], name=top)'),
    'first_device_dropped': ('    for d in circuit.devices:\n        if d.kind in ("nfet", "pfet"):', '    for d in circuit.devices[1:]:\n        if d.kind in ("nfet", "pfet"):'),
}
NONE_PROPOSER = ('"""No deterministic rule: this collection only establishes declared states and their fresh baselines."""\n'
                 'RULE_IDS = []\n\n\ndef propose(source, rule_id):\n    raise ValueError("This collection declares no rule")\n')


def replace_once(text, before, after):
    if text.count(before) != 1: raise ValueError('Template precondition differs from the original module: ' + before)
    return text.replace(before, after, 1)


def lattice_programs(original):
    for mode in LATTICE_MODES:
        for device_order, order_text in DEVICE_ORDERS.items():
            for port_order, port_text in PORT_ORDERS.items():
                if (mode, device_order, port_order) == ('independent', 'netlist', 'netlist'): continue
                text = set_plan(original, 'set_plan_' + mode)
                text = replace_once(text, ORDER, order_text)
                text = replace_once(text, PORTS, port_text)
                yield mode + '_' + device_order + '_' + port_order, {'plan_mode': mode, 'device_order': device_order, 'port_order': port_order}, text


def fault_programs(original, templates=None):
    for name, (before, after) in (templates or FAULTS).items():
        yield name, {'template': name, 'inverse_edit': {'before': after, 'after': before}}, replace_once(original, before, after)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domain', required=True, help='declared textbook domain id, e.g. C03 or C03_cfg1')
    p.add_argument('--kind', choices=['lattice', 'faults', 'faults_extra', 'faults_more', 'faults_more2'], required=True, help='faults_extra: five additional fault templates (length doubled, fingers doubled, width halved, two port labels dropped, NMOS taps removed); faults_more2: six templates (length halved, fingers tripled, gate tied to source, body tied to gate net, port labels lowercased, first device dropped)')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--collection-version', default='v1')
    p.add_argument('--dry-run', action='store_true', help='print the variant diffs and write nothing')
    a = p.parse_args(); dom = a.domain.lower()
    parent = ROOT / 'runtime/train_collections' / (dom + '_rules_v1/collection.json')
    manifest = json.loads(parent.read_text())
    if manifest.get('status') != 'frozen': raise ValueError('Parent rule collection is not frozen: ' + str(parent))
    source = Path(manifest['source_pack']); original = (source / PATH).read_text()
    parent_states = [json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
    if len(parent_states) != 1 or parent_states[0]['base_source'][PATH] != original: raise ValueError('Parent must hold the single unmodified original state')
    first = parent_states[0]
    programs = list(lattice_programs(original) if a.kind == 'lattice' else fault_programs(original, {'faults': FAULTS, 'faults_extra': EXTRA_FAULTS, 'faults_more': MORE_FAULTS, 'faults_more2': MORE2_FAULTS}[a.kind]))
    identities = {source_identity({PATH: original}, True)}
    states = [{**first, 'initial_state_id': dom + '_original_compiler_' + a.kind + '_control',
               'ancestry': {**first['ancestry'], 'role_in_collection': 'unmodified_original_first_state_for_fresh_gold_controls'}}]
    for name, descriptor, text in programs:
        identity = source_identity({PATH: text}, True)
        if identity in identities: raise ValueError('Variant programs must be distinct ASTs: ' + name)
        identities.add(identity)
        states.append({'initial_state_id': dom + '_' + ('lattice' if a.kind == 'lattice' else 'fault') + '_' + name, 'task_id': first['task_id'],
                       'parent_lineage': first['parent_lineage'], 'origin': 'natural' if a.kind == 'lattice' else 'injected', 'editable_paths': [PATH],
                       'base_source': {PATH: text},
                       'ancestry': {'kind': 'deterministic_plan_order_variant_of_unmodified_public_compiler' if a.kind == 'lattice' else 'injected_fault_template_on_unmodified_public_compiler',
                                    'source_revision': first['ancestry']['source_revision'], 'source_pack': str(source), 'derived_from_state': first['initial_state_id'],
                                    'generator_is_not_model': True, 'descriptor': descriptor, 'edit_from_original': source_patch(original, text, PATH)}})
    if a.dry_run:
        for state in states[1:]: print(state['initial_state_id']); print(state['ancestry']['edit_from_original'])
        print(json.dumps({'domain': a.domain, 'kind': a.kind, 'states': len(states), 'written': False})); return
    out = ROOT / 'runtime/collection_preparation' / (dom + '_' + a.kind + '_' + a.collection_version + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')); out.mkdir()
    states_path = out / 'initial_states.jsonl'; states_path.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in states))
    if a.kind == 'lattice': shutil.copyfile(ROOT / 'scripts/corpus_rule_proposer_v2.py', out / 'rule_proposer.py'); rule_ids = list(RULE_IDS)
    else: (out / 'rule_proposer.py').write_text(NONE_PROPOSER); rule_ids = []
    effective = 3 if a.kind == 'lattice' else 0
    metadata = {'status': 'DRAFT_PROSPECTIVE_MULTISTATE_COLLECTION_NOT_FROZEN', 'role': 'train_collection', 'kind': a.kind, 'domain': a.domain,
                'collection_id': dom + '_' + a.kind + '_' + a.collection_version, 'parent_rule_collection': str(parent), 'source_pack': str(source), 'trusted_bundle': manifest['trusted_bundle'],
                'parent_lineage': first['parent_lineage'], 'source_revision': first['ancestry']['source_revision'], 'editable_paths': [PATH],
                'initial_states_path': str(states_path), 'initial_state_count': len(states), 'distinct_initial_programs': len(identities),
                'rule_proposer_path': str(out / 'rule_proposer.py'), 'rule_ids': rule_ids, 'effective_candidates_per_variant_state': effective,
                'proposed_collection_mode': 'train_collection_rules', 'collector': 'scripts/collect_training_v2.py',
                'physical': {'workers': a.workers, 'cpus_per_job': 2, 'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720},
                'new_physical_point_budget': 9 * (len(states) + (len(states) - 1) * effective),
                'origin_labels': 'natural (clean plan/order variants)' if a.kind == 'lattice' else 'injected (fixed fault templates; reported separately from natural states)',
                'inverse_edit_is_not_a_candidate': True, 'descriptors': {s['initial_state_id']: s['ancestry'].get('descriptor') for s in states[1:]},
                'counting': 'One SFT pair at most per state under the frozen Point/Family rules; report natural and injected states separately.',
                'formal_collection_started': False, 'old_outcomes_relabelled': False}
    (out / 'preparation.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    for q in sorted(out.rglob('*'), reverse=True): q.chmod(0o555 if q.is_dir() else 0o444)
    out.chmod(0o555)
    print(json.dumps({'preparation': str(out / 'preparation.json'), 'domain': a.domain, 'kind': a.kind, 'states': len(states), 'rules': len(rule_ids),
                      'new_physical_point_budget': metadata['new_physical_point_budget'], 'state': 'DRAFT_NOT_FROZEN_OR_LAUNCHED'}))


if __name__ == '__main__': main()
