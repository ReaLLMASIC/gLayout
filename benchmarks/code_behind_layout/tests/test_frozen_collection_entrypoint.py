"""A frozen collector keeps its source location and receives the real workspace."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_frozen_training_collection import ROOT,frozen_module


class FrozenCollectorEntrypointTests(unittest.TestCase):
    def fixture(self,directory):
        root=Path(directory);(root/'interface').mkdir()
        source=root/'interface/collector.py'
        source.write_text("from pathlib import Path\nROOT=Path(__file__).parents[1]\ndef load(path):return str(ROOT),str(Path(__file__).resolve())\n")
        manifest=root/'collection.json';manifest.write_text(json.dumps({'status':'frozen','role':'train_collection','frozen_collector_entrypoint':'interface/collector.py'}))
        (root/'freeze_identity.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,manifest]}))
        return manifest,source

    def test_exact_snapshot_executes_with_true_file_and_research_root(self):
        parent=ROOT/'runtime/train_collections';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            manifest,source=self.fixture(directory);module=frozen_module(manifest)
            self.assertEqual(module.load(manifest),(str(ROOT),str(source.resolve())))

    def test_changed_code_is_rejected_before_execution(self):
        parent=ROOT/'runtime/train_collections';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            manifest,source=self.fixture(directory);marker=Path(directory)/'executed'
            source.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('bad')\n")
            with self.assertRaisesRegex(ValueError,'artifact changed'):frozen_module(manifest)
            self.assertFalse(marker.exists())


if __name__=='__main__':unittest.main()
