"""Synthetic arithmetic/filesystem fixtures only; no formal vectors/model/EDA."""
import copy
import io
import json
import math
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from src.e3_qor_supplement import analyze, interval, read_only_run_view, read_backend, PASS, FAIL
from src.e1_analysis import paired_cluster_effect


def outcome(value=100, passed=True):
    return {'checked':{'execution_integrity':'valid','S2':passed},'objective':value if passed else None}


def fixture():
    tasks={}; originals={}; episodes=[]; metadata=[]
    for number in range(24):
        ident='software_task_%02d'%number; group=number//3
        metadata.append({'task_id':ident,'source_group':'g%d'%group,'merged_source_group':'merged01' if group<2 else 'g%d'%group})
        direction='min' if group<6 else 'max'
        definition={'metric':'area' if direction=='min' else 'ugb_per_area','unit':'um2' if direction=='min' else 'Hz/um2',
            'direction':direction,'corner_aggregation':'worst'}
        tasks[ident]={'configurations':[{'configuration_id':'software_h%d'%i,'role':'hidden','contract':{'objective':definition}} for i in range(16)]}
        originals[ident]={'software_h%d'%i:outcome() for i in range(16)}
        for method in ('A','R','B','C'):
            for trial in range(1,6):
                value=(80 if direction=='min' else 125) if method=='C' else 100
                episodes.append({'task_id':ident,'method':method,'trial_id':str(trial),
                    'points':{'software_h%d'%i:outcome(value) for i in range(16)}})
    rule={'analysis_id':'software_fixture_not_formal_results','matched_method_contrasts':{'contrasts':[['C','R'],['C','B']]},
        'uncertainty':{'replicates':2000,'seed':20261019}}
    return {'tasks':metadata},tasks,originals,episodes,rule


class QorSupplementTests(unittest.TestCase):
    def test_direction_aligned_log_gain_and_complete_eligible_population(self):
        manifest,tasks,old,episodes,rule=fixture(); report=analyze(manifest,tasks,old,episodes,rule,complete_gate=True)
        self.assertEqual(report['status'],'COMPLETE')
        for row in report['task_trial_quality']:
            if row['method']=='C': self.assertAlmostEqual(row['mean_log_gain'],math.log(1.25))
            self.assertEqual(sum(sum(v.values()) for v in row['state_count_table'].values()),16)
        for row in report['contrasts']:
            self.assertEqual(row['eligible_tasks'],24)
            self.assertEqual(row['merged_cluster_analysis']['actual_clusters'],7)
            self.assertEqual(row['logical_cluster_sensitivity']['actual_clusters'],8)
            self.assertAlmostEqual(row['merged_cluster_analysis']['task_mean_log_gain_difference'],math.log(1.25))

    def test_common_same_point_mask_does_not_compare_different_feasible_subsets(self):
        manifest,tasks,old,episodes,rule=fixture()
        for row in episodes:
            if row['task_id']=='software_task_00' and row['trial_id']=='1':
                if row['method']=='C':row['points']['software_h0']=outcome(1)
                if row['method']=='R':row['points']['software_h0']=outcome(passed=False)
        report=analyze(manifest,tasks,old,episodes,rule,complete_gate=True)
        pair=next(r for r in report['contrasts'] if r['contrast']=='C-R')
        actual=next(r for r in pair['task_trial_counts'] if r['task_id']=='software_task_00' and r['trial_id']=='1')
        self.assertEqual(actual['common_mask_count'],15);self.assertEqual(actual['known_excluded'],1)
        self.assertAlmostEqual(actual['task_trial_effect'],math.log(1.25))
        r=next(r for r in report['task_trial_quality'] if r['task_id']=='software_task_00' and r['method']=='R' and r['trial_id']=='1')
        self.assertEqual(r['verified_regressions'],1)

    def test_one_empty_trial_makes_whole_task_undefined_but_conditional_population_remains(self):
        manifest,tasks,old,episodes,rule=fixture()
        for row in episodes:
            if row['task_id']=='software_task_00' and row['method']=='R' and row['trial_id']=='1':
                row['points']={name:outcome(passed=False) for name in row['points']}
        report=analyze(manifest,tasks,old,episodes,rule,complete_gate=True)
        cr,cb=[next(r for r in report['contrasts'] if r['contrast']==name) for name in ('C-R','C-B')]
        self.assertEqual((cr['declared_tasks'],cr['eligible_tasks'],cr['undefined_tasks']),(24,23,1))
        self.assertEqual(cb['eligible_tasks'],24)
        counts=next(r for r in cr['task_trial_counts'] if r['task_id']=='software_task_00' and r['trial_id']=='1')
        self.assertIsNone(counts['task_trial_effect'])

    def test_original_failed_task_retains_recoveries_without_fake_quality(self):
        manifest,tasks,old,episodes,rule=fixture()
        old['software_task_00']={name:outcome(passed=False) for name in old['software_task_00']}
        report=analyze(manifest,tasks,old,episodes,rule,complete_gate=True)
        row=next(r for r in report['task_trial_quality'] if r['task_id']=='software_task_00')
        self.assertEqual(row['verified_recoveries'],16);self.assertIsNone(row['mean_log_gain'])
        self.assertEqual(report['contrasts'][0]['undefined_tasks'],1)

    def test_incomplete_matrix_or_unknown_raw_never_yields_effect_CI(self):
        manifest,tasks,old,episodes,rule=fixture()
        for modified in [episodes[:-1],copy.deepcopy(episodes)]:
            if len(modified)==480: modified[0]['points']['software_h0']['checked']['execution_integrity']='incomplete'
            report=analyze(manifest,tasks,old,modified,rule,complete_gate=True)
            self.assertEqual(report['status'],'DESCRIPTIVE_ONLY_NOT_READY')
            self.assertTrue(all(row['merged_cluster_analysis'] is None for row in report['contrasts']))

    def test_draw_rule_matches_primary_and_single_cluster_has_no_CI(self):
        rows=[{'task_id':str(i),'source_group':'g%d'%(i%3),'effect':i/10} for i in range(9)]
        actual=interval(rows,'source_group',2000,20261019)
        reference=paired_cluster_effect([{**r,'method_S2_rates':{'C':r['effect'],'R':0}} for r in rows],
            'C','R','source_group',2000,20261019)
        self.assertEqual(actual['cluster_percentile_95_CI'],reference['cluster_percentile_95_CI'])
        single=interval([{**r,'source_group':'same'} for r in rows],'source_group',2000,20261019)
        self.assertEqual(single['actual_clusters'],1);self.assertIsNone(single['cluster_percentile_95_CI'])

    def test_archive_analysis_does_not_restore_or_modify_original_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir()
            for name in ('manifest.json','configuration.json'):(run/name).write_text('{}')
            for name in ('source','trusted','accepted'):(run/name).mkdir()
            (run/'source/layout.py').write_text('# software fixture\n')
            archive=root/'raw.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:
                data=b'{"software_fixture":true}';member=tarfile.TarInfo('evidence/validation.json');member.size=len(data);stream.addfile(member,io.BytesIO(data))
            (run/'evidence_archive.json').write_text(json.dumps({'archive':str(archive),'archive_bytes':archive.stat().st_size}))
            before={str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()}
            with read_only_run_view(run) as view:
                self.assertTrue(json.loads((view/'evidence/validation.json').read_text())['software_fixture'])
                self.assertNotEqual(view,run)
            self.assertFalse((run/'evidence').exists())
            self.assertEqual(before,{str(p.relative_to(run)):p.read_bytes() for p in run.rglob('*') if p.is_file()})

    def test_absent_actual_release_blocks_before_any_private_baseline_or_index_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('src.e3_qor_supplement.declaration',return_value=({}, {'hidden_release_file':str(root/'absent_release')})), patch(
                    'scripts.e3_episode.verify'), patch('scripts.e3_original_baseline.load_plan',side_effect=AssertionError('private plan must not open')) as load:
                result=read_backend(root/'manifest',root/'declaration',root/'baseline',root/'episode_index')
                self.assertEqual(result['status'],'NOT_READY_SHARED_RELEASE_ABSENT')
                self.assertIs(result['private_vectors_read'],False);load.assert_not_called()


if __name__=='__main__':unittest.main()
