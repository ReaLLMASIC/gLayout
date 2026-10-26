#!/usr/bin/env python3
"""Claude-policy driver for one frozen 16k E1 scope episode; scripts/e1_scope_runner.py is unchanged.

The frozen runner binds GptDecisionAdapter at import time, so the replacement is applied on
the imported module object before run_policy executes. The backend half runs on the server
through the original script.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort.common import annotate_dispatch_record, install_claude_adapter  # noqa: E402

ClaudeCLIDecisionAdapter = install_claude_adapter()
from scripts import e1_scope_runner as base  # noqa: E402

base.GptDecisionAdapter = ClaudeCLIDecisionAdapter

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--method', choices=['G0', 'G1', 'G2'], required=True)
    p.add_argument('--trial', default='development')
    p.add_argument('--formal', action='store_true')
    p.add_argument('--pilot', action='store_true')
    p.add_argument('--dispatch-record', type=Path)
    a = p.parse_args()
    if a.formal and a.pilot:
        p.error('Development pilot cannot be formal')
    a.backend = False
    try:
        base.run_policy(a)
    finally:
        annotate_dispatch_record(a.dispatch_record, __file__)
