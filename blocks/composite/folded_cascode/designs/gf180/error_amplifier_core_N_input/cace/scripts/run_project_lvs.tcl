# NOTE: PDK_ROOT, PDK and CACE_ROOT are set in the local environment by CACE
#
# This is an example script to drive LVS; because this is a simple
# example, there is no specific benefit of using this instead of the
# default handling in CACE.

set PDK_ROOT $::env(PDK_ROOT)
set PDK $::env(PDK)
set CACE_ROOT $::env(CACE_ROOT)

set circuit1 [readnet spice $CACE_ROOT/netlist/layout/folded_cascode_core.spice]
set circuit2 [readnet spice $CACE_ROOT/netlist/schematic/folded_cascode_core.spice]

lvs "$circuit1 folded_cascode_core" "$circuit2 folded_cascode_core" $PDK_ROOT/$PDK/libs.tech/netgen/${PDK}_setup.tcl folded_cascode_core_comp.out -json
