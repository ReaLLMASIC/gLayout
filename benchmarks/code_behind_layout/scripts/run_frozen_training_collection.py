"""Execute the exact collector source bound by a prospective collection freeze."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def frozen_module(path):
    path=path.resolve();path.relative_to(ROOT/'runtime/train_collections')
    manifest=json.loads(path.read_text())
    if manifest.get('status')!='frozen' or manifest.get('role')!='train_collection' or manifest.get('frozen_collector_entrypoint')!='interface/collector.py':
        raise ValueError('An explicit frozen collector entrypoint is required')
    identity=json.loads((path.parent/'freeze_identity.json').read_text())
    for name,digest in identity.items():
        target=(path.parent/name).resolve();target.relative_to(path.parent)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Frozen collection artifact changed: '+name)
    source=path.parent/'interface/collector.py'
    spec=importlib.util.spec_from_file_location('_frozen_training_collector',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # ROOT is execution environment, not the snapshot's physical location.
    # __file__ remains the actual frozen code, including for its self-binding.
    module.ROOT=ROOT
    return module


def load_definition(path):
    manifest=json.loads(path.read_text())
    if manifest.get('frozen_collector_entrypoint'):
        return frozen_module(path).load(path.resolve())
    from scripts.collect_training import load
    return load(path)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--validate-only',action='store_true');parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.validate_only==args.execute:parser.error('Select exactly one of --validate-only/--execute')
    frozen_module(args.manifest).main()
