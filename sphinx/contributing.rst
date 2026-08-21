Contributing
============

The full guide lives at `docs/contributor_guide.md
<https://github.com/ReaLLMASIC/gLayout/blob/main/docs/contributor_guide.md>`_.
This page covers what the verification flow expects of a change.

Before opening a pull request
-----------------------------

.. admonition:: Checklist
   :class: tip

   * New generators query the PDK for rules rather than hard-coding
     dimensions
   * Ports are named and documented
   * A testbench exists in ``tests/sim/testbenches/`` for any new cell,
     containing stimulus and ``.measure`` cards only — no ``.lib``, no
     ``.include`` of the DUT
   * Bands added to ``tests/sim/testbenches/checks.json`` where the cell
     has a real spec (without them it runs as a smoke test)
   * DRC and LVS pass locally on sky130
   * Docs build clean: ``./run_webpage.sh``
   * Generated output (``lvs_results/``, ``sim_results/``, ``*.raw``) is
     not committed

Working with a fork
-------------------

Most contributors do not have push access to ``ReaLLMASIC/gLayout``, so
the flow is fork → branch → pull request:

.. code-block:: console

   git clone https://github.com/<you>/gLayout.git
   cd gLayout
   git remote add upstream https://github.com/ReaLLMASIC/gLayout.git

Keep the fork current before branching, or the pull request will carry
unrelated commits:

.. code-block:: console

   git fetch upstream
   git checkout main
   git merge --ff-only upstream/main
   git push origin main
   git checkout -b my-feature

.. tip::

   Base new branches on ``upstream/main``, not on your fork's ``main``. A
   stale fork is the usual cause of a pull request showing dozens of
   unexpected commits.

When a merge seems to have vanished
-----------------------------------

A file that disappeared after a successful merge was usually moved or
removed by a later commit rather than lost. Trace it before redoing the
work:

.. code-block:: console

   git log --full-history --oneline upstream/main -- '**/<filename>'

``--full-history`` matters — without it git prunes merge history and can
hide the commit that removed the file. ``git branch -r --contains <sha>``
confirms whether a commit is reachable from the branch you expect.

To restore a tree from before a deletion:

.. code-block:: console

   git checkout -b restore-x upstream/main
   git checkout <commit-before-deletion> -- path/to/dir/
   git commit -m "Restore path/to/dir deleted in <sha>"
   git push -u origin restore-x

.. note::

   Pushing changes under ``.github/workflows/`` over HTTPS requires a
   token with the ``workflow`` scope in addition to ``repo``. A ``403``
   naming a different account than the repository owner means a stale
   credential is cached, not a permissions problem on the repository.

Documentation changes
---------------------

The docs live in ``sphinx/``. Result tables are generated from
``results.json`` and must not be edited by hand — see :doc:`reporting`.

.. code-block:: console

   uv sync --group docs        # or: pip install sphinx furo myst-parser
   ./run_webpage.sh            # build and serve on :8000
   ./run_webpage.sh --live     # dashboard only, much faster
