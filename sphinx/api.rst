API reference
=============

Common entry points
-------------------

.. list-table::
   :widths: 35 65
   :header-rows: 1

   * - Task
     - API
   * - Activate a PDK
     - :class:`glayout.pdk.mappedpdk.MappedPDK`
   * - Query rules and layers
     - :meth:`~glayout.pdk.mappedpdk.MappedPDK.get_grule`,
       :meth:`~glayout.pdk.mappedpdk.MappedPDK.get_glayer`
   * - Generate primitives
     - :mod:`glayout.primitives.fet`, :mod:`glayout.primitives.via_gen`,
       :mod:`glayout.primitives.guardring`
   * - Generate elementary cells
     - :mod:`glayout.cells.elementary`
   * - Generate composite blocks
     - :mod:`glayout.cells.composite`
   * - Natural language front end
     - :mod:`glayout.llm`

Full module reference
---------------------

The module index below is discovered from the installed package at build
time, so it tracks the source tree rather than a hand-maintained list. A
subpackage without an ``__init__.py``, or one that raises on import, is
skipped rather than failing the build.

.. toctree::
   :maxdepth: 2

   api_modules
