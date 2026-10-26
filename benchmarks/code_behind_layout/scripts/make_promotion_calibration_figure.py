"""Plot actual train/validation AC calibration with its explicit support limit."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.promotion_calibration import NominalWorstCalibration


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--output-stem', type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.artifact.read_text())
    model = NominalWorstCalibration(value)
    low, high = value['nominal_support_Hz']
    x = np.linspace(low, high, 200)
    predictions = [model.predict(float(v)) for v in x]
    fig, ax = plt.subplots(figsize=(5.8, 3.7), constrained_layout=True)
    ax.axvspan(0, low/1e6, color='#e4e7ea', alpha=0.8, label='Outside support: full evaluation')
    ax.fill_between(x/1e6, [p['lower_ugb_Hz']/1e6 for p in predictions],
        [p['upper_ugb_Hz']/1e6 for p in predictions], color='#377eb8', alpha=.16,
        label='Empirical validation band + ensemble spread')
    ax.plot(x/1e6, [p['prediction_ugb_Hz']/1e6 for p in predictions], color='#377eb8', linewidth=1.2,
        label='Train-only log-ratio model')
    rows = []
    for field, label, color, marker in [('train_rows', 'Train: 9 configs / 1 source', '#377eb8', 'o'),
                                        ('validation_rows', 'Validation: 9 configs / 1 source', '#d95f02', 's')]:
        data = value[field]
        ax.scatter([p['nominal_ugb_Hz']/1e6 for p in data], [p['worst_ugb_Hz']/1e6 for p in data],
            s=30, color=color, marker=marker, linewidths=.5, edgecolors='white', label=label, zorder=5)
        for point in data:
            rows.append({'split': point['split'], 'parent_lineage': point['parent_lineage'],
                'measurement_id': point['measurement_id'], 'nominal_ugb_Hz': point['nominal_ugb_Hz'],
                'worst_ugb_Hz': point['worst_ugb_Hz'], 'raw_evidence': json.dumps(point['raw_evidence'])})
    ax.set(xlabel='Measured nominal TT UGB (MHz)', ylabel='Measured minimum TT/SS/FF UGB (MHz)',
        xlim=(5, 45), ylim=(0, 43))
    ax.grid(alpha=.18)
    ax.legend(loc='upper left', fontsize=7.2, frameon=False)
    ax.text(.98, .03, 'Development AC calibration; prediction never establishes S2.\nConfigurations are correlated within each source.',
        transform=ax.transAxes, ha='right', va='bottom', fontsize=7)
    args.output_stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ('pdf', 'png'):
        fig.savefig(args.output_stem.with_suffix('.'+suffix), dpi=220)
    with args.output_stem.with_suffix('.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({'plotted_actual_measurements': len(rows), 'sources': 2,
        'artifact': str(args.artifact), 'output_stem': str(args.output_stem), 'formal_result': False}))


if __name__ == '__main__':
    main()
