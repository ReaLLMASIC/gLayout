#!/usr/bin/env python3
"""Analyze actual exported E4 episodes; incomplete fixed slots remain unknown."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.e4_analysis import analyze


def read(path):return json.loads(Path(path).read_text())


def load_episodes(index_path):
    result=[]
    for line in Path(index_path).read_text().splitlines():
        if not line.strip():continue
        index=json.loads(line);report=read(index['episode_json'])
        if report.get('formal_trial') is not True:raise ValueError('Development episodes do not enter formal E4 statistics')
        if index.get('regression_json'):
            join=read(index['regression_json'])
            if not index.get('episode_directory') or join.get('episode_directory')!=index['episode_directory']:
                raise ValueError('Regression join needs its exact backend episode-directory binding')
            if join.get('sealed_source_revision')!=report['selection']['revision']:
                raise ValueError('Regression join refers to another sealed source')
            report={**report,'regression_join':join}
        result.append(report)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','episode-index','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--models-manifest',type=Path);parser.add_argument('--bootstrap-replicates',type=int,default=2000)
    args=parser.parse_args();manifest=read(args.manifest)
    if manifest.get('status')!='FROZEN_E4':raise ValueError('Main E4 results require their actual predeclared matrix freeze')
    report=analyze(manifest,load_episodes(args.episode_index),read(args.models_manifest) if args.models_manifest else None,
                   replicates=args.bootstrap_replicates)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
