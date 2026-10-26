"""Fresh GDS and exact physical-layer pad control only; never DRC/LVS/PEX/SPICE."""
import json
import os
from pathlib import Path
import shutil
import sys


def check_pads(gds):
    import gdstk
    library = gdstk.read_gds(gds); top, = library.top_level()
    if library.unit != 1e-6:
        raise ValueError('Expected the original micrometre GDS units')
    precision = library.precision / library.unit
    all_polygons = top.get_polygons()
    metals = {layer: [p for p in all_polygons if (p.layer, p.datatype) == (layer, 20)] for layer in [69, 70]}
    labels = top.get_labels(); results = []
    if sorted(l.text for l in labels) != ['IOUT1', 'IOUT2', 'IREF', 'VSS']:
        raise ValueError('Fresh ratio source has unexpected named labels')
    for name in ['IREF', 'VSS']:
        label, = [l for l in labels if l.text == name]
        if (label.layer, label.texttype) != (70, 5):
            raise ValueError('Global pin does not map to the expected physical Metal3 label layer')
        x, y = label.origin
        target = gdstk.rectangle((x - .25, y - .25), (x + .25, y + .25))
        uncovered = gdstk.boolean([target], metals[70], 'not', precision=precision)
        obsolete = gdstk.boolean([target], metals[69], 'and', precision=precision)
        results.append({'pin': name, 'center_um': [x, y], 'expected_physical_layer_datatype': [70, 20],
            'pad_width_um': .5, 'pad_area_um2': .25,
            'uncovered_target_area_um2': sum(p.area() for p in uncovered),
            'obsolete_physical_met2_area_at_pad_um2': sum(p.area() for p in obsolete),
            'passed': not uncovered and not obsolete})
    return {'passed': all(r['passed'] for r in results), 'pad_controls': results,
        'actual_GDS_precision_um': precision, 'actual_top': top.name}


def main():
    prepared = Path(os.environ['PROBE_INPUT']); sys.path.insert(0, str(prepared / 'source_snapshot'))
    from src.train_generators.ratio_source import write_gds
    from src.train_generators.ratio_source_intent import point
    from glayout import sky130
    row = point(2, 1); out = Path.cwd()
    shutil.copyfile(prepared / 'source_snapshot/src/train_generators/ratio_source.py', out / 'actual_ratio_source.py')
    (out / 'configuration.json').write_text(json.dumps(row, indent=2) + '\n')
    gds = write_gds(row['parameters'], out)
    result = {'scope': 'DEVELOPMENT_FRESH_S0_PHYSICAL_LAYER_CONTROL_ONLY_NOT_S1_S2',
        'source_preparation': str(prepared), 'configuration_id': row['configuration_id'],
        'gds': str(gds), 'S0': True, 'S1_S2_not_established': True,
        'actual_runtime_generic_mappings': {key: list(sky130.get_glayer(key)) for key in ['met3', 'met4', 'met5']},
        'new_tool_calls': {'GDS_generation': 1, 'DRC': 0, 'LVS': 0, 'PEX': 0, 'SPICE': 0},
        **check_pads(gds)}
    (out / 'pad_smoke.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 2)


if __name__ == '__main__':
    main()
