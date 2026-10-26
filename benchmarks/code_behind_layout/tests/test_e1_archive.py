import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.archive_e1_episode import archive,restore


class EvidenceArchiveTests(unittest.TestCase):
    def fixture(self,root):
        episode=root/'runs/formal/E1/trial';private=episode/'private';private.mkdir(parents=True)
        (private/'state.json').write_text(json.dumps({'sealed':True,'formal_trial':True,
            'post_freeze_status':'COMPLETE','in_flight_point':None}))
        files={'private/physical/point/evidence/candidate.gds':bytes(range(256))*21,
               'private/capsules/anchor/source/generator.py':b'complete_source=1\n',
               'private/point_inputs/contract.json':b'{"corners":["tt","ss","ff"]}\n'}
        for name,data in files.items():
            target=episode/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        return episode,files

    def test_all_raw_bytes_round_trip_after_compaction(self):
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.archive_e1_episode.ROOT',Path(tmp)):
            episode,files=self.fixture(Path(tmp));record=archive(episode)
            self.assertEqual(record['status'],'COMPRESSED_RAW_RETAINED')
            self.assertFalse((episode/'private/physical').exists())
            self.assertTrue((episode/'private/state.json').exists())
            self.assertEqual(record,archive(episode))
            self.assertEqual(restore(episode)['status'],'RESTORED_RAW_WITHOUT_NEW_SIMULATION')
            for name,data in files.items():self.assertEqual((episode/name).read_bytes(),data)
            with self.assertRaises(ValueError):restore(episode)

    def test_inflight_or_nonformal_evidence_cannot_be_compacted(self):
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.archive_e1_episode.ROOT',Path(tmp)):
            episode,files=self.fixture(Path(tmp));state=episode/'private/state.json'
            original=json.loads(state.read_text())
            for values in [{'in_flight_point':{'configuration_id':'hidden01'}},{'formal_trial':False}]:
                state.write_text(json.dumps({**original,**values}))
                with self.assertRaises(ValueError):archive(episode)
                for name,data in files.items():self.assertEqual((episode/name).read_bytes(),data)

    def test_readonly_frozen_capsules_archive_restore_and_repeat_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.archive_e1_episode.ROOT',Path(tmp)):
            episode,files=self.fixture(Path(tmp));capsule=episode/'private/capsules'
            for path in sorted(capsule.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
            capsule.chmod(0o555)
            record=archive(episode);restore(episode)
            self.assertEqual(capsule.stat().st_mode&0o777,0o555)
            for name,data in files.items():self.assertEqual((episode/name).read_bytes(),data)
            self.assertEqual(archive(episode)['archive'],record['archive'])
            self.assertFalse(capsule.exists())


if __name__=='__main__':unittest.main()
