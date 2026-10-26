"""Check retained ngspice data for the analysis that was actually requested."""
import math
from pathlib import Path
import re


def validate_analysis(data_path, log_path, contract, returncode=0):
    """Validate a wrdata table against declared shape, sweep and time coverage.

    contract: kind=op|ac|dc|transient, columns, and optionally expected_rows,
    start/end, points, scale=linear|log, expected_axis, required_windows.
    Axis values use wrdata precision tolerances, not circuit-spec tolerances.
    """
    errors=[]
    rows=[]
    try:
        lines=Path(data_path).read_text().splitlines()
        rows=[[float(x) for x in line.split()] for line in lines[1:] if line.strip()]
    except (OSError, ValueError):
        errors.append("missing_or_unreadable_numeric_data")
    try:
        log=Path(log_path).read_text()
    except OSError:
        log=""
        errors.append("missing_simulator_log")
    fatal=re.findall(r"(?im)^.*(?:^\s*error\s*:|error on line|doanalyses:|simulation(?:s)? aborted).*$",log)
    if fatal:errors.append("fatal_simulator_log")
    if returncode!=0:errors.append("nonzero_or_missing_returncode")
    if not re.search(r"ngspice-[\w.]+ done",log):errors.append("missing_simulator_completion")
    columns=contract["columns"]
    numeric=bool(rows) and all(len(row)==columns and all(math.isfinite(x) for x in row) for row in rows)
    if not numeric:errors.append("nonfinite_empty_or_wrong_columns")
    kind=contract["kind"]
    expected_rows=contract.get("expected_rows",1 if kind=="op" else contract.get("points"))
    if expected_rows is not None and len(rows)!=expected_rows:errors.append("incomplete_row_count")
    if numeric and kind!="op":
        axis=[r[0] for r in rows]
        close=lambda a,b:math.isclose(a,b,rel_tol=2e-7,abs_tol=1e-14)
        if any(b<=a for a,b in zip(axis,axis[1:])):errors.append("nonincreasing_axis")
        for key,index in [("start",0),("end",-1)]:
            if key in contract and not close(axis[index],contract[key]):errors.append("incomplete_"+key)
        expected=contract.get("expected_axis")
        if expected is None and "points" in contract and "start" in contract and "end" in contract:
            n=contract["points"]
            start,end=contract["start"],contract["end"]
            if contract.get("scale")=="log":
                expected=[start*(end/start)**(i/(n-1)) for i in range(n)]
            else:expected=[start+(end-start)*i/(n-1) for i in range(n)]
        if expected is not None and (len(axis)!=len(expected) or any(not close(a,b) for a,b in zip(axis,expected))):
            errors.append("incomplete_or_changed_sweep")
        for start,end in contract.get("required_windows",[]):
            if not any(start<t<end for t in axis):errors.append("missing_measurement_window")
    return {"complete":not errors,"kind":kind,"rows":len(rows),"columns":columns,
            "errors":errors,"fatal_log_lines":fatal,"data_path":str(data_path),"log_path":str(log_path)}
