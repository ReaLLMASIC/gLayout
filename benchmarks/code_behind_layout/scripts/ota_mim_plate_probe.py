"""Independent development plate-routing variant; gold and checks stay fixed."""
import json
from pathlib import Path
import runpy
import sys

variant="/work/vendor/glayout-mim-plate-development/src"
sys.path.insert(0,variant)
Path("actual_generator_source.json").write_text(Path("/work/configs/development/mim_plate_variant.json").read_text())
# Executes the same independent gold binding and physical checker as the root
# probe, with only the inspected generator's two physical plate routes changed.
runpy.run_path("/work/scripts/ota_reference_probe.py",run_name="__main__")
