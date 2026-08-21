Generators
==========

The library is layered: primitives wrap PDK geometry, elementary cells
compose primitives into recognisable analog structures, and composite
cells build blocks from those.

Primitives
----------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Generator
     - Description
   * - ``via_stack``
     - Via and enclosure geometry between any two metal layers
   * - ``nmos`` / ``pmos``
     - Multi-finger transistors with optional dummies and taps
   * - ``guard_ring``
     - Well/substrate isolation ring around an arbitrary bounding box
   * - ``tapring``
     - Tap ring for latch-up prevention

Elementary cells
----------------

Each of these has a testbench in the regression matrix — see
:doc:`results`.

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - Generator
     - Description
   * - ``current_mirror_nfet`` / ``current_mirror_pfet``
     - Ratioed mirror with matched-device placement
   * - ``diff_pair``
     - Differential pair with common source and interdigitated fingers
   * - ``diff_pair_ibias``
     - Differential pair with integrated bias current source
   * - ``flipped_voltage_follower``
     - FVF cell for low-impedance buffering
   * - ``low_voltage_cmirror``
     - Cascoded mirror optimised for headroom
   * - ``transmission_gate``
     - Complementary pass gate

Composite cells
---------------

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - Generator
     - Description
   * - ``opamp``
     - Two-stage operational amplifier with compensation
   * - ``diffpair_cmirror_bias``
     - Differential pair with current-mirror bias network

Writing a generator
-------------------

Generators take a ``MappedPDK`` first and return a component:

.. code-block:: python

   from glayout.pdk.mappedpdk import MappedPDK
   from gdsfactory import Component

   def my_cell(pdk: MappedPDK, width: float = 1.0,
               length: float = 0.15) -> Component:
       pdk.activate()
       cell = Component()
       # place subcells, add ports, route
       return cell

Three conventions make a generator usable by the rest of the framework:

Query the PDK, never hard-code
   Use ``pdk.get_grule()`` and ``pdk.get_glayer()`` for spacing and
   layers. A literal ``0.15`` in a generator means it is not
   PDK-agnostic.

Expose named ports
   Composite cells route to ports, not coordinates.

Ship a testbench
   A generator with no entry in ``tests/sim/testbenches/`` is not covered
   by regression, so nothing catches a behavioural break.

See :doc:`contributing` for review expectations.
