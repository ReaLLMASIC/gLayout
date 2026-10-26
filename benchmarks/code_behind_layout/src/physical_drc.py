"""Completed full-area Magic checks for an actual, unambiguous GDS top."""
from pathlib import Path
import re
import subprocess

from src.report_parsers import magic_drc_report


def check_gds(gds, output, style="drc(full)", timeout=120, top_name=None):
    import gdstk

    gds = Path(gds).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    library = gdstk.read_gds(gds)
    if top_name is None:
        top, = library.top_level()
    else:
        matches = [cell for cell in library.cells if cell.name == top_name]
        if len(matches) != 1:
            raise ValueError("Declared GDS target must exist exactly once: " + top_name)
        top = matches[0]
    # A named target includes every referenced child, even outside its own shapes.
    # Unreferenced cells are not part of the declared circuit.
    pending = [top]
    hierarchy = set()
    while pending:
        cell = pending.pop()
        if cell.name in hierarchy:
            continue
        hierarchy.add(cell.name)
        for reference in cell.references:
            if not isinstance(reference.cell, gdstk.Cell):
                raise ValueError("Declared GDS target has an unresolved child: " + cell.name)
            pending.append(reference.cell)
    if not re.fullmatch(r"[A-Za-z0-9_$]+", top.name):
        raise ValueError("Unsupported GDS top name")
    if style not in ["drc(full)", "drc(fast)"]:
        raise ValueError("Undeclared DRC style")
    bbox = top.bounding_box()
    if bbox is None:
        raise ValueError("Declared GDS target has no geometry: " + top.name)
    scale = library.unit / 1e-6
    box = [bbox[0][0]*scale-5, bbox[0][1]*scale-5,
           bbox[1][0]*scale+5, bbox[1][1]*scale+5]
    report = output / "direct_drc.rpt"
    tcl = "\n".join([
        "gds read {"+str(gds)+"}", "load {"+top.name+"}", "select top cell",
        "box values "+" ".join(f"{x:.6f}um" for x in box),
        "puts stdout [list ACTUAL_TOP [cellname list self] BOX [box values]]",
        "puts stdout [list ACTUAL_TOP_MATCH [string equal [lindex [cellname list self] 0] {"+top.name+"}]]",
        "drc style {"+style+"}", "puts stdout [list DRC_STYLE [drc list style]]",
        "drc on", "drc check", "drc catchup", "puts stdout DRC_COMPLETE",
        "set f [open {"+str(report)+"} w]",
        'puts $f [format {%s count: %d} {'+top.name+'} [drc listall count total]]',
        'puts $f "----------------------------------------"', "set scale [cif scale out]",
        "foreach {rule boxes} [drc listall why] {", "puts $f $rule",
        "foreach bounds $boxes {", "set converted [list]",
        "foreach x $bounds {lappend converted [format %.3fum [expr {$scale*$x}]]}",
        "puts $f [join $converted]", "}", "}", "close $f", "quit -noprompt", ""])
    (output / "direct_drc.tcl").write_text(tcl)
    logpath = output / "magic.log"
    with logpath.open("w") as log:
        run = subprocess.run(["magic", "-rcfile",
            "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc", "-noconsole", "-dnull"],
            input=tcl, text=True, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    log = logpath.read_text()
    completed = (run.returncode == 0 and "\nDRC_COMPLETE\n" in log
        and "\nACTUAL_TOP_MATCH 1\n" in log and "DRC_STYLE "+style in log)
    parsed = magic_drc_report(report.read_text()) if report.exists() else magic_drc_report("")
    return {"scope": "actual_top_full_bbox_completed_DRC", "input_gds": str(gds),
        "actual_top": top.name, "target_selection": "declared_name" if top_name is not None else "sole_top",
        "checked_hierarchy": sorted(hierarchy), "check_box_um": box, "style": style,
        "returncode": run.returncode, "completed": completed, "parsed": parsed,
        "is_clean": completed and parsed["is_clean"]}
