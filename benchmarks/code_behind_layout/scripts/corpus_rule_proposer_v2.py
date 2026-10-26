"""Four explicit plan-mode rules for multi-state textbook collections (E4 stage 2).

Deterministic proposal sources, never outputs of an AI model. Each rule sets the per-group named sharing plan of
textbook_sharing/layout.py to one fixed mode whatever the program's current mode is, so one rule set serves every
lattice variant. The frozen generator always calls build(..., mode="independent"), so the original `nm.get(mode)` is
the independent plan; a rule whose target equals the program's current plan returns the source unchanged, which the
collector records as no_source_change without physics. A collection must freeze this file before new labels.
"""
import argparse
import json
from pathlib import Path
import re
import time

MODES = ('independent', 'diffusion_only', 'gate_only', 'combined')
RULE_IDS = ['set_plan_' + mode for mode in MODES]
PLAN_LINE = re.compile(r'plan = nm\.get\((mode|"(?:independent|diffusion_only|gate_only|combined)")\) or nm\["independent"\]')
DERIVED_FROM = 'scripts/corpus_rule_proposer.py plan rules (diffusion_plan, gate_plan, combined_plan) generalized to any current plan mode'


def current_mode(source):
    matches = PLAN_LINE.findall(source)
    if len(matches) != 1: raise ValueError('Rule precondition differs from its frozen source scope')
    return 'independent' if matches[0] == 'mode' else matches[0].strip('"')


def propose(source, rule_id):
    if rule_id not in RULE_IDS: raise ValueError('Unknown frozen rule')
    mode = rule_id[len('set_plan_'):]
    if current_mode(source) == mode: return source
    return PLAN_LINE.sub('plan = nm.get("' + mode + '") or nm["independent"]', source, count=1)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', type=Path, required=True); p.add_argument('--rule', choices=RULE_IDS, required=True); a = p.parse_args()
    wall = time.monotonic(); cpu = time.process_time(); source = a.source.read_text(); text = propose(source, a.rule)
    print(json.dumps({'proposal': {'source_text': text}, 'usage': {'proposal_generator': 'frozen_rule_proposer', 'rule_id': a.rule, 'wall_seconds': time.monotonic() - wall,
        'process_cpu_seconds': time.process_time() - cpu, 'model_inferences': 0, 'model_tokens': None}, 'derived_from': DERIVED_FROM}))


if __name__ == '__main__': main()
