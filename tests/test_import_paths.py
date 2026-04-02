from __future__ import annotations

import importlib
import sys
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ImportPathRegressionTests(unittest.TestCase):
    def test_canonical_cells_import(self) -> None:
        module = importlib.import_module(
            "glayout.cells.elementary.current_mirror.current_mirror"
        )
        self.assertTrue(hasattr(module, "current_mirror"))

    def test_blocks_compat_import(self) -> None:
        legacy = importlib.import_module(
            "glayout.blocks.elementary.current_mirror.current_mirror"
        )
        canonical = importlib.import_module(
            "glayout.cells.elementary.current_mirror.current_mirror"
        )
        self.assertEqual(legacy.__file__, canonical.__file__)
        self.assertEqual(legacy.current_mirror.__name__, canonical.current_mirror.__name__)

    def test_canonical_verification_import(self) -> None:
        module = importlib.import_module("glayout.verification.evaluator_wrapper")
        self.assertTrue(hasattr(module, "run_evaluation"))

    def test_verification_compat_import(self) -> None:
        legacy = importlib.import_module("glayout.blocks.evaluator_box.evaluator_wrapper")
        canonical = importlib.import_module("glayout.verification.evaluator_wrapper")
        self.assertEqual(legacy.__file__, canonical.__file__)
        self.assertEqual(legacy.run_evaluation.__name__, canonical.run_evaluation.__name__)

    def test_public_exports_match(self) -> None:
        blocks = importlib.import_module("glayout.blocks")
        cells = importlib.import_module("glayout.cells")
        self.assertIs(blocks.current_mirror, cells.current_mirror)
        self.assertIs(blocks.transmission_gate, cells.transmission_gate)


if __name__ == "__main__":
    unittest.main()
