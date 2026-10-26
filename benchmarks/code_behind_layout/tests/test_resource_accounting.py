import json
from pathlib import Path
import tempfile
import unittest

from scripts.account_recorded_resources import account


def save(filename,value):
    filename.parent.mkdir(parents=True,exist_ok=True);filename.write_text(json.dumps(value))


class ResourceAccountingTests(unittest.TestCase):
    def test_E1_raw_and_capsule_subsets_are_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);probe=root/'runs/phase0/preparation'
            save(probe/'pilot_manifest.json',{'status':'TOOL_COMPLETED','script':'prepare.py'})
            save(probe/'resource_usage.json',dict(wall_seconds=4,self_user_cpu_seconds=1,self_system_cpu_seconds=1,children_user_cpu_seconds=4,children_system_cpu_seconds=1))
            ep=root/'runs/development/E1_matched/ep'
            cost={'physical_calls':1,'waited_child_CPU_seconds':5,'stage_wall_seconds':8,'missing_CPU_records':0,'capsule_preparation_CPU_seconds':7}
            empty={**cost,'physical_calls':0}
            save(ep/'private/state.json',{'phase':'development_E1','in_flight_point':None,'post_freeze_status':'COMPLETE',
                'costs_by_stage':{'search':cost,'post_freeze_diagnostic':empty,'hidden':empty}})
            raw=ep/'private/physical/run'
            save(raw/'manifest.json',{'run_id':'executor_duplicated_view','phase':'development_E1','status':'EVALUATED',
                'candidate':{'status':'COMPLETED','wall_seconds':8}})
            save(raw/'candidate_stage/resource_usage.json',{'child_user_cpu_seconds':5,'child_system_cpu_seconds':0})
            report=account(root)
            self.assertEqual(report['totals']['observed_CPU_seconds'],12)
            self.assertEqual(report['totals']['event_records'],2)
            self.assertNotIn('executor_candidate',report['categories'])

    def test_historical_missing_telemetry_stays_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            save(root/'runs/phase0/early/pilot_manifest.json',{'status':'FAILED','case':'early_mirror'})
            report=account(root)
            self.assertIsNone(report['records'][0]['CPU_seconds'])
            self.assertEqual(report['totals']['events_with_unavailable_CPU'],1)
            self.assertFalse(report['prices_or_break_even_inferred'])


if __name__=='__main__':unittest.main()
