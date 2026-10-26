"""Analyze an explicit frozen E3 episode index without dropping NOT_RUN trials."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.e3_analysis import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--episode-index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest['status'] != 'FROZEN_E3':
        raise ValueError('Main results require their actual independent E3 freeze')
    episodes = []
    for line in args.episode_index.read_text().splitlines():
        index = json.loads(line)
        report = json.loads(Path(index['episode_json']).read_text())
        if report.get('formal_trial') is not True:
            raise ValueError('Development episodes do not enter formal statistics')
        episodes.append({**report, 'trial_id': index['trial_id']})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analyze(manifest, episodes), indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
