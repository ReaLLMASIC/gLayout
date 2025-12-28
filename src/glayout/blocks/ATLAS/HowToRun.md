# How to Run the Dataset Generation

## ⚡ Current Status (Dec 27, 2024 22:45)

**Phase 2 Implementation: COMPLETE** ✅
- ✅ Generic cell support implemented
- ✅ All 6 cell types configured
- ✅ Command-line interface ready
- ⚠️ **Testing in progress** - Some issues being resolved

**Known Issues** (being fixed):
1. DRC report path conflicts → Use `fix_drc_directories.sh`
2. PDK activation timing → Environment setup refined
3. LVS Component type mismatch → Partial functionality
4. PEX script missing → Optional feature, can skip

**Recommended Testing Approach**:
```bash
# Start with single-sample test
python test_single_sample.py txgate

# If successful, try small batch
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/txgate_params.json \
    --cell_type txgate \
    --n_cores 2 \
    --output_dir small_test \
    -y
```

---

## 📜 Change History

### ErinXU2004: Dec 27, 2024 - **Generic Cell Support Implementation**

**Major Update: Made dataset generator support ALL cell types!** 🎉

**What Changed:**
- ✅ Created `cell_registry.py` - Configuration system for all 6 cell types
- ✅ Refactored `run_dataset_multiprocess.py` to be generic
- ✅ Added `--cell_type` command-line argument
- ✅ Implemented dynamic module loading
- ✅ Support for: `txgate`, `fvf`, `lvcm`, `current_mirror`, `diff_pair`, `opamp`

**Implementation Details:**
- `robust_transmission_gate()` → `robust_cell_generator(cell_type, **params)`
- `load_tg_parameters_from_json()` → `load_cell_parameters_from_json(json_file, cell_type)`
- Dynamic output naming: `{prefix}_sample_{num}`
- Configuration-driven architecture for easy extensibility

**Motivation:**
Original code only supported transmission gate (hardcoded). Now one script handles all cell types through configuration, making it maintainable and extensible.

---

### AL: Sep 29, 2025 - **Initial Port from OpenFASOC**

Migrated from Arnav's fork of OpenFASOC with modifications:
- A lot of effort needed to make it compatible with latest new gLayout repo
- Import path fixes: `glayout.flow.*` → `glayout.*`
- Initial transmission gate support working

---

## 🚀 Quick Start

### Step 1: Generate Parameters (if not already done)

```bash
# Generate parameter files for all cell types
python elhs.py
# This creates: gen_params_8h_runtime_aware/<cell_type>_params.json
```

### Step 2: Run Dataset Generation

**Transmission Gate Example:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/txgate_params.json \
    --cell_type txgate \
    --n_cores 8 \
    --output_dir txgate_dataset
```

**Flipped Voltage Follower Example:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/fvf_params.json \
    --cell_type fvf \
    --n_cores 8 \
    --output_dir fvf_dataset
```

**Low Voltage Current Mirror Example:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/lvcm_params.json \
    --cell_type lvcm \
    --n_cores 8 \
    --output_dir lvcm_dataset
```

---

## 📋 All Supported Cell Types

| Cell Type | Identifier | JSON File | Output Prefix | Samples |
|-----------|-----------|-----------|---------------|---------|
| Transmission Gate | `txgate` | `txgate_params.json` | `tg_` | 3,464 |
| Flipped Voltage Follower | `fvf` | `fvf_params.json` | `fvf_` | 10,886 |
| Low Voltage Current Mirror | `lvcm` | `lvcm_params.json` | `lvcm_` | 3,503 |
| Current Mirror | `current_mirror` | `current_mirror_params.json` | `cm_` | 7,755 |
| Differential Pair | `diff_pair` | `diff_pair_params.json` | `dp_` | 9,356 |
| Operational Amplifier | `opamp` | `opamp_params.json` | `opamp_` | 5,850 |

---

## 🔧 Command-Line Arguments

```bash
python run_dataset_multiprocess.py <json_file> --cell_type <type> [OPTIONS]
```

### Required Arguments:
- `json_file` - Path to parameter JSON file
- `--cell_type` - Cell type identifier (txgate, fvf, lvcm, current_mirror, diff_pair, opamp)

### Optional Arguments:
- `--n_cores N` - Number of parallel CPU cores (default: 1)
- `--output_dir DIR` - Output directory (default: "result")
- `--max_samples N` - Maximum number of samples to process from JSON (default: all)
- `-y, --yes` - Auto-confirm prompts (for automation)

### Examples:

**Run all samples:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/txgate_params.json \
    --cell_type txgate \
    --n_cores 8
```

**Test with 10 samples:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/txgate_params.json \
    --cell_type txgate \
    --n_cores 2 \
    --max_samples 10 \
    --output_dir test_10_samples
```

**Run 100 FVF samples:**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/fvf_params.json \
    --cell_type fvf \
    --n_cores 8 \
    --max_samples 100 \
    --output_dir fvf_100_samples
```

---

## 📂 Output Structure

```
output_dir/
├── sample_0001/
│   ├── <prefix>_sample_0001.gds           # Layout file
│   ├── <prefix>_sample_0001.drc.rpt       # DRC report
│   ├── <prefix>_sample_0001.lvs.rpt       # LVS report
│   ├── <prefix>_sample_0001_pex.spice     # Parasitic extraction
│   ├── <prefix>_sample_0001.res.ext       # Resistance extraction
│   ├── <prefix>_sample_0001.ext           # Full extraction
│   └── ...
├── sample_0002/
├── ...
├── <prefix>_parameters.json               # Copy of input parameters
├── <prefix>_results.json                  # Detailed results (JSON)
└── <prefix>_summary.csv                   # Summary table (CSV)
```

---

## 📊 Example: Large-Scale Generation

**Generate full transmission gate dataset (3,464 samples):**
```bash
python run_dataset_multiprocess.py \
    gen_params_8h_runtime_aware/txgate_params.json \
    --cell_type txgate \
    --n_cores 32 \
    --output_dir txgate_full_dataset \
    -y
```

**Estimated Runtime:**
- With 32 cores: ~8 hours
- Average: ~8 seconds per sample
- Total: 3,464 samples

---

## 🐛 Troubleshooting

### Error: "Unknown cell type"
```bash
# Check supported types:
python cell_registry.py
```

### Error: "Parameter file not found"
```bash
# Generate parameters first:
python elhs.py
```

### Error: "No module named 'glayout.flow'"
```bash
# This is from old OpenFASOC code - all fixed in current version
# Make sure you're on the latest sweep-experiement branch
```

### Error: "[Errno 21] Is a directory: 'xxx.drc.rpt'"

**Root Cause**: DRC report file is being created as a directory instead of a file.

**Quick Fix** (Dec 27, 2024) - Use the cleanup script:
```bash
cd src/glayout/blocks/ATLAS

# Option 1: Use the provided cleanup script (recommended)
./fix_drc_directories.sh txgate_dataset

# Option 2: Manual cleanup
find . -type d -name "*.drc.rpt" -o -name "*.lvs.rpt" | xargs rm -rf
```

**Workaround**: Test with a single sample first
```bash
# Option 1: Use the provided test script (easiest)
python test_single_sample.py txgate

# Option 2: Create a minimal test JSON manually
python -c "
import json
params = [{
    'width': (1.0, 2.0),
    'length': (0.15, 0.15),
    'fingers': (4, 4),
    'multipliers': (1, 1)
}]
with open('test_single.json', 'w') as f:
    json.dump(params, f, indent=2)
"

# Run with single core for easier debugging
python run_dataset_multiprocess.py \
    test_single.json \
    --cell_type txgate \
    --n_cores 1 \
    --output_dir test_single_output \
    -y
```

**Permanent Fix** (TODO): Update `robust_verification.py` to ensure DRC reports are created as files, not directories.

### Error: "No active PDK. Activating generic PDK"

**Impact**: This causes Magic to use the "minimum" tech file instead of Sky130, leading to dummy DRC/LVS reports.

**Fix**: Ensure PDK environment is set before running:
```bash
# Check if PDK_ROOT is set
echo $PDK_ROOT

# If not set, export it (adjust path to your installation)
export PDK_ROOT=/path/to/your/pdk_root
export PDK=sky130A

# Or let the script auto-detect (it will search common locations)
python run_dataset_multiprocess.py ...
```

**Note**: The script includes `robust_verification.py` which should auto-detect PDK_ROOT, but if you see this warning repeatedly, manually set the environment variable.

### Error: "'str' object has no attribute 'generate_netlist'"

**Root Cause**: LVS is receiving a string path instead of a Component object.

**Status**: Known issue in `robust_verification.py` - needs update to handle both Component objects and paths.

**Workaround**: DRC and geometric analysis will still work; only LVS will fail.

### Error: "run_pex.sh: No such file or directory"

**Root Cause**: PEX extraction script is missing or not in PATH.

**Impact**: PEX (parasitic extraction) will be skipped, but DRC/LVS/geometric analysis will continue.

**Fix**: 
1. Check if `run_pex.sh` exists in your PDK installation
2. Add it to PATH or update `physical_features.py` to use the correct path

**Workaround**: PEX is optional for basic dataset generation; you can proceed without it.

### DRC/LVS general failures
- Check PDK installation: `echo $PDK_ROOT`
- Verify Magic/Netgen are installed: `which magic`, `which netgen`
- Check `robust_verification.py` for PDK environment setup
- Review individual sample directories for detailed error reports
- Try reducing parallel workers: `--n_cores 1` for debugging

---

## 🔍 Checking Results

**Quick summary:**
```bash
# View CSV summary
cat output_dir/<prefix>_summary.csv

# Count successful samples
grep -c '"success": true' output_dir/<prefix>_results.json

# Check DRC/LVS pass rates
grep -c '"drc_pass": true' output_dir/<prefix>_results.json
grep -c '"lvs_pass": true' output_dir/<prefix>_results.json
```

**Detailed analysis:**
```python
import pandas as pd
import json

# Load summary
df = pd.read_csv('output_dir/tg_summary.csv')
print(f"Success rate: {df['success'].mean()*100:.1f}%")
print(f"DRC pass rate: {df['drc_pass'].mean()*100:.1f}%")
print(f"LVS pass rate: {df['lvs_pass'].mean()*100:.1f}%")

# Load detailed results
with open('output_dir/tg_results.json', 'r') as f:
    results = json.load(f)

# Analyze parasitic extraction
pex_complete = [r for r in results if r.get('pex_status') == 'PEX Complete']
print(f"PEX success: {len(pex_complete)}/{len(results)}")
```

---

## 📚 Related Files

- `cell_registry.py` - Cell type configurations
- `elhs.py` - Parameter generation (LHS + OA)
- `evaluator_wrapper.py` - DRC/LVS/PEX evaluation
- `robust_verification.py` - PDK environment setup
- `transmission_gate.py`, `fvf.py`, `lvcm.py`, etc. - Cell generators

---

## 🎯 Next Steps

1. **Test all cell types** with small samples
2. **Run full dataset generation** for your target cell
3. **Analyze results** for design space exploration
4. **Use datasets** for ML training or optimization

---

## 💡 Tips

- Start with small `--n_cores` (2-4) to test before scaling up
- Monitor disk space - each sample generates ~10-20 files
- Use `-y` flag for unattended batch runs
- Check logs for errors during generation
- Keep `_work/` directory for debugging failed samples

---

## 📞 Need Help?

- Check `IMPLEMENTATION_PLAN.md` for detailed implementation notes
- See `cell_registry.py --help` for cell type info
- Review error messages in terminal output
- Check individual sample directories for detailed reports