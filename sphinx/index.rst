GLAYOUT
=======

**PDK-agnostic layout automation for analog circuit design.** Glayout
generates DRC-clean layouts for any technology that implements the
framework, and every generator in the library is verified end to end:
physical rules with KLayout, netlist equivalence with Netgen, and
electrical behaviour with ngspice.

.. admonition:: Live verification status
   :class: tip

   Current DRC / LVS / ngspice results for every cell, read from the
   runners' own output rather than the last docs deploy.

   👉 `Open the live status dashboard <live/>`_

   The tables on :doc:`results` are generated when these docs are built,
   so they lag the dashboard whenever a run has completed since the last
   deploy.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting_started
   generators
   verification
   results
   ci
   reporting
   contributing
   api

Current status
--------------

.. results-provenance::

.. verification-matrix::

Per-measurement detail is on :doc:`results`.

Supported PDKs
--------------

.. list-table::
   :widths: 30 14 14 14 14 14
   :header-rows: 1

   * - PDK
     - Node
     - Layout
     - DRC
     - LVS
     - ngspice
   * - `SKY130A <https://skywater-pdk.readthedocs.io/en/main/>`_
     - 130 nm
     - ✅
     - ✅
     - ✅
     - ✅
   * - `GF180MCU-D <https://gf180mcu-pdk.readthedocs.io/en/latest/>`_
     - 180 nm
     - ✅
     - ✅
     - ✅
     - —

ngspice regression currently runs on sky130 only. The simulation is a
pre-layout functional check against the reference netlist the DRC runner
emits — see :doc:`verification`.

New here? Start with :doc:`getting_started` for an installable
walk-through, then :doc:`verification` for how the checks work.

Citation
--------

If you use Glayout in your research, please cite:

.. code-block:: bibtex

   @article{hammoud2024human,
     title={Human Language to Analog Layout Using Glayout Layout Automation
            Framework},
     author={Hammoud, A. and Goyal, C. and Pathen, S. and Dai, A. and Li, A.
             and Kielian, G. and Saligane, M.},
     journal={Accepted at MLCAD},
     year={2024}
   }

   @article{hammoud2024reinforcement,
     title={Reinforcement Learning-Enhanced Cloud-Based Open Source Analog
            Circuit Generator for Standard and Cryogenic Temperatures in
            130-nm and 180-nm OpenPDKs},
     author={Hammoud, A. and Li, A. and Tripathi, A. and Tian, W. and
             Khandeparkar, H. and Wans, R. and Kielian, G. and Murmann, B.
             and Sylvester, D. and Saligane, M.},
     journal={Accepted at ICCAD},
     year={2024}
   }

Licensed under MIT. Questions: mehdi_saligane@brown.edu

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
