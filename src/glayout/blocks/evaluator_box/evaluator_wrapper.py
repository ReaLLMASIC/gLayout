# comprehensive evaluator
# comprehensive evaluator
import os
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from gdsfactory.typings import Component

# Make run_pex.sh executable if it exists
_evaluator_box_dir = Path(__file__).parent
_run_pex_script = _evaluator_box_dir / "run_pex.sh"
if _run_pex_script.exists():
    os.chmod(_run_pex_script, 0o755)

from glayout.blocks.evaluator_box.verification import run_verification
from glayout.blocks.evaluator_box.physical_features import run_physical_feature_extraction

def get_next_filename(base_name="evaluation", extension=".json"):
    """
    Generates the next available filename with a numerical suffix, starting from 1.
    e.g., base_name_1.json, base_name_2.json, etc.
    """
    i = 1
    while True:
        filename = f"{base_name}_{i}{extension}"
        if not os.path.exists(filename):
            return filename
        i += 1

def run_evaluation(layout_path: str, component_name: str, top_level: Component) -> dict:
    """
    The main evaluation wrapper. Runs all evaluation modules and combines results.
    """
    print(f"--- Starting Comprehensive Evaluation for {component_name} ---")

    # Deletes known intermediate and report files/directories for a given component to ensure a clean run.
    print(f"Cleaning up intermediate files for component '{component_name}'...")
    
    items_to_delete = [
        f"{component_name}.res.ext",
        f"{component_name}.lvs.rpt",
        f"{component_name}_lvs.rpt",
        f"{component_name}.drc.rpt",
        f"{component_name}_drc_out",  # New DRC output directory
        f"{component_name}_lvs_out",  # New LVS output directory
        f"{component_name}.nodes",
        f"{component_name}.sim",
        f"{component_name}.pex.spice",
        f"{component_name}_pex.spice"
    ]
    
    for f_path in items_to_delete:
        try:
            if os.path.isdir(f_path):
                shutil.rmtree(f_path)
                print(f"  - Deleted directory: {f_path}")
            elif os.path.exists(f_path):
                os.remove(f_path)
                print(f"  - Deleted: {f_path}")
        except OSError as e:
            print(f"  - Warning: Could not delete {f_path}. Error: {e}")

    # Run verification module
    print("Running verification checks (DRC, LVS)...")
    verification_results = run_verification(layout_path, component_name, top_level)
    
    # Run physical features module
    print("Running physical feature extraction (PEX, Area, Symmetry)...")
    physical_results = run_physical_feature_extraction(layout_path, component_name, top_level)
    
    # Combine results into a single dictionary
    final_results = {
        "component_name": component_name,
        "timestamp": datetime.now().isoformat(),
        "drc_lvs_fail": not (verification_results["drc"]["is_pass"] and verification_results["lvs"]["is_pass"]),
        **verification_results,
        **physical_results
    }
    
    # Generate the output JSON filename
    output_filename = get_next_filename(base_name=component_name, extension=".json")
    
    # Write the results dictionary to a JSON file
    with open(output_filename, 'w') as json_file:
        json.dump(final_results, json_file, indent=4)        
    print(f"--- Evaluation complete. Results saved to {output_filename} ---")
    
    return final_results
