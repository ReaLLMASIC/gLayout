"""Offline nine-point development yield; never rewrite evidence or formal labels."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.corpus_metrics import mirror_dc_metrics


def point_record(root):
    physical=root/'physical.json'
    if not physical.exists():
        return {'complete':False,'feasible_under_prospective_constraints':False,'reason':'No complete physical record','raw':str(root)}
    actual=json.loads(physical.read_text())
    complete=bool(actual.get('full_physical_analysis_complete') and actual.get('DRC',{}).get('is_clean') and actual.get('LVS',{}).get('is_clean') and actual.get('RC',{}).get('has_real_RC'))
    metrics={corner:mirror_dc_metrics(root/corner/'dc.dat') for corner in ['tt','ss','ff']} if complete else {}
    feasible=complete and all(m['nominal_current_relative_error']<=.05 and m['output_resistance_ohm']>=300000 and
        len([r for r in m['dc_sweep_relative_errors'] if .7-1e-8<=r['voltage_V']<=1.0+1e-8])==4 and
        all(r['relative_error']<=.05 for r in m['dc_sweep_relative_errors'] if .7-1e-8<=r['voltage_V']<=1.0+1e-8) for m in metrics.values())
    return {'complete':complete,'feasible_under_prospective_constraints':feasible,'area_um2':actual.get('area_um2'),'corners':metrics,'raw':str(root)}


def summarize(batch):
    state=json.loads(batch.read_text())
    if state['baseline_only'] or len(state['jobs'])!=8:raise ValueError('The full eight-point/eight-candidate development batch is not complete')
    anchor=ROOT/'runs/phase0/phase0_20261018T234700264280Z_corpus_yield_pilot'
    roots={'anchor':anchor,**{job['configuration_id']:Path(job['output']) for job in state['jobs']}}
    names=[row['candidate_id'] for row in json.loads((anchor/'yield.json').read_text())['proposals'] if row['candidate_id']!='baseline']
    if len(names)!=8:raise ValueError('Expected the original eight explicit heuristic programs')
    baselines={}
    for cid,root in roots.items():
        rows=json.loads((root/'yield.json').read_text())['proposals']
        baseline=next(row for row in rows if row['candidate_id']=='baseline')
        original=Path(baseline['reused_completed_evidence']) if baseline.get('reused_completed_evidence') else root
        if original.is_relative_to('/work'):original=ROOT/original.relative_to('/work')
        baselines[cid]=point_record(original/'baseline')
    if not all(row['feasible_under_prospective_constraints'] for row in baselines.values()):raise ValueError('A baseline no longer satisfies the stated hypothetical comparison constraints')
    result={'scope':'development_only_offline_prospective_constraint_analysis_not_formal_labels',
        'batch':str(batch),'configurations':9,'heuristic_programs':8,'formal_training_rows':0,
        'constraints_used_for_analysis':{'all_corners':['tt','ss','ff'],'DC_nominal_error_max':.05,'output_resistance_min_ohm':300000,'compliance_samples_V':[.7,.8,.9,1.0],'each_compliance_error_max':.05},
        'objective':'arithmetic mean of area_um2 across eight development configurations, with anchor feasibility required; feasibility first','minimum_relative_improvement':.01,
        'baselines':baselines,'candidates':{}}
    baseline_mean=sum(row['area_um2'] for cid,row in baselines.items() if cid!='anchor')/8
    whole_baseline_mean=sum(row['area_um2'] for row in baselines.values())/9
    for name in names:
        sources=[(root/name/'source/textbook_sharing/layout.py').read_text() for root in roots.values()]
        if any(source!=sources[0] for source in sources):raise ValueError('One family candidate did not apply the identical complete source program at every point')
        rows={cid:point_record(root/name) for cid,root in roots.items()}
        passing=sum(row['feasible_under_prospective_constraints'] for row in rows.values())
        all_complete=all(row['complete'] for row in rows.values())
        mean=sum(row['area_um2'] for cid,row in rows.items() if cid!='anchor')/8 if all_complete else None
        whole_mean=sum(row['area_um2'] for row in rows.values())/9 if all_complete else None
        anchor=rows['anchor'];anchor_improvement=1-anchor['area_um2']/baselines['anchor']['area_um2'] if anchor['complete'] else None
        result['candidates'][name]={'physical_points_complete':sum(row['complete'] for row in rows.values()),'passing_points':passing,'coverage':passing/9,'regression_rate':(9-passing)/9,
            'family_mean_area_um2':mean,'family_relative_area_improvement':1-mean/baseline_mean if mean is not None else None,
            'whole_nine_point_mean_relative_area_improvement':1-whole_mean/whole_baseline_mean if whole_mean is not None else None,
            'anchor_relative_area_improvement':anchor_improvement,
            'anchor_feasible_meaningful_area_improvement':bool(anchor['feasible_under_prospective_constraints'] and anchor_improvement>=.01),
            'family_feasible_meaningful_area_improvement':bool(passing==9 and mean is not None and 1-mean/baseline_mean>=.01),'points':rows}
    result['counts']={'new_development_candidate_point_attempts':64,'anchor_development_candidate_point_attempts_preexisting':8,
        'all_candidate_point_attempts':72,'physical_points_complete':sum(row['physical_points_complete'] for row in result['candidates'].values()),
        'anchor_feasible_meaningful_programs':sum(row['anchor_feasible_meaningful_area_improvement'] for row in result['candidates'].values()),
        'family_feasible_meaningful_programs':sum(row['family_feasible_meaningful_area_improvement'] for row in result['candidates'].values())}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path);a=p.parse_args()
    batch=a.batch or max((ROOT/'runs/development/corpus_family_yield').glob('*/batch.json'),key=lambda path:path.stat().st_mtime)
    result=summarize(batch);out=ROOT/'results/derived/c01_family_development_yield.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'counts':result['counts'],'candidates':{name:{key:row[key] for key in ['coverage','family_relative_area_improvement','anchor_relative_area_improvement','family_feasible_meaningful_area_improvement']} for name,row in result['candidates'].items()}},indent=2))
