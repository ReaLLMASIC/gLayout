CI flow
=======

Pull requests and pushes to ``main`` trigger the generate → verify →
simulate pipeline, and a push to ``main`` additionally rebuilds and
deploys this site.

Workflows
---------

The workflows are chained by ``workflow_run`` rather than run as one job.
DRC produces the artifact that LVS and ngspice both consume, so those two
run in parallel off the same input and neither blocks the other.

.. list-table::
   :widths: 26 26 28 20
   :header-rows: 1

   * - Workflow
     - Trigger
     - Produces
     - PDK matrix
   * - ``drc.yml`` (Cell DRC)
     - push, PR
     - ``gds/``, ``netlists/``, ``reports/``, ``summary.json``
     - sky130, gf180
   * - ``lvs.yml`` (Automated: Cell LVS)
     - after Cell DRC
     - ``summary.json``, ``junit.xml``
     - sky130, gf180
   * - ``sim.yml`` (Automated: Cell ngspice)
     - after Cell DRC
     - ``summary.json``, ``junit.xml``, decks and logs
     - sky130
   * - ``docs.yml``
     - after ngspice, push to ``main``
     - this site
     - —

Both LVS and ngspice trigger on DRC finishing, success **or** failure — a
DRC violation does not invalidate the netlist, and running LVS on the
cells that did pass beats a cascade of skips. Cancelled runs are the one
case that is skipped, since their artifacts are partial.

Everything downstream of DRC consumes the same artifact rather than
rebuilding the cells, which is why a full pipeline costs roughly one
build rather than three.

.. list-table:: Artifacts each workflow publishes
   :widths: 24 30 46
   :header-rows: 1

   * - Artifact
     - Written by
     - Contents
   * - ``drc-<pdk>``
     - ``run_cell_drc.py``
     - ``gds/``, ``netlists/`` (consumed by LVS and ngspice),
       ``reports/*.lyrdb``, ``summary.json``, ``junit.xml``
   * - ``lvs-<pdk>``
     - ``run_cell_lvs.py``
     - Netgen or KLayout-deck comparison output, ``summary.json``,
       ``junit.xml``
   * - ``sim-<pdk>``
     - ``run_cell_sim.py``
     - Assembled decks, ngspice logs, ``summary.json``, ``junit.xml``

.. note::

   LVS takes different routes per PDK: sky130 runs magic + netgen through
   ``pdk.lvs_netgen``, while gf180 drives the PDK's own KLayout LVS deck,
   because magic mis-extracts the gf180 substrate — NMOS bulks merge into
   VDD through the n-well. Both write the same ``summary.json`` shape, so
   the tables here do not care which ran.

Permissions the docs workflow needs
-----------------------------------

Reading artifacts from a *different* workflow run requires ``actions:
read``, the same grant ``lvs.yml`` declares for its DRC download. Without
it the download step fails with "Resource not accessible by integration"
and the tables silently fall back to sample data.

A ``workflow_run`` event also reports ``github.ref`` as the default
branch no matter which branch actually ran, so the deploy job gates on
``github.event.workflow_run.head_branch`` instead. Without that guard, a
pull-request branch's results would be published to the live site.

.. note::

   ``sim.yml`` was deleted in commit ``84119ec`` and restored afterwards.
   If simulation is not running on your branch, check that the workflow
   file exists.

Latest run summary
------------------

.. results-provenance::

.. ci-summary::

Artifacts
---------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Artifact
     - Contents
   * - ``drc-<pdk>``
     - ``gds/``, ``netlists/`` (reference netlists consumed by LVS and
       ngspice), ``reports/*.lyrdb``, ``summary.json``
   * - ``lvs-<pdk>``
     - Netgen comparison logs, ``summary.json``, ``junit.xml``
   * - ``sim-<pdk>``
     - ``summary.json``, ``junit.xml``, per-cell assembled decks and logs

Each runner's ``summary.json`` is the source for the tables on this site
— see :doc:`reporting`.

Deployment
----------

The site is built by Sphinx into ``_site`` and published to GitHub Pages.
The live dashboard is copied in from ``docs/live/`` as a sibling path, so
the Sphinx site serves from the root and the dashboard from ``/live/``:

.. code-block:: yaml

   - name: Stage _site/ (live dashboard)
     run: |
       rm -rf _site && mkdir _site
       cp -r docs/. _site/

   - name: Build Sphinx site (root)
     run: |
       sphinx-build -b html --keep-going sphinx _site
       touch _site/.nojekyll

The ``.nojekyll`` marker matters: without it GitHub Pages runs Jekyll,
which strips directories beginning with an underscore and breaks
``_static``.

One-time repository setup
~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
   Not "Deploy from a branch" — the workflow uses the Pages deployment
   API and needs no ``gh-pages`` branch.
2. Confirm the workflow has ``pages: write`` and ``id-token: write``
   permissions.

The site then appears at ``https://reallmasic.github.io/gLayout/``.

Building locally
~~~~~~~~~~~~~~~~

``run_webpage.sh`` at the repository root does what the ``build`` job
does, then serves the result:

.. code-block:: console

   ./run_webpage.sh              # build + serve on :8000
   ./run_webpage.sh 8080         # different port
   ./run_webpage.sh --no-build   # serve an existing _site/
   ./run_webpage.sh --live       # dashboard only, skip Sphinx
   ./run_webpage.sh --strict     # fail if results.json is absent

It prefers ``uv run sphinx-build`` when ``uv`` is installed and falls
back to whatever ``sphinx-build`` is on ``PATH``. In ``--live`` mode it
copies the results file into the served tree and rewrites
``live/config.js`` to fetch it relatively, so the dashboard works without
network access.

Docs dependencies live in the ``docs`` dependency group:

.. code-block:: console

   uv sync --group docs
   # or, with pip:
   pip install sphinx furo myst-parser

Reproducing the pipeline locally
--------------------------------

Every stage is an ordinary shell invocation, so anything CI does can be
run on a laptop with the EDA tools installed. This is usually faster than
pushing a commit to find out whether a fix worked.

``conf.py`` prefers ``sim_results/results.json`` at the repository root
when it exists, so a local run is picked up with no extra flags:

.. code-block:: console

   python tests/sim/run_cell_sim.py --pdk sky130 --all
   sphinx-build -b html sphinx _site

Version skew is the most common reason a stage passes locally and fails
in CI. Check what the workflow pins:

.. code-block:: console

   grep -A2 'ngspice\|magic\|netgen\|klayout' .github/workflows/sim.yml

``ngspice`` in particular changed ``.measure`` behaviour across versions
— a deck that reports a measurement on one version may silently omit it
on another, which the parser records as a failure rather than a pass.

Keeping generated output out of git
-----------------------------------

.. code-block:: text

   lvs_results/
   sim_results/
   _site/
   *.raw
   *.lyrdb

``sim_results/results.json`` is the exception if the live dashboard is in
use: that one file needs to be committed for the page to have something
to fetch. Ignore the directory and force-add the single file with
``git add -f sim_results/results.json``.
