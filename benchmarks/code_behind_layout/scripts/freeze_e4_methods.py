#!/usr/bin/env python3
"""Freeze completed formal E4 models; never manufacture missing training evidence."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.e4_methods import build_methods_freeze


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Do not overwrite an existing methods freeze')
    artifact=build_methods_freeze(json.loads(args.draft.read_text()),args.draft.resolve().parent)
    if not args.validate_only:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x') as target:target.write(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
        args.output.chmod(0o444)
    print(json.dumps({'status':artifact['status'],'formal_training_runs':artifact['formal_training_runs'],
                      'written':not args.validate_only,'hidden_evaluation_released':False}))


if __name__=='__main__':main()
