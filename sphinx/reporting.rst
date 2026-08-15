Reporting
=========

No result table in this documentation is written by hand, and none of them
require a change to the runners. Everything reads the ``summary.json`` that
each runner already writes next to its ``junit.xml``.

.. code-block:: text

   drc_results/<pdk>/summary.json     <- tests/drc/run_cell_drc.py
   lvs_results/<pdk>/summary.json     <- tests/lvs/run_cell_lvs.py
   sim_results/<pdk>/summary.json     <- tests/sim/run_cell_sim.py

Three consumers, one set of files:

* the Sphinx directives on :doc:`results` and :doc:`ci`, at build time;
* the `live dashboard <live/>`_, fetched in the browser on page load;
* ``tools/render_results.py``, which fills the marker blocks in the
  repository ``README.md``.

If a table disagrees with a run, the fault is in the summary file, not in
three separate places.

Schema
------

.. code-block:: json

   {
     "pdk": "sky130",
     "total": 9, "pass": 8, "fail": 1, "error": 0, "skip": 0,
     "results": [
       {
         "cell": "diff_pair",
         "status": "pass",
         "message": "sim passed",
         "summary": {
           "conclusion": "sim passed",
           "measures": {"tphl": 1.19e-9},
           "rows": [
             {"name": "tphl", "value": 1.19e-9,
              "min": null, "max": 2e-9, "verdict": "PASS"}
           ]
         }
       }
     ]
   }

``status``
   One of ``pass``, ``fail``, ``error`` or ``skip``. ``error`` means the
   runner itself failed — a timeout or an exception — as distinct from a
   cell that ran and did not meet its bands.

``summary.rows``
   Present for ngspice only. One entry per measurement, carrying the
   value, the band it was checked against, and a verdict of ``PASS``,
   ``FAIL``, ``MISSING`` or ``n/a``. Built unconditionally, so the table
   renders whether the cell passed or failed and the displayed rows can
   never disagree with the verdict.

A run with nothing to do writes ``{"pdk": ..., "total": 0, "note": ...}``
with no ``results`` key — for instance when netlists exist but no
testbenches have been authored yet. That renders as "nothing to run"
rather than an error, which is what keeps adding the workflow from
reddening the build before the testbenches land.

Directives
----------

Provided by ``sphinx/_ext/glayout_results.py``:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Directive
     - Renders
   * - ``verification-matrix``
     - One row per cell, one column per stage that ran, per PDK
   * - ``ngspice-detail``
     - One row per measurement. Options: ``:pdk:``, ``:failures-only:``
   * - ``ci-summary``
     - Per-stage pass counts
   * - ``results-provenance``
     - Which summaries were loaded and when they were written

Usage is a bare directive — no data is passed in the document:

.. code-block:: rst

   .. verification-matrix::

   .. ngspice-detail::
      :pdk: sky130
      :failures-only:

Configuration
~~~~~~~~~~~~~

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - ``conf.py`` value
     - Meaning
   * - ``glayout_results_root``
     - Directory containing ``<stage>_results/<pdk>/summary.json``.
       Defaults to the repository root when a local run exists, else the
       committed sample. Override with ``GLAYOUT_RESULTS_ROOT``.
   * - ``glayout_pdks``
     - Which PDKs to look for and show as columns.
   * - ``glayout_results_strict``
     - When true, missing or malformed summaries fail the build instead of
       rendering a placeholder. Set ``GLAYOUT_RESULTS_STRICT=1`` in CI.

The fallback matters: a contributor with no PDK installed can still build
the docs and gets the sample data with a warning, rather than a broken
build.

Number formatting
~~~~~~~~~~~~~~~~~

The directives reimplement ``run_cell_sim.py``'s ``_fmt_eng`` exactly, so
a value shown here reads identically to the same value in the console
log, the JUnit report and the Actions step summary. If you change the
formatter in the runner, change it in
``sphinx/_ext/glayout_results.py`` and ``tools/render_results.py`` too —
they are duplicated deliberately, so the docs build has no import
dependency on the test tree.

Updating the README
-------------------

The README is rendered by GitHub and cannot run Sphinx directives, so it
uses comment markers instead:

.. code-block:: text

   <!-- BEGIN: VERIFICATION_MATRIX (auto-generated - do not edit by hand) -->
   ...
   <!-- END: VERIFICATION_MATRIX -->

``tools/render_results.py`` rewrites only the text between a matching
pair, leaving surrounding prose untouched:

.. code-block:: console

   python tools/render_results.py --results-root . --target README.md

Run it with ``--check`` to verify the README is current without modifying
it; it exits non-zero when stale, which makes a usable PR gate.

Where CI gets the data
----------------------

The docs workflow triggers on the ngspice workflow completing, downloads
the ``sim-<pdk>`` artifacts from the triggering run and the ``drc-<pdk>``
and ``lvs-<pdk>`` artifacts from the branch, then reshapes them into the
layout above. Each download is best-effort: a stage whose artifact is
missing simply loses its column rather than failing the build.

The summaries are also copied into the deployed site, so the live
dashboard fetches them from the same origin instead of reaching for
``raw.githubusercontent.com``.
