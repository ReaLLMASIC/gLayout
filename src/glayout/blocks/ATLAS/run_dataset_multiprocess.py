#!/usr/bin/env python3
"""
Generic Dataset Generator - Supports Multiple Cell Types
Based on the proven approach from generate_fvf_360_robust_fixed.py.

This script generates datasets for various cell types using parameter combinations
from JSON files and performs comprehensive evaluation (DRC, LVS, PEX, Geometry).

Supported cell types:
- txgate: Transmission Gate
- fvf: Flipped Voltage Follower
- lvcm: Low Voltage Current Mirror
- current_mirror: Current Mirror
- diff_pair: Differential Pair
- opamp: Operational Amplifier

Usage:
    python run_dataset_multiprocess.py <params.json> --cell_type <type> --n_cores <n>

Example:
    python run_dataset_multiprocess.py txgate_params.json --cell_type txgate --n_cores 8
    python run_dataset_multiprocess.py fvf_params.json --cell_type fvf --n_cores 8
"""
import logging
import os
import sys
import time
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd

# Suppress overly verbose gdsfactory logging
import warnings
warnings.filterwarnings(
    "ignore", 
    message="decorator is deprecated and will be removed soon.*"
)
warnings.filterwarnings(
    "ignore", 
    message=".*we will remove unlock to discourage use.*"
)
# Also suppress info with "* PDK is now active"
logging.getLogger("gdsfactory").setLevel(logging.WARNING)

# -----------------------------------------------------------------------------
# Ensure the *local* `glayout` package is discoverable *before* we import any
# module that depends on it (e.g. `robust_verification`).
# -----------------------------------------------------------------------------
_here = Path(__file__).resolve()
_glayout_repo_path = _here.parent.parent.parent.parent.parent.parent
pwd_path = Path.cwd().resolve()
print("Current working directory:", pwd_path)
# Fallback hard-coded path if relative logic fails (for robustness when the
# script is moved around). Adjust this if your repo structure changes.
if not _glayout_repo_path.exists():
    _glayout_repo_path = pwd_path / "../../../../"

if _glayout_repo_path.exists() and str(_glayout_repo_path) not in sys.path:
    sys.path.insert(0, str(_glayout_repo_path))

del _here, _glayout_repo_path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# We *delay* importing gdsfactory until *after* the PDK environment variables
# are guaranteed to be correct. Importing it too early locks-in an incorrect
# `PDK_ROOT`, which then causes Magic/Netgen to fall back to the built-in
# "minimum" tech, triggering the dummy fallback reports the user wants to
# avoid.

# Helper to obtain a stable sky130 mapped PDK instance
GLOBAL_SKY130_PDK = None

def get_global_pdk():
    """Return a *stable* sky130_mapped_pdk instance (cached)."""
    global GLOBAL_SKY130_PDK
    if GLOBAL_SKY130_PDK is None:
        from glayout.pdk.sky130_mapped import sky130_mapped_pdk as _pdk
        GLOBAL_SKY130_PDK = _pdk
    return GLOBAL_SKY130_PDK

# Import the shared PDK environment helper so we keep a single source of truth
from robust_verification import ensure_pdk_environment
from contextlib import contextmanager

@contextmanager
def chdir(path: Path):
    """Temporarily change working directory to `path`."""
    prev = Path.cwd()
    try:
        os.makedirs(path, exist_ok=True)
        os.chdir(path)
        yield
    finally:
        os.chdir(prev)

def setup_environment():
    """Set up (or refresh) the PDK environment for this trial.

    We rely on the **shared** `ensure_pdk_environment` helper so that the
    exact same logic is used across the entire code-base. This prevents the
    two implementations from drifting apart and guarantees that *every*
    entry-point resets the PDK environment in one atomic `os.environ.update`
    call.
    """

    pdk_root = ensure_pdk_environment()

    # Now that the environment is correctly set, it is finally safe to import
    # gdsfactory and disable its Component cache to avoid stale classes.
    try:
        import gdsfactory as gf
    except ImportError:
        import gdsfactory as gf  # should always succeed now
    if hasattr(gf, 'CONFIG') and hasattr(gf.CONFIG, 'use_cache'):
        gf.CONFIG.use_cache = False
    else:
        # Newer gdsfactory versions expose settings via gf.config.CONF
        try:
            gf.config.CONF.use_cache = False  # type: ignore
        except Exception:
            pass

    # Ensure the `glayout` package directory is discoverable regardless of
    # how the user launches the script.
    glayout_path = pwd_path / "../../../../"
    print("Using glayout path:", glayout_path)
    if glayout_path not in sys.path:
        sys.path.insert(0, glayout_path)

    # Prepend to PYTHONPATH so subprocesses (if any) inherit the correct path
    current_pythonpath = os.environ.get('PYTHONPATH', '')
    if glayout_path not in current_pythonpath.split(":"):
        os.environ['PYTHONPATH'] = f"{glayout_path}:{current_pythonpath}"

    logger.info(f"Environment refreshed: PDK_ROOT={pdk_root}")
    return pdk_root

def robust_cell_generator(cell_type, **params):
    """Return a cell component with a *fresh* MappedPDK every call.
    
    This function dynamically loads the appropriate cell module and function
    based on cell_type from the cell registry, then generates the component.
    
    Args:
        cell_type: String identifier for cell type (e.g., "txgate", "fvf")
        **params: Cell-specific parameters (width, length, fingers, etc.)
    
    Returns:
        gdsfactory Component with the generated cell
    """
    from cell_registry import get_cell_config
    
    config = get_cell_config(cell_type)
    
    # Dynamic module import
    module = __import__(config["module"], fromlist=[config["function"]])
    cell_func = getattr(module, config["function"])
    
    # Use a *stable* PDK instance across all trials to avoid Pydantic class mismatch
    pdk = get_global_pdk()
    
    # Generate the cell component
    comp = cell_func(pdk=pdk, **params)
    
    # Add physical pin shapes/labels if label function is defined
    if config["label_function"]:
        try:
            label_func = getattr(module, config["label_function"])
            comp = label_func(comp, pdk)
        except Exception as e:
            logger.warning(f"Failed to add pin labels to {config['display_name']}: {e}")
    
    return comp

def load_cell_parameters_from_json(json_file, cell_type):
    """Load cell parameters from the generated JSON file.
    
    Args:
        json_file: Path to JSON file containing parameter combinations
        cell_type: Cell type identifier (e.g., "txgate", "fvf")
    
    Returns:
        List of parameter dictionaries
    """
    from cell_registry import get_cell_config
    
    config = get_cell_config(cell_type)
    json_path = Path(json_file)
    
    if not json_path.exists():
        raise FileNotFoundError(f"Parameter file not found: {json_file}")
    
    with open(json_path, 'r') as f:
        parameters = json.load(f)
    
    logger.info(f"Loaded {len(parameters)} {config['display_name']} parameter combinations from {json_file}")
    
    # Log parameter distribution statistics (generic approach)
    if parameters:
        log_parameter_statistics(parameters, config)
    
    return parameters


def log_parameter_statistics(parameters, config):
    """Log statistics about parameter distribution based on cell type.
    
    Args:
        parameters: List of parameter dictionaries
        config: Cell configuration from registry
    """
    param_format = config.get('param_format', 'single')
    
    # Handle complementary parameters (NMOS/PMOS tuples)
    if param_format == 'complementary':
        if 'width' in parameters[0]:
            widths_nmos = [p["width"][0] for p in parameters]
            widths_pmos = [p["width"][1] for p in parameters]
            logger.info(f"Parameter ranges:")
            logger.info(f"  NMOS width: {min(widths_nmos):.2f} - {max(widths_nmos):.2f} μm")
            logger.info(f"  PMOS width: {min(widths_pmos):.2f} - {max(widths_pmos):.2f} μm")
        
        if 'length' in parameters[0]:
            lengths_nmos = [p["length"][0] for p in parameters]
            lengths_pmos = [p["length"][1] for p in parameters]
            logger.info(f"  NMOS length: {min(lengths_nmos):.3f} - {max(lengths_nmos):.3f} μm")
            logger.info(f"  PMOS length: {min(lengths_pmos):.3f} - {max(lengths_pmos):.3f} μm")
        
        # Show first few examples
        logger.info(f"First 3 parameter combinations:")
        for i, params in enumerate(parameters[:3], 1):
            nmos_w, pmos_w = params.get("width", (0, 0))
            nmos_l, pmos_l = params.get("length", (0, 0))
            nmos_f, pmos_f = params.get("fingers", (0, 0))
            nmos_m, pmos_m = params.get("multipliers", (1, 1))
            
            logger.info(f"  Sample {i}: NMOS({nmos_w:.2f}μm/{nmos_l:.3f}μm, {nmos_f}f×{nmos_m}), "
                       f"PMOS({pmos_w:.2f}μm/{pmos_l:.3f}μm, {pmos_f}f×{pmos_m})")
    
    # Handle mixed parameters (LVCM: width tuple, length scalar)
    elif param_format == 'mixed':
        if 'width' in parameters[0]:
            widths_0 = [p["width"][0] for p in parameters]
            widths_1 = [p["width"][1] for p in parameters]
            logger.info(f"Parameter ranges:")
            logger.info(f"  Width[0]: {min(widths_0):.2f} - {max(widths_0):.2f} μm")
            logger.info(f"  Width[1]: {min(widths_1):.2f} - {max(widths_1):.2f} μm")
        
        if 'length' in parameters[0]:
            lengths = [p["length"] for p in parameters]
            logger.info(f"  Length: {min(lengths):.3f} - {max(lengths):.3f} μm")
    
    # Handle single scalar parameters
    elif param_format == 'single':
        logger.info(f"Parameter ranges:")
        for key in ['width', 'length']:
            if key in parameters[0]:
                values = [p[key] for p in parameters]
                logger.info(f"  {key.capitalize()}: {min(values):.2f} - {max(values):.2f} μm")
    
    # Handle complex parameters (opamp)
    elif param_format == 'complex':
        logger.info(f"Complex parameter structure with {len(parameters[0])} top-level keys")
        logger.info(f"Keys: {list(parameters[0].keys())}")

def cleanup_files():
    """Clean up generated files in working directory"""
    files_to_clean = [
        "*.gds", "*.drc.rpt", "*.lvs.rpt", "*.ext", "*.spice", 
        "*.res.ext", "*.sim", "*.nodes", "*_lvsmag.spice", "*_sim.spice",
        "*_pex.spice", "*.pex.spice"
    ]
    for pattern in files_to_clean:
        import glob
        for file in glob.glob(pattern):
            try:
                os.remove(file)
            except OSError:
                pass

def make_json_serializable(obj):
    """Convert complex objects to JSON-serializable formats"""
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, '__dict__'):
        try:
            return make_json_serializable(obj.__dict__)
        except:
            return str(obj)
    elif hasattr(obj, '__class__') and 'PDK' in str(obj.__class__):
        return f"PDK_object_{getattr(obj, 'name', 'unknown')}"
    else:
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)
# Parallelized
def run_single_evaluation(trial_num, params, output_dir, cell_type):
    """Run a single cell evaluation in its own isolated working directory.
    
    Args:
        trial_num: Trial number (used for seeding and naming)
        params: Parameter dictionary for this trial
        output_dir: Base output directory
        cell_type: Cell type identifier (e.g., "txgate", "fvf")
    
    Returns:
        Dictionary with evaluation results
    """
    from cell_registry import get_cell_config
    
    trial_start = time.time()
    config = get_cell_config(cell_type)

    # Per-trial working dir (all scratch files live here)
    trial_work_dir = Path(output_dir) / "_work" / f"sample_{trial_num:04d}"
    # Per-trial final results dir (curated outputs copied here)
    trial_out_dir = Path(output_dir) / f"sample_{trial_num:04d}"

    try:
        with chdir(trial_work_dir):
            # === DETERMINISTIC SEEDING FIX ===
            import random
            import numpy as np
            base_seed = trial_num * 1000
            random.seed(base_seed)
            np.random.seed(base_seed)
            os.environ['PYTHONHASHSEED'] = str(base_seed)
            logger.info(f"Trial {trial_num}: Set deterministic seed = {base_seed}")

            # Setup environment for each trial (safe in subprocess)
            setup_environment()

            # Clear any cached gdsfactory Components / PDKs to avoid stale class refs
            try:
                import gdsfactory as gf
            except ImportError:
                import gdsfactory as gf
            if hasattr(gf, 'clear_cache'):
                gf.clear_cache()
            if hasattr(gf, 'clear_cell_cache'):
                gf.clear_cell_cache()
            try:
                if hasattr(gf, '_CACHE'):
                    gf._CACHE.clear()
                if hasattr(gf.Component, '_cell_cache'):
                    gf.Component._cell_cache.clear()
                if hasattr(gf, 'CONFIG'):
                    if hasattr(gf.CONFIG, 'use_cache'):
                        gf.CONFIG.use_cache = False
                    if hasattr(gf.CONFIG, 'cache'):
                        gf.CONFIG.cache = False
            except Exception as e:
                logger.warning(f"Could not clear some gdsfactory caches: {e}")

            # Fresh PDK import per trial/process
            import importlib, sys
            if 'glayout.pdk.sky130_mapped' in sys.modules:
                importlib.reload(sys.modules['glayout.pdk.sky130_mapped'])
            from glayout.pdk.sky130_mapped import sky130_mapped_pdk
            pdk = sky130_mapped_pdk

            # Create and name component (dynamic naming based on cell type)
            component_name = f"{config['prefix']}_sample_{trial_num:04d}"
            comp = robust_cell_generator(cell_type, **params)
            comp.name = component_name

            # Write GDS into the trial's **work** dir
            gds_file = f"{component_name}.gds"
            comp.write_gds(gds_file)
            gds_path = Path.cwd() / gds_file  # absolute path

            # Run comprehensive evaluation (DRC, LVS, PEX, Geometry)
            from evaluator_wrapper import run_evaluation
            comprehensive_results = run_evaluation(str(gds_path), component_name, comp)
            drc_result = comprehensive_results["drc"]["is_pass"]
            lvs_result = comprehensive_results["lvs"]["is_pass"]

            # Extract PEX and geometry data
            pex_data = comprehensive_results.get("pex", {})
            geometry_data = comprehensive_results.get("geometric", {})

            # Copy curated artifacts to the **final** per-trial results dir
            trial_out_dir.mkdir(parents=True, exist_ok=True)
            files_to_copy = [
                gds_file,
                f"{component_name}.drc.rpt",
                f"{component_name}.lvs.rpt",
                f"{component_name}_pex.spice",
                f"{component_name}.res.ext",
                f"{component_name}.ext",
                f"{component_name}_lvsmag.spice",
                f"{component_name}_sim.spice",
            ]
            for file_path in files_to_copy:
                p = Path(file_path)
                if p.exists():
                    shutil.copy(p, trial_out_dir / p.name)

            trial_time = time.time() - trial_start
            success_flag = drc_result and lvs_result

            result = {
                "sample_id": trial_num,
                "component_name": component_name,
                "cell_type": cell_type,
                "success": success_flag,
                "drc_pass": drc_result,
                "lvs_pass": lvs_result,
                "execution_time": trial_time,
                "parameters": make_json_serializable(params),
                "output_directory": str(trial_out_dir),
                # PEX data
                "pex_status": pex_data.get("status", "not run"),
                "total_resistance_ohms": pex_data.get("total_resistance_ohms", 0.0),
                "total_capacitance_farads": pex_data.get("total_capacitance_farads", 0.0),
                # Geometry data
                "area_um2": geometry_data.get("raw_area_um2", 0.0),
                "symmetry_horizontal": geometry_data.get("symmetry_score_horizontal", 0.0),
                "symmetry_vertical": geometry_data.get("symmetry_score_vertical", 0.0),
            }

            # Generic parameter summary (handle different param formats)
            param_summary = format_param_summary(params, config)
            pex_status_short = "✓" if pex_data.get("status") == "PEX Complete" else "✗"
            
            logger.info(
                f"✅ Sample {trial_num:04d} completed in {trial_time:.1f}s "
                f"(DRC: {'✓' if drc_result else '✗'}, LVS: {'✓' if lvs_result else '✗'}, PEX: {pex_status_short}) "
                f"[{param_summary}]"
            )
            return result

    except Exception as e:
        trial_time = time.time() - trial_start
        logger.error(f"❌ Sample {trial_num:04d} failed: {e}")
        return {
            "sample_id": trial_num,
            "component_name": f"{config['prefix']}_sample_{trial_num:04d}",
            "cell_type": cell_type,
            "success": False,
            "error": str(e),
            "execution_time": trial_time,
            "parameters": make_json_serializable(params),
        }

    finally:
        # Clean ONLY this trial's scratch via CWD-scoped globbing
        with chdir(trial_work_dir):
            cleanup_files()
            try:
                import gdsfactory as gf
            except ImportError:
                import gdsfactory as gf
            if hasattr(gf, 'clear_cache'):
                gf.clear_cache()
            if hasattr(gf, 'clear_cell_cache'):
                gf.clear_cell_cache()


def format_param_summary(params, config):
    """Format parameter summary string based on parameter format.
    
    Args:
        params: Parameter dictionary
        config: Cell configuration from registry
    
    Returns:
        Formatted string summarizing key parameters
    """
    param_format = config.get('param_format', 'single')
    
    try:
        if param_format == 'complementary':
            nmos_w, pmos_w = params.get("width", (0, 0))
            nmos_f, pmos_f = params.get("fingers", (0, 0))
            return f"NMOS:{nmos_w:.1f}μm×{nmos_f}f, PMOS:{pmos_w:.1f}μm×{pmos_f}f"
        
        elif param_format == 'mixed':
            w0, w1 = params.get("width", (0, 0))
            length = params.get("length", 0)
            return f"W:[{w0:.1f},{w1:.1f}]μm, L:{length:.3f}μm"
        
        elif param_format == 'single':
            width = params.get("width", 0)
            length = params.get("length", 0)
            fingers = params.get("fingers", 0)
            return f"W:{width:.1f}μm, L:{length:.3f}μm, F:{fingers}"
        
        elif param_format == 'complex':
            # For opamp, just show number of parameters
            return f"{len(params)} params"
        
        else:
            return str(params)[:50]
    except Exception:
        return "params"

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
# Parallelized
def run_dataset_generation(parameters, output_dir, cell_type, max_workers=1):
    """Run the dataset generation for all parameters (in parallel, per-trial isolation).
    
    Args:
        parameters: List of parameter dictionaries
        output_dir: Output directory path
        cell_type: Cell type identifier (e.g., "txgate", "fvf")
        max_workers: Number of parallel workers
    
    Returns:
        Tuple of (success, passed_count, total_count)
    """
    from cell_registry import get_cell_config
    
    config = get_cell_config(cell_type)
    n_samples = len(parameters)
    logger.info(f"🚀 Starting {config['display_name']} Dataset Generation for {n_samples} samples")

    # Prepare top-level dirs
    out_dir = Path(output_dir)
    work_root = out_dir / "_work"
    out_dir.mkdir(exist_ok=True)
    work_root.mkdir(exist_ok=True)

    # Save parameter configuration
    param_file = out_dir / f"{config['prefix']}_parameters.json"
    with open(param_file, 'w') as f:
        json.dump(parameters, f, indent=2)

    results = []
    total_start = time.time()
    logger.info(f"📊 Processing {n_samples} {config['display_name']} samples in parallel...")
    logger.info(f"Using {max_workers} parallel workers")

    futures = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for i, params in enumerate(parameters, start=1):
            futures.append(executor.submit(run_single_evaluation, i, params, output_dir, cell_type))

        completed = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1

            # Progress logging similar to your sequential version
            if completed % 10 == 0 or completed < 5:
                success_rate = (
                    sum(1 for r in results if r.get("success")) / len(results) * 100
                    if results else 0.0
                )
                elapsed = time.time() - total_start
                avg_time = elapsed / completed
                eta = avg_time * (n_samples - completed)
                logger.info(
                    f"📈 Progress: {completed}/{n_samples} "
                    f"({completed/n_samples*100:.1f}%) - "
                    f"Success: {success_rate:.1f}% - "
                    f"Elapsed: {elapsed/60:.1f}m - ETA: {eta/60:.1f}m"
                )

    # Final summary (unchanged)
    total_time = time.time() - total_start
    successful = [r for r in results if r.get("success")]
    success_rate = (len(successful) / len(results) * 100) if results else 0.0

    logger.info(f"\n🎉 {config['display_name']} Dataset Generation Complete!")
    logger.info(f"📊 Total time: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
    logger.info(f"📈 Success rate: {len(successful)}/{len(results)} ({success_rate:.1f}%)")

    if successful:
        drc_passes = sum(1 for r in successful if r.get("drc_pass"))
        lvs_passes = sum(1 for r in successful if r.get("lvs_pass"))
        pex_passes = sum(1 for r in successful if r.get("pex_status") == "PEX Complete")
        avg_time = sum(r["execution_time"] for r in successful) / len(successful)
        avg_area = sum(r.get("area_um2", 0) for r in successful) / len(successful)
        avg_sym_h = sum(r.get("symmetry_horizontal", 0) for r in successful) / len(successful)
        avg_sym_v = sum(r.get("symmetry_vertical", 0) for r in successful) / len(successful)

        logger.info(f"   DRC passes: {drc_passes}/{len(successful)} ({drc_passes/len(successful)*100:.1f}%)")
        logger.info(f"   LVS passes: {lvs_passes}/{len(successful)} ({lvs_passes/len(successful)*100:.1f}%)")
        logger.info(f"   PEX passes: {pex_passes}/{len(successful)} ({pex_passes/len(successful)*100:.1f}%)")
        logger.info(f"   Average time per sample: {avg_time:.1f}s")
        logger.info(f"   Average area: {avg_area:.2f} μm²")
        logger.info(f"   Average symmetry (H/V): {avg_sym_h:.3f}/{avg_sym_v:.3f}")

    failed = [r for r in results if not r.get("success")]
    if failed:
        logger.info(f"\n⚠️ Failed Samples Summary ({len(failed)} total):")
        error_counts = {}
        for r in failed:
            error = r.get("error", "Unknown error")
            error_key = error.split('\n')[0][:50]
            error_counts[error_key] = error_counts.get(error_key, 0) + 1
        for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"   {count}x: {error}")

    # Persist results/summary (with dynamic naming)
    results_file = out_dir / f"{config['prefix']}_results.json"
    try:
        serializable_results = make_json_serializable(results)
        with open(results_file, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        logger.info(f"📄 Results saved to: {results_file}")
    except Exception as e:
        logger.error(f"Failed to save JSON results: {e}")

    df_results = pd.DataFrame(results)
    summary_file = out_dir / f"{config['prefix']}_summary.csv"
    df_results.to_csv(summary_file, index=False)
    logger.info(f"📄 Summary saved to: {summary_file}")

    # Threshold as before
    return success_rate >= 50, len(successful), len(results)

import argparse
def main():
    """Main function for Dataset generation"""
    from cell_registry import list_supported_cells

    # Argument parsing
    parser = argparse.ArgumentParser(description="Generic Dataset Generator - Supports Multiple Cell Types")
    parser.add_argument("json_file",    type=str,                   help="Path to the JSON file containing parameters")
    parser.add_argument("--cell_type",  type=str, required=True,    
                       choices=list_supported_cells(),
                       help="Cell type to generate (txgate, fvf, lvcm, current_mirror, diff_pair, opamp)")
    parser.add_argument("--n_cores",    type=int, default=1,        help="Number of CPU cores to use") # Number of CPU cores to use, default=1
    parser.add_argument("--output_dir", type=str, default="result", help="Output directory for the generated dataset")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatic yes to prompts")
    args = parser.parse_args()
    json_file = Path(args.json_file).resolve()
    output_dir = args.output_dir
    cell_type = args.cell_type
    n_cores = args.n_cores if args.n_cores > 0 else 1
    if n_cores > (os.cpu_count()):
        n_cores = os.cpu_count()
    
    # Get cell configuration
    from cell_registry import get_cell_config
    config = get_cell_config(cell_type)
    
    print("="*30+" Arguments "+"="*30)
    print(f"Cell Type: {config['display_name']} ({cell_type})")
    print(f"Using {n_cores} CPU cores for parallel processing")
    print(f"Input file: {json_file}")
    print(f"Output will be saved to: {output_dir}")
    print(f"Output prefix: {config['prefix']}_*")
    print("="*70)
    
    # Load parameters from JSON
    try:
        parameters = load_cell_parameters_from_json(json_file, cell_type)
        n_samples = len(parameters)
        print(f"Loaded {n_samples} parameter combinations")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print(f"Make sure you have run 'python elhs.py' first to generate the parameters")
        return False
    except Exception as e:
        print(f"❌ Error loading parameters: {e}")
        return False
    
    # Show parameter distribution (generic)
    param_format = config.get('param_format', 'single')
    if param_format == 'complementary' and 'width' in parameters[0]:
        widths_nmos = [p["width"][0] for p in parameters]
        widths_pmos = [p["width"][1] for p in parameters]
        print(f"\n📋 Parameter Distribution:")
        print(f"   NMOS width range: {min(widths_nmos):.2f} - {max(widths_nmos):.2f} μm")
        print(f"   PMOS width range: {min(widths_pmos):.2f} - {max(widths_pmos):.2f} μm")
        if 'fingers' in parameters[0]:
            print(f"   Finger combinations: {len(set(tuple(p['fingers']) for p in parameters))} unique")
        if 'multipliers' in parameters[0]:
            print(f"   Multiplier combinations: {len(set(tuple(p['multipliers']) for p in parameters))} unique")
        
        # Show examples
        print(f"\n📋 Sample Parameter Examples:")
        for i, params in enumerate(parameters[:3], 1):
            nmos_w, pmos_w = params["width"]
            nmos_l, pmos_l = params["length"]
            nmos_f, pmos_f = params.get("fingers", (0, 0))
            nmos_m, pmos_m = params.get("multipliers", (1, 1))
            print(f"   {i}. NMOS: {nmos_w:.2f}μm/{nmos_l:.3f}μm×{nmos_f}f×{nmos_m} | "
                  f"PMOS: {pmos_w:.2f}μm/{pmos_l:.3f}μm×{pmos_f}f×{pmos_m}")
    else:
        print(f"\n📋 Parameter Distribution:")
        print(f"   {n_samples} parameter combinations loaded")
        print(f"   Parameter keys: {list(parameters[0].keys())}")
    
    # Prompt user to continue
    if not args.yes:
        print(f"\nContinue with {config['display_name']} dataset generation for {n_samples} samples? (y/n): ", end="")
        response = input().lower().strip()
        if response != 'y':
            print("Stopping as requested.")
            return True
    
    # Generate dataset
    print(f"\nStarting generation of {n_samples} {config['display_name']} samples...")
    success, passed, total = run_dataset_generation(parameters, output_dir, cell_type, max_workers=n_cores)
    
    if success:
        print(f"\n🎉 {config['display_name']} dataset generation completed successfully!")
    else:
        print(f"\n⚠️ Dataset generation completed with issues")
    print(f"📊 Final results: {passed}/{total} samples successful")
    print(f"📁 Dataset saved to: {output_dir}/")
    return success


if __name__ == "__main__":
    main()