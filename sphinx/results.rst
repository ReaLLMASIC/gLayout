Results
=======

Combined DRC / LVS / ngspice status for every cell in the regression
matrix, built from the ``summary.json`` each runner writes.

.. results-provenance::

.. tip::

   These tables are generated when the documentation is built. For a run
   that completed after the last deploy, see the
   `live status dashboard <live/>`_.

Verification matrix
-------------------

.. verification-matrix::

A column appears only for a stage that actually ran for that PDK — which
is why gf180 has no ngspice column: simulation is enabled for sky130
only.

**Legend** — ✅ pass · ❌ fail · 💥 error (the runner itself failed, e.g.
a timeout) · ⏭️ skipped · — not run

Cells are discovered, not registered: the sim runner intersects the
netlists in the DRC artifact with the testbenches in
``tests/sim/testbenches/``. A cell missing from this table has neither.

ngspice measurements
--------------------

Every measurement ngspice reported, with the band from ``checks.json``
and the resulting verdict. Values use the same engineering formatting as
the runner's console output, so a number here reads identically to one in
the log.

.. ngspice-detail::
   :pdk: sky130

A dash in the limits column means no band was declared for that
measurement: it is recorded and displayed, but does not gate the build. A
one-sided band shows as ``— … 2n`` or ``24 … —``.

Reproducing a result
--------------------

Each cell's assembled deck is written before ngspice runs, so any row
above can be re-run directly:

.. code-block:: console

   ngspice -b sim_results/sky130/reports/sim/<cell>/<cell>.deck.spice

The deck is self-contained — model library, reference netlist and
testbench in one file — so it needs no arguments and no environment
beyond ngspice itself.

Rebuilding these tables
-----------------------

The build reads ``<stage>_results/<pdk>/summary.json`` relative to
``glayout_results_root``, which defaults to the repository root when a
local run exists and to the committed sample otherwise:

.. code-block:: console

   sphinx-build -b html sphinx _site \
     -D glayout_results_root=/path/to/downloaded/artifacts
