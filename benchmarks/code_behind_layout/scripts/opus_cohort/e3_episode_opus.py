#!/usr/bin/env python3
"""Claude-policy driver for one frozen E3 search; scripts/e3_episode.py stays byte-identical.

The frozen episode script keeps the variant label GPT for the frontier command-line policy. The
cohort freeze's model_config names the Claude CLI backend, and this wrapper makes the frozen
run_policy construct the Claude adapter instead of the GPT adapter. The backend half of the
episode runs on the server through the original script.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort.common import annotate_dispatch_record, install_claude_adapter  # noqa: E402

install_claude_adapter()
from scripts import e3_episode as base  # noqa: E402

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--method', choices=['A', 'R', 'B', 'C'], required=True)
    p.add_argument('--selection-seed', type=int, default=41)
    p.add_argument('--trial', default='development')
    p.add_argument('--variant', choices=['GPT'], default='GPT',
                   help='Frontier-CLI variant label of the frozen protocol; model_config carries the Claude identity')
    p.add_argument('--training-seed', type=int, choices=[41, 73, 109], default=41)
    p.add_argument('--selector-variant', choices=['main', 'without_distance', 'without_margin'], default='main')
    p.add_argument('--dispatch-record', type=Path)
    p.add_argument('--search-only', action='store_true')
    p.add_argument('--formal', action='store_true')
    a = p.parse_args()
    a.backend = False
    try:
        base.run_policy(a)
    finally:
        annotate_dispatch_record(a.dispatch_record, __file__)
