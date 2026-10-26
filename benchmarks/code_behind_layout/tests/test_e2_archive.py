"""Real temporary files test archive safety; no physical labels are fixtures."""
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.archive_e2_run import archive


class E2ArchiveTests(unittest.TestCase):
    def test_readonly_directory_and_interrupted_cleanup_keep_complete_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = (Path(tmp) / "executor_archive_control").resolve()
            for name in ["accepted", "blocked_package", "source", "evidence"]:
                (run / name).mkdir(parents=True)
            (run / "manifest.json").write_text(json.dumps({"phase": "development_E2_storage_fixture", "status": "EVALUATED"}))
            (run / "accepted/candidate.gds").write_bytes(b"software GDS fixture")
            (run / "blocked_package/__init__.py").write_bytes(b"read-only boundary fixture")
            (run / "blocked_package/__init__.py").chmod(0o444)
            (run / "blocked_package").chmod(0o555)
            (run / "source/generator.py").write_bytes(b"frozen source fixture")
            (run / "evidence/validation.json").write_text("{}")
            originals = {str(p.relative_to(run)): p.read_bytes() for p in run.rglob("*") if p.is_file()}
            unlink = Path.unlink
            def interrupt(path, *args, **kwargs):
                if path == run / "source/generator.py":
                    raise PermissionError("software fixture interrupted after first deletion")
                return unlink(path, *args, **kwargs)
            with patch.object(Path, "unlink", interrupt):
                with self.assertRaises(PermissionError):
                    archive(run, retain_accepted_gds=True)
            self.assertFalse((run / "blocked_package/__init__.py").exists())
            before = (run / "terminal_raw.tar.gz").read_bytes()
            self.assertFalse(json.loads((run / "raw_archive.json").read_text())["cleanup_complete"])
            report = archive(run, retain_accepted_gds=True)
            self.assertTrue(report["cleanup_complete"])
            self.assertEqual(before, (run / "terminal_raw.tar.gz").read_bytes())
            with tarfile.open(run / "terminal_raw.tar.gz") as saved:
                self.assertEqual(saved.getmember("blocked_package").mode, 0o555)
                for name, data in originals.items():
                    self.assertEqual(saved.extractfile(name).read(), data)
                restored = Path(tmp) / "restored"
                self.assertTrue(all(not Path(member.name).is_absolute() and ".." not in Path(member.name).parts for member in saved.getmembers()))
                # This archive was generated and checked in this fixture;
                # defer directory modes until all member files are restored.
                saved.extractall(restored)
                for name, data in originals.items():
                    self.assertEqual((restored / name).read_bytes(), data)
                self.assertEqual(stat.S_IMODE((restored / "blocked_package").stat().st_mode), 0o555)
                (restored / "blocked_package").chmod(0o755)
            self.assertEqual((run / "accepted/candidate.gds").read_bytes(), originals["accepted/candidate.gds"])


if __name__ == "__main__":
    unittest.main()
