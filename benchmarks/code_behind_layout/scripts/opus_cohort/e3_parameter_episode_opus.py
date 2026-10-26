#!/usr/bin/env python3
"""Claude-policy driver for one frozen E3 parameter-baseline search (P); the frozen script is unchanged.

The random strategy never invokes a model; the gpt_feedback strategy receives the Claude adapter
through the same run-time replacement as the editing searches.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort.common import annotate_dispatch_record, install_claude_adapter  # noqa: E402

install_claude_adapter()
from scripts import e3_parameter_episode as base  # noqa: E402

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--strategy', choices=base.STRATEGIES, required=True)
    p.add_argument('--selection-seed', type=int, default=41)
    p.add_argument('--trial', default='development')
    p.add_argument('--formal', action='store_true')
    p.add_argument('--dispatch-record', type=Path)
    a = p.parse_args()
    a.backend = False
    try:
        base.run_policy(a)
    finally:
        annotate_dispatch_record(a.dispatch_record, __file__)
