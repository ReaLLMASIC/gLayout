#!/usr/bin/env python3
"""Run one Minimum-tier E3-C search part against the Claude cohort freeze.

scripts/run_e3_suite.py stays byte-identical. Its coordinator loop, reservations, collection,
sealed-source proof and evidence archiving are reused; only the declared matrix and the child
command are replaced on the imported module object. Hidden evaluation is never dispatched here.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common  # noqa: E402
from scripts import run_e3_suite as base  # noqa: E402

base.plan = common.claude_e3_plan
base.command = common.claude_e3_command

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--part', choices=common.E3_PARTS, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    common.require_claude_manifest(common.read(args.manifest), 'E3')
    result = base.run(args)
    result['cohort'] = common.COHORT_LABEL['E3']
    print(json.dumps(result), flush=True)
