"""Software state/budget boundaries; no model, source search or EDA run."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts.e3_fidelity_episode import Gateway,POLICY,verify_calibration
from scripts.freeze_e3_fidelity import audit_controls
from src.e3_episode_state import EpisodeState


def state():
    points=[{'configuration_id':'anchor','role':'anchor','parameters':{'w':1}},
        {'configuration_id':'dev1','role':'development','parameters':{'w':2}},
        {'configuration_id':'dev2','role':'development','parameters':{'w':3}}]
    result=EpisodeState('R',points,41,'max')
    result.value.update(deferred_by_revision={},decisions=0,status='RUNNING',formal_trial=False)
    result.observe({'configuration_id':'anchor','checked':{'S2':True,'execution_integrity':'valid'},'objective':1})
    return result


class FidelityEpisodeTests(unittest.TestCase):
    def test_deferred_exclusion_never_creates_an_actual_counterexample(self):
        s=state()
        before=dict(s.current()['results'])
        self.assertEqual(s.next_configuration(excluded=['dev1']),'dev2')
        self.assertEqual(s.current()['results'],before)
        self.assertEqual(s.value['counterexamples'],[])
        s.new_revision()
        self.assertEqual(s.next_configuration(excluded=['anchor','dev1']),'anchor')

    def test_deferred_gateway_response_does_not_call_observe(self):
        g=Gateway.__new__(Gateway);g.state=state();g.write=Mock()
        g.manifest={'budget':{'decisions':48}}
        g.packet={'budget':{'deadline_utc':(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()}}
        g.next=Mock(return_value='dev1')
        g.physical=Mock(return_value={'deferred':True,'promotion_decision':{'action':'screened_deferred'},
            'nominal_actual':{'measurement':{'metrics':{'tt_ugb_Hz':1}}}})
        g.state.value.update(low_fidelity_calls=2,full_evaluations=0)
        g.state.observe=Mock()
        with patch('scripts.e3_fidelity_episode.validate_action'):
            result=g.action({'action':'request_evaluation','configuration_ids':['dev1'],'fidelity':'pex_spice'})
        self.assertEqual(result['status'],'screened_deferred')
        self.assertNotIn('checked',result)
        self.assertEqual(g.state.value['deferred_by_revision']['0'],['dev1'])
        g.state.observe.assert_not_called()

    def test_post_release_path_uses_parent_fresh_full_and_development_cannot_open_hidden(self):
        g=Gateway.__new__(Gateway);g.state=state()
        with patch('scripts.e3_fidelity_episode.main.Gateway.physical',return_value={'fresh':True}) as parent:
            self.assertEqual(g.physical('hidden',0,'post_freeze_hidden'),{'fresh':True})
            parent.assert_called_once_with('hidden',0,'post_freeze_hidden')
        with self.assertRaises(ValueError):g.post_freeze()

    def test_freeze_rejects_unmeasured_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'summary.json';path.write_text('{"complete":false,"rows":[]}')
            with self.assertRaises(ValueError):audit_controls(path)

    def test_frozen_calibration_bytes_cannot_change_after_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'artifact.json';path.write_text('{"software_fixture":1}')
            manifest={'status':'FROZEN_E3_FIDELITY_METHOD','promotion_calibration':str(path),
                'promotion_calibration_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            path.chmod(0o444);verify_calibration(manifest)
            path.chmod(0o644);path.write_text('{"software_fixture":2}');path.chmod(0o444)
            with self.assertRaises(RuntimeError):verify_calibration(manifest)


if __name__=='__main__':unittest.main()
