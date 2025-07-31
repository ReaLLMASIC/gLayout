# Switched-Cap Low Pass Filter Progress Log

The switched-capacitor low-pass filter is used to remove high-frequency components after chopper demodulation, recovering the clean baseband EEG signal. Instead of relying on physical resistors, which can consume significant area and vary with process, the filter uses capacitor ratios and a clock signal to define its cutoff frequency precisely. This makes it highly area-efficient, tunable, and well-suited for integration in CMOS processes. The switching operation emulates a resistor using charge transfer, allowing for compact, accurate, and fully integrated filtering essential in low-power EEG front-end systems.

## Target Specification

<div align="center">

| **Parameter**           | **Value**      | **Unit**   |
|-------------------------|-------------|--------|
| Cutoff Frequency (f<sub>c</sub>)  | 220        | Hz     |
| Clock Frequency (f<sub>clk</sub>) | 4         | kHz     |

</div>

## Schematic Design

<p align="center">
  <img src="../../images/LPFSchem.jpg" alt="LPFSchem" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Individual Switched-Cap Low Pass Filter Schematic</h4>

## Simulation

<p align="center">
  <img src="../../images/LPFFull.jpg" alt="LPFFull" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Switched-Cap Low Pass Filter Testbench</h4>

<p align="center">
  <img src="../../images/LPFTb.jpg" alt="LPFTb" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Testbench Result</h4>

## Performance of Designed Switched-Cap Low Pass Filter

<div align="center">

| **Parameter**           | **Value**      | **Unit**   |
|-------------------------|-------------|--------|
| Cutoff Frequency (f<sub>c</sub>)  | TBD       | Hz     |
| Clock Frequency (f<sub>clk</sub>) | 4        | kHz     |
| Capacitor ) | 4        | farad    |

</div>

**Last Updated: 1st August**
