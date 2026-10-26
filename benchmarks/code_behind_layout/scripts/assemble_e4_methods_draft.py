"""Assemble the DRAFT_E4_METHODS record from a frozen E4 data directory, the twelve completed runs and their selections.

    runtime/training-venv/bin/python scripts/assemble_e4_methods_draft.py --data data/training/e4_textbook_v1 \
        --plan runtime/e4_validation_plans/e4_textbook_v1_plan.json --validation-root runs/e4_validation/e4_textbook_v1 \
        --checkpoint-root checkpoints/e4_textbook_v1 --output runtime/protocol_freezes/E4_primary/draft.json
Then: scripts/freeze_e4_methods.py --draft <output> --output runtime/protocol_freezes/E4_primary/manifest.json
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src.e4_methods import METHODS, SEEDS
from src.student_interface import CONTEXT_VERSION, interface_definition


def read(p): return json.loads(Path(p).read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('data', 'plan', 'validation-root', 'checkpoint-root', 'output'): p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args(); data = a.data.resolve()
    entries = []
    for method in METHODS:
        manifest = data / ('training_manifest.json' if method in ('T1', 'T2') else 'training_manifest_dpo.json')
        for seed in SEEDS:
            run = (a.checkpoint_root / method / ('seed-%d' % seed)).resolve(); sel = (a.validation_root / method / ('seed-%d' % seed) / 'selection.json').resolve()
            if not (run / 'run.json').is_file() or not sel.is_file(): raise SystemExit('missing run or selection for %s seed %d' % (method, seed))
            selection = read(sel)
            entries.append({'method': method, 'seed': seed, 'run_directory': str(run), 'training_manifest': str(manifest.resolve()),
                            'validation_selection': str(sel), 'selected_checkpoint': selection['selected_checkpoint']})
    draft = {'status': 'DRAFT_E4_METHODS', 'student_interface': interface_definition(CONTEXT_VERSION, 16384, 1024),
             'split_registry': str((data / 'pooled_registry.json').resolve()), 'context_calibration': str((data / 'context_calibration.json').resolve()),
             'validation_plan': str(a.plan.resolve()), 'decoding_settings': {'do_sample': False, 'max_new_tokens': 1024},
             'formal_training_runs': entries, 'data_freeze': str(data)}
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(draft, indent=2) + '\n')
    print(json.dumps({'draft': str(a.output), 'runs': len(entries)}))


if __name__ == '__main__': main()
