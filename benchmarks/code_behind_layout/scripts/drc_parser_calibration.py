"""Real failing Magic report for measurement calibration, not a circuit experiment."""
import json
from pathlib import Path
import sys
import gdstk
from glayout import sky130

sys.path.insert(0,"/work")
from src.report_parsers import magic_drc_report

out=Path.cwd()
lib=gdstk.Library();cell=lib.new_cell("drc_calibration")
minimum=sky130.get_grule("met2")["min_width"]
cell.add(gdstk.rectangle((0,0),(minimum/3,2),layer=68,datatype=20))
lib.write_gds(out/"drc_calibration.gds")
sky130.drc_magic(out/"drc_calibration.gds","drc_calibration",pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",output_file=out/"drc")
report=next((out/"drc").rglob("*.rpt"))
parsed=magic_drc_report(report.read_text())
record={"scope":"measurement_calibration_not_benchmark","minimum_width_um":minimum,
        "drawn_width_um":minimum/3,"report":str(report),"parsed":parsed,
        "pass":not parsed["is_clean"] and parsed["error_count"] is not None and parsed["error_count"]>0}
(out/"validation.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2))
raise SystemExit(0 if record["pass"] else 2)
