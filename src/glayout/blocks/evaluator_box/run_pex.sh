#!/bin/bash

# Usage: ./run_pex.sh layout.gds layout_cell_name
# Requires PDK_ROOT environment variable to be set

GDS_FILE=$1
LAYOUT_CELL=$2

# Use PDK_ROOT to find the magicrc file
MAGICRC="${PDK_ROOT}/sky130A/libs.tech/magic/sky130A.magicrc"

if [ ! -f "$MAGICRC" ]; then
    echo "Error: Cannot find magicrc at $MAGICRC"
    echo "Make sure PDK_ROOT is set correctly (current: $PDK_ROOT)"
    exit 1
fi

magic -rcfile "$MAGICRC" -noconsole -dnull << EOF
gds read $GDS_FILE
flatten $LAYOUT_CELL
load $LAYOUT_CELL
select top cell
extract do local
extract all
ext2sim labels on
ext2sim
extresist tolerance 10
extresist
ext2spice lvs
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o ${LAYOUT_CELL}_pex.spice
exit
EOF