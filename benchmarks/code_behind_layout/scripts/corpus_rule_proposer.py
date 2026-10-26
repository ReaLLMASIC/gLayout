"""Eight explicit source rules, borrowed from the retained development pilot.

These are deterministic proposal sources, never outputs of an AI model. A
collection must freeze this file before obtaining any new physical labels.
"""
import argparse
import json
from pathlib import Path
import time

RULE_IDS=['diffusion_plan','gate_plan','combined_plan','reverse_device_order','gate_order',
          'reverse_port_track_order','reverse_devices_combined','reverse_ports_combined']
BORROWED_FROM='scripts/corpus_yield_pilot.py:variants; same eight development planning rules'


def propose(source,rule_id):
    if rule_id not in RULE_IDS:raise ValueError('Unknown frozen rule')
    plan='plan = nm.get(mode) or nm["independent"]'
    ordering='    return out\n'
    ports='assemble(pdk, row_specs, circuit.ports, name=top)'
    def replace_once(text,before,after):
        if text.count(before)!=1:raise ValueError('Rule precondition differs from its frozen source scope')
        return text.replace(before,after,1)
    output=source
    if rule_id in ['reverse_device_order','reverse_devices_combined']:
        output=replace_once(output,ordering,'    return list(reversed(out))\n')
    elif rule_id=='gate_order':
        output=replace_once(output,ordering,'    return sorted(out, key=lambda d: (d.g, d.d, d.logical_id))\n')
    if rule_id in ['reverse_port_track_order','reverse_ports_combined']:
        output=replace_once(output,ports,'assemble(pdk, row_specs, list(reversed(circuit.ports)), name=top)')
    mode={'diffusion_plan':'diffusion_only','gate_plan':'gate_only','combined_plan':'combined',
          'reverse_devices_combined':'combined','reverse_ports_combined':'combined'}.get(rule_id)
    if mode:output=replace_once(output,plan,'plan = nm.get("'+mode+'") or nm["independent"]')
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--rule',choices=RULE_IDS,required=True);a=p.parse_args()
    wall=time.monotonic();cpu=time.process_time();source=a.source.read_text();text=propose(source,a.rule)
    print(json.dumps({'proposal':{'source_text':text},'usage':{'proposal_generator':'frozen_rule_proposer',
        'rule_id':a.rule,'wall_seconds':time.monotonic()-wall,'process_cpu_seconds':time.process_time()-cpu,
        'model_inferences':0,'model_tokens':None},'borrowed_from':BORROWED_FROM}))


if __name__=='__main__':main()
