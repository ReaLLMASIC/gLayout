#!/usr/bin/env python3
"""Claude-policy driver (format-guidance prompt, cohort E1-C2) for one frozen 16k E1 scope episode."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort.common import annotate_dispatch_record  # noqa: E402
from scripts.opus_cohort.common_v2 import install_claude_adapter_v2  # noqa: E402

ClaudeCLIDecisionAdapterV2 = install_claude_adapter_v2()
from scripts import e1_scope_runner as base  # noqa: E402

base.GptDecisionAdapter = ClaudeCLIDecisionAdapterV2

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
