from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepoLayoutTests(unittest.TestCase):
    def test_cells_directory_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "src" / "glayout" / "cells").is_dir())

    def test_verification_directory_exists(self) -> None:
        self.assertTrue((REPO_ROOT / "src" / "glayout" / "verification").is_dir())

    def test_legacy_atlas_moved_to_repo_root(self) -> None:
        self.assertTrue((REPO_ROOT / "legacy" / "atlas").is_dir())
        self.assertFalse((REPO_ROOT / "src" / "glayout" / "blocks" / "ATLAS").exists())


if __name__ == "__main__":
    unittest.main()
