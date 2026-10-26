"""Write the new train-intended source assignment and fixed9point ideal input."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src.train_generators.ratio_source_intent import CIRCUIT, K_VALUES, LINEAGE, R_VALUES, point, reference_spice


def prepare(output):
    if output.exists():
        raise ValueError('Do not overwrite a prior domain or retrospectively change its thresholds')
    output.mkdir(parents=True); (output / 'references').mkdir(); (output / 'parameters').mkdir()
    points = [point(k, ratio) for k in K_VALUES for ratio in R_VALUES]
    for row in points:
        target = output / row['reference_file']; target.write_text(reference_spice(row)); target.chmod(0o444)
        target = output / 'parameters' / (row['configuration_id'] + '.json')
        target.write_text(json.dumps(row['parameters'], indent=2) + '\n'); target.chmod(0o444)
    lineage = {'status': 'DRAFT_TRAIN_ONLY_ASSIGNMENT_PENDING_INDEPENDENT_QUALIFICATION',
        'lineage_id': LINEAGE, 'split': 'train', 'circuit_id': CIRCUIT,
        'topology_families': ['diode_biased_two_output_ratio_current_source_array'],
        'parent_lineages': [], 'qualified_independent_source_lineages_added': 0,
        'editable_source_files': ['src/train_generators/ratio_source.py'],
        'source_package_files': ['src/__init__.py', 'src/train_generators/__init__.py', 'src/train_generators/ratio_source.py'],
        'frozen_common_source_files': ['src/generators/__init__.py', 'src/generators/terminal_access.py'],
        'source_cli': 'python src/train_generators/ratio_source.py --configuration parameters.json --output candidate.gds; configuration is the declared point.parameters object.',
        'trusted_reference_and_bench_files': ['src/train_generators/ratio_source_intent.py',
                                             'src/train_generators/ratio_source_bench.py'],
        'shared_frozen_dependencies': ['gdsfactory7.7 geometry/component API', 'glayout.primitives.fet.nmos',
            'glayout.primitives.via_gen.via_stack', 'glayout.sky130 mappedPDK', 'src/generators/terminal_access.py'],
        'shared_access_disclosure': 'Only terminal escape, rectangle/wire/via/pin/flatten helpers reused. That library has no circuit graph, placement or net route policy. Source/body/gate/output placement and H bias tree are newly authored here.',
        'excluded_dependencies': ['all evaluation/validation circuit assemblies', 'glayout.cells', 'glayout.blocks',
                                  'glayout.sharing compiler', 'textbook_sharing'],
        'authorship': 'New high-level assembly written for this train-only proposal, without reading or calling any evaluation assembly for this task. Shared common terminal-access source was read and is disclosed.',
        'holdout_statement': 'No Miller or FVF OTA graph/helper/data. A current-source graph is not a new topology holdout; source independence still needs actual import/ancestry/geometry qualification.',
        'global_registry_modified': False, 'frozen_source_assignments_modified': False,
        'required_before_formal_collection': ['Nine-point ideal qualification with full failures retained',
            'Actual anchor and full nine-point full-ruleDRC/independentN LVS/deviceintent/positivefullRC/postlayoutcorner qualification',
            'Prospective global source-assignment extension preserving every prior train/validation/test source assignment',
            'New frozen source/trusted evaluator/contracts/labels/initialstates/context preflight before fresh model proposals'],
        'formal_training_examples': 0, 'model_calls': 0, 'physical_runs': 0}
    declaration = {'status': 'DRAFT_NEW_TRAIN_SOURCE_NINE_POINT_IDEAL_QUALIFICATION',
        'lineage_id': LINEAGE, 'circuit_id': CIRCUIT, 'split': 'train', 'configurations': points,
        'whole_grid_definition': {'K': list(K_VALUES), 'R': list(R_VALUES), 'points': 9, 'no_post_result_filtering': True},
        'reference_binding': 'Each readonly literal per-finger N is independently generated from its own declared K/R/sizing and fixed transistor graph; layout source cannot redefine it.',
        'counts': {'ideal_qualified_points': 0, 'physical_qualified_points': 0, 'model_calls': 0,
                   'formal_training_examples': 0, 'qualified_independent_source_lineages_added': 0}}
    for filename, value in [('lineage_declaration.json', lineage), ('domain.json', declaration)]:
        target = output / filename; target.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n'); target.chmod(0o444)
    return {'status': declaration['status'], 'points': 9, 'input_directory': str(output),
            'new_ideal_calls': 0, 'new_physical_calls': 0, 'new_model_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'configs/development/ratio_source_array_v1')
    print(json.dumps(prepare(parser.parse_args().output), indent=2))
