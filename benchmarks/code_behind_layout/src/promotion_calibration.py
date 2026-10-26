"""Train-only nominal-to-worst UGB model with validation residual intervals.

The bootstrap describes model disagreement, not independent circuit uncertainty.
Validation configurations are correlated within their source lineages. Returned
intervals are empirical; no distribution-free coverage claim is made.
"""
import math
import random
from statistics import mean, pstdev

VERSION='nominal_to_worst_ugb_v1'


def _checked(rows,split,assignments):
    if not rows:raise ValueError('Calibration requires actual '+split+' measurements')
    seen=set()
    for row in rows:
        lineage=row['parent_lineage']
        if row['split']!=split or assignments.get(lineage)!=split:
            raise ValueError('Calibration source assignment differs from the shared registry')
        identity=(lineage,row['measurement_id'])
        if identity in seen:raise ValueError('Repeated measurements cannot increase calibration size')
        seen.add(identity)
        if not row.get('raw_evidence') or row.get('actual_three_corner_AC_complete') is not True:
            raise ValueError('UGB calibration needs complete actual three-corner AC evidence')
        nominal,worst=row['nominal_ugb_Hz'],row['worst_ugb_Hz']
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in (nominal,worst)):
            raise ValueError('Calibrate positive finite measured UGB values')
        if worst>nominal*(1+1e-10):raise ValueError('Worst of corners including TT cannot exceed measured TT')
    return rows


def fit_nominal_worst(train_rows,validation_rows,registry,alpha=.1,seed=20261019,members=64):
    if not 0<alpha<1 or members<2:raise ValueError('Invalid frozen calibration settings')
    assignments={r['lineage_id']:r['split'] for r in registry['lineages']}
    train=_checked(train_rows,'train',assignments)
    validation=_checked(validation_rows,'validation',assignments)
    ratios=[math.log(row['worst_ugb_Hz']/row['nominal_ugb_Hz']) for row in train]
    offset=mean(ratios);rng=random.Random(seed)
    ensemble=[offset]+[mean(rng.choices(ratios,k=len(ratios))) for _ in range(members-1)]
    residuals=sorted(abs(math.log(r['worst_ugb_Hz']/r['nominal_ugb_Hz'])-offset) for r in validation)
    order=math.ceil((len(residuals)+1)*(1-alpha))
    radius=residuals[order-1] if order<=len(residuals) else None
    nominal=[r['nominal_ugb_Hz'] for r in train+validation]
    return {'version':VERSION,'status':'EMPIRICALLY_CALIBRATED' if radius is not None else 'INSUFFICIENT_VALIDATION',
        'target':'minimum actual UGB over the declared TT/SS/FF corners in Hz',
        'input':'actual same-GDS positive-RC nominal TT OP/AC UGB in Hz',
        'log_ratio_offset':offset,'ensemble_log_ratio_offsets':ensemble,
        'validation_absolute_log_residuals':residuals,'validation_radius_log':radius,
        'alpha':alpha,'seed':seed,'nominal_support_Hz':[min(nominal),max(nominal)],
        'train_measurements':len(train),'validation_measurements':len(validation),
        'train_source_lineages':sorted({r['parent_lineage'] for r in train}),
        'validation_source_lineages':sorted({r['parent_lineage'] for r in validation}),
        'coefficient_fit_split':'train_only','residual_and_support_selection_split':'train_and_validation_only',
        'train_rows':train,'validation_rows':validation,
        'limitations':'Correlated configurations and few independent sources; empirical intervals, no universal coverage guarantee. OOD or insufficient validation forces full evaluation.',
        'S2_is_established_by_prediction':False,'formal_calibration_freeze':False}


class NominalWorstCalibration:
    def __init__(self,artifact):
        if artifact.get('version')!=VERSION:raise ValueError('Unknown UGB calibration version')
        self.artifact=artifact

    def predict(self,tt_ugb_Hz):
        if type(tt_ugb_Hz) not in (int,float) or not math.isfinite(tt_ugb_Hz) or tt_ugb_Hz<=0:
            raise ValueError('Prediction requires positive finite actual nominal UGB')
        a=self.artifact;low,high=a['nominal_support_Hz']
        ood=not low<=tt_ugb_Hz<=high
        unavailable=a['validation_radius_log'] is None
        forced=ood or unavailable
        center=tt_ugb_Hz*math.exp(a['log_ratio_offset'])
        spread=pstdev(a['ensemble_log_ratio_offsets'])
        radius=(a['validation_radius_log'] or 0)+spread
        # TT belongs to the worst-corner set, so it is a physical upper bound.
        lower=0. if forced else center*math.exp(-radius)
        upper=tt_ugb_Hz if forced else min(tt_ugb_Hz,center*math.exp(radius))
        return {'prediction_ugb_Hz':center,'lower_ugb_Hz':lower,'upper_ugb_Hz':upper,
            'ensemble_std_log_ratio':spread,'force_full':forced,'nominal_input_out_of_support':ood,
            'reason':'nominal_input_out_of_support' if ood else 'insufficient_validation' if unavailable else 'empirical_validation_interval',
            'prediction_is_S2':False}
