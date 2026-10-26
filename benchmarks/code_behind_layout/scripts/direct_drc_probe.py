"""Check the actual sole GDS top and full bounding box, waiting for full DRC."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, "/work")
from src.physical_drc import check_gds

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--gds-name", default="ota7.gds")
p.add_argument("--style", choices=["drc(full)", "drc(fast)"], default="drc(full)")
a = p.parse_args()
record = check_gds(Path(os.environ["PROBE_INPUT"])/a.gds_name, Path.cwd(), a.style)
Path("validation.json").write_text(json.dumps(record, indent=2)+"\n")
print(json.dumps(record, indent=2))
