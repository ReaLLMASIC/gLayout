import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import backup_completed_phase0


class PrivateDomainBackupTests(unittest.TestCase):
    def test_terminal_ota_domain_preflight_is_not_exported_with_development_pool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'private_checkpoints').mkdir()
            names=['phase0_20261019T0236Z_ota_task_preflight','phase0_20261019T0122Z_e2_development_pilot',
                   'phase0_20261019T0312Z_revise_e1_mirror_domain']
            for name in names:
                run=root/'runs/phase0'/name;run.mkdir(parents=True)
                (run/'pilot_manifest.json').write_text(json.dumps({'status':'TOOL_COMPLETED'}))
                (run/'layout.gds').write_bytes(b'physical-layout-fixture')
            with patch.object(backup_completed_phase0,'ROOT',root):
                report=backup_completed_phase0.backup('terminal',set())
            self.assertEqual(report['selected_run_count'],1)
            with tarfile.open(report['archive']) as archive:
                members=archive.getnames()
            self.assertTrue(any(names[1] in name for name in members))
            self.assertFalse(any(names[0] in name for name in members))
            self.assertFalse(any(names[2] in name for name in members))


if __name__=='__main__':unittest.main()
