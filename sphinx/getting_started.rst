Getting started
===============

This page walks through installing Glayout, generating a component, and
running the verification flow on it. The examples are small and can be
pasted into a Python REPL in order.

Install
-------

Glayout needs Python ≥ 3.10. With ``pip``:

.. code-block:: console

   pip install glayout

From a checkout, for development:

.. code-block:: console

   git clone https://github.com/ReaLLMASIC/gLayout.git
   cd gLayout
   pip install -e ".[dev]"

Optional extras: ``[ml]`` for the reinforcement-learning tooling,
``[llm]`` for the natural-language front end. Documentation dependencies
are in the ``docs`` dependency group (``uv sync --group docs``).

External tools
~~~~~~~~~~~~~~

The layout generators are pure Python and need nothing else. The
verification flow shells out to EDA tools, so install these only if you
intend to run DRC, LVS, or simulation:

.. list-table::
   :widths: 22 28 50
   :header-rows: 1

   * - Requirement
     - Needed for
     - Notes
   * - ``klayout``
     - DRC
     - invoked with the PDK's own rule deck
   * - ``magic``
     - LVS
     - netlist extraction
   * - ``netgen``
     - LVS
     - netlist comparison
   * - ``ngspice``
     - simulation
     - version 39 or newer recommended
   * - ``PDK_ROOT``
     - all three
     - points at an installed sky130A / gf180mcuD PDK

Generate a component
--------------------

Every generator takes a PDK object as its first argument. The same call
produces a layout in whichever technology is passed in — that is the
point of the framework:

.. code-block:: python

   from glayout import sky130, gf180, nmos, pmos, via_stack

   # A via stack: met2 is the bottom layer, met3 the top
   via = via_stack(sky130, "met2", "met3", centered=True)

   # A two-finger NMOS transistor
   transistor = nmos(sky130, width=1.0, length=0.15, fingers=2)

   # The same generator, different technology
   transistor_gf = nmos(gf180, width=2.0, length=0.28, fingers=2)

   via.write_gds("via.gds")
   transistor.write_gds("transistor.gds")

Generators return :class:`gdsfactory.Component` objects, so the usual
display paths work:

.. code-block:: python

   transistor.show()   # opens in KLayout
   transistor.plot()   # inline matplotlib preview

Inspect ports
-------------

.. code-block:: python

   print(transistor.ports.keys())

Ports are what let composite cells route to primitives without
hard-coded coordinates. A generator with undocumented ports is difficult
to build on — see :doc:`generators` for the conventions.

Build a composite cell
----------------------

.. code-block:: python

   from glayout import sky130, diff_pair

   dp = diff_pair(sky130, width=3.0, length=0.15, fingers=4)
   dp.write_gds("diff_pair.gds")

Verify what you built
---------------------

DRC runs first and emits the reference netlists that LVS and ngspice both
consume:

.. code-block:: console

   python tests/drc/run_cell_drc.py --pdk sky130 --out-dir drc_results/sky130

   python tests/sim/run_cell_sim.py \\
       --pdk sky130 \\
       --inputs-dir drc_results/sky130 \\
       --out-dir sim_results/sky130 \\
       --cells diff_pair

Each runner writes a ``summary.json``. Rebuild the docs afterwards and the
tables on :doc:`results` pick up your run automatically — ``conf.py``
prefers local runner output over the committed sample. See
:doc:`verification` for what each stage checks.

Natural language interface
--------------------------

With the ``[llm]`` extra installed:

.. code-block:: python

   from glayout.llm import generate

   component = generate(
       "a 4-finger nmos current mirror in sky130 with a 1:4 ratio"
   )

The front end maps descriptions onto the generators in
:doc:`generators`. It does not write new layout code, so its output is
subject to the same DRC guarantees as a hand-written call.
