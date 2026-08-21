Verification
============

Every generator passes through three independent checks. They answer
different questions, and passing one says nothing about the others.

.. list-table::
   :widths: 15 40 45
   :header-rows: 1

   * - Stage
     - Question it answers
     - Tool
   * - DRC
     - Is the layout manufacturable under the PDK's rules?
     - KLayout, using the PDK's own deck
   * - LVS
     - Does the layout implement the intended schematic?
     - Magic (extract) + Netgen (compare)
   * - ngspice
     - Does the extracted netlist behave correctly?
     - ngspice, on the DRC runner's reference netlist

The stages are chained through artifacts rather than run by a single
driver. DRC runs first and emits the GDS plus a reference netlist per
cell; LVS and ngspice both consume that artifact, in parallel, so a flaky
LVS run does not block simulation.

.. code-block:: console

   # DRC first — produces gds/, netlists/ and reports/
   python tests/drc/run_cell_drc.py --pdk sky130 --out-dir drc_results/sky130

   # Then ngspice, against the netlists DRC emitted
   python tests/sim/run_cell_sim.py \
       --pdk sky130 \
       --inputs-dir drc_results/sky130 \
       --out-dir sim_results/sky130

   # A subset of cells
   python tests/sim/run_cell_sim.py --pdk sky130 \
       --inputs-dir drc_results/sky130 --out-dir sim_results/sky130 \
       --cells diff_pair,opamp

Each runner writes ``summary.json`` and ``junit.xml`` into its output
directory. Those summary files are what the tables on :doc:`results` are
built from.

Where the flow lives
--------------------

.. code-block:: text

   tests/sim/
   ├── run_cell_sim.py              # assembles decks, runs ngspice, reports
   └── testbenches/
       ├── checks.json              # measurement bands, keyed by cell
       ├── current_mirror_nfet.spice
       ├── current_mirror_pfet.spice
       ├── diff_pair.spice
       ├── diff_pair_ibias.spice
       ├── flipped_voltage_follower.spice
       ├── low_voltage_cmirror.spice
       └── transmission_gate.spice

.. note::

   This directory was deleted in commit ``d57ca85`` and restored
   afterwards. If ``tests/sim/`` is missing from your checkout, confirm
   you are on a ``main`` that includes the restore commit.

Design rule checking
--------------------

DRC runs KLayout against the PDK's own rule deck, so the rules are
exactly those the foundry ships — Glayout does not maintain a parallel
copy. A cell passes only with zero violations; there is no waiver
mechanism, because a generator that cannot produce a clean layout is a
bug in the generator.

Violations are written as a KLayout marker database. Open it alongside
the GDS to see the flagged geometry in place:

.. code-block:: console

   klayout <cell>.gds -m lvs_results/sky130/<cell>/drc.lyrdb

Each marker carries the rule name from the deck, which is the string to
look up in the PDK's rule documentation.

.. list-table:: Common causes
   :widths: 35 65
   :header-rows: 1

   * - Symptom
     - Usual cause
   * - Minimum spacing on a metal layer
     - Two subcells abutted without honouring the routing pitch
   * - Enclosure / surround failure
     - A via placed without the required overlap on one of its layers
   * - Density or antenna rules
     - Large routes without fill or a tie-down; usually top level only
   * - Well / tap spacing
     - Missing guard ring or tap on an isolated device

Layout versus schematic
-----------------------

LVS is two steps: Magic extracts a netlist from the layout, then Netgen
compares it against the reference schematic netlist.

.. code-block:: text

   lvs_results/<pdk>/<cell>/lvs.log            # Netgen comparison output
   lvs_results/<pdk>/<cell>/extracted.spice

Netgen reports mismatches in three flavours, and the distinction matters
when debugging:

Device mismatch
   The layout has a different count or type of device than the schematic.
   Usually a generator emitting the wrong number of fingers, or a dummy
   device that should not be electrically connected.

Net mismatch
   Device counts agree but connectivity differs. Typically a route that
   did not land on the intended port, or two nets shorted through a
   shared tap.

Property mismatch
   Connectivity is correct but W/L or multiplier values differ. Often a
   unit error — Glayout works in microns, and SPICE decks frequently use
   metres.

.. warning::

   ``opamp`` currently fails LVS on gf180 with a net mismatch. The sky130
   variant passes. It is recorded in the results file as a known issue so
   it renders distinctly from a new regression.

For LVS to have anything to compare against, a generator needs a
reference netlist with matching port names. Composite cells should expose
ports in the same order as the schematic subcircuit definition:

.. code-block:: text

   .subckt diff_pair vin_p vin_n vout_p vout_n vbias vss
   ...
   .ends

Mismatched port *order* still passes LVS if names match, but produces
confusing testbench wiring later, so keep them aligned.

ngspice regression
------------------

Simulation checks that a cell behaves as intended, which neither DRC nor
LVS can tell you: a layout can be manufacturable and topologically
correct and still miss its timing or bias targets.

.. important::

   This is a **pre-layout / functional** check by default. It simulates
   the reference netlist that the DRC runner emits, not a
   parasitic-extracted one. Post-layout (PEX) simulation is a documented
   extension point in ``_assemble_deck`` — it is off the default path
   because per-cell magic extraction is slow in CI and, on gf180,
   mis-extracts the substrate.

A cell is simulated when it has **both** a reference netlist from the DRC
artifact and a testbench:

.. code-block:: text

   drc_results/<pdk>/netlists/<cell>.spice   <- from run_cell_drc.py
   tests/sim/testbenches/<cell>.spice        <- hand-written

Cells with only one of the two are skipped silently, so adding a
testbench is all it takes to bring a cell into the matrix.

How a cell gets simulated:

1. ``_assemble_deck`` writes a self-contained deck: the PDK model
   library at the right corner, then the reference netlist, then the
   testbench body.
2. ngspice runs it in batch mode (``-b``, no ``.control`` block — that
   combination causes a well-known double execution).
3. ``_parse_sim_log`` extracts ``.measure`` results and compares each
   against its band.

Writing a testbench
~~~~~~~~~~~~~~~~~~~

A testbench is **stimulus, analysis and ``.measure`` cards only**. It must
not declare the model ``.lib`` or ``.include`` the DUT netlist — the
runner injects both, which is what lets one testbench work across corners
and PDKs. Instantiate the DUT with a subckt call whose name matches the
``.subckt <cell>`` in the reference netlist:

.. code-block:: text

   Vdd vdd 0 1.8
   Vin in 0 PULSE(0 1.8 1n 10p 10p 5n 10n)
   X1 in out vdd 0 <cell>
   .tran 10p 50n
   .measure tran tphl TRIG v(in) VAL=0.9 RISE=1 TARG v(out) VAL=0.9 FALL=1

A trailing ``.end`` is stripped by the runner, so leaving one in is
harmless.

Declaring pass criteria
~~~~~~~~~~~~~~~~~~~~~~~

Bands live in one consolidated file, ``tests/sim/testbenches/checks.json``,
keyed by cell then by measurement name. Either bound may be omitted for a
one-sided limit:

.. code-block:: json

   {
     "diff_pair": {
       "gain_db": { "min": 24.0, "max": 28.0 },
       "tphl":    { "max": 2e-9 }
     },
     "current_mirror_nfet": {
       "iout":     { "max": 4.2e-6 },
       "vout_min": { "max": 0.40 }
     }
   }

A per-cell sidecar at ``tests/sim/testbenches/<cell>.checks.json`` is used
as a fallback for any cell not listed in the consolidated file. Override
the consolidated path with ``--checks-file``.

Without any band, a cell still runs as a smoke test: it passes when
ngspice finishes cleanly with no failed ``.measure``. Each measurement
gets one of four verdicts:

``PASS``
   Measured and inside its band.

``FAIL``
   Measured and outside its band. Fails the cell.

``MISSING``
   A band was declared but no matching measurement appeared in the log —
   usually a ``.measure`` name typo, or an analysis that did not converge
   far enough to emit it. Fails the cell.

``no band``
   Measured, with no band declared. Recorded and displayed, but does not
   gate the build.

Failure modes the parser catches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Convergence problems are treated as failures rather than missing data,
because a silently truncated run otherwise reads as a pass:

* ``fatal`` errors reported by ngspice
* singular matrix
* timestep too small
* aborted or interrupted simulation
* iteration limit reached

Environment problems are surfaced separately, so a broken container reads
as its actual cause rather than a generic "sim inconclusive":

.. list-table::
   :widths: 45 55
   :header-rows: 1

   * - Reported conclusion
     - Usual cause
   * - ngspice binary not on PATH
     - ngspice missing from the runner image
   * - missing include / model lib
     - ``PDK_ROOT`` unset, or the model library moved
   * - missing model / unresolved subckt
     - Wrong corner section, or the testbench's subckt call does not
       match the ``.subckt`` name in the reference netlist

The measurement scan is scoped to ngspice's "Measurements for … Analysis"
blocks. Without that scoping, the end-of-run resource report (``Stack = 0
bytes.``) parses as a measurement.

Reading the output
~~~~~~~~~~~~~~~~~~

.. code-block:: text

   sim_results/<pdk>/
   ├── summary.json                          # every cell, every measurement
   ├── junit.xml                             # published as a CI check
   └── reports/sim/<cell>/
       ├── <cell>.deck.spice                 # the assembled deck
       └── <cell>.log                        # raw ngspice output

The deck is written before ngspice runs, so a failing cell leaves behind
exactly the file you need to reproduce it:

.. code-block:: console

   ngspice -b sim_results/sky130/reports/sim/opamp/opamp.deck.spice

In CI the same measurement tables are also written to the run's Summary
page via ``$GITHUB_STEP_SUMMARY``, so a failure is readable without
downloading artifacts.

Adding a cell to the matrix
~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``tests/sim/testbenches/<cell>.spice``.
2. Optionally add bands for it to ``checks.json``.

The runner discovers cells by intersecting the netlists in the DRC
artifact with the testbenches on disk, so no registry needs updating. A
cell with a testbench but no netlist is skipped, and vice versa.
