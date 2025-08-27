# Switched-Cap Low Pass Filter Progress Log

The switched-capacitor low-pass filter is used to remove high-frequency components after chopper demodulation, recovering the clean baseband EEG signal. Instead of relying on physical resistors, which can consume significant area and vary with process, the filter uses capacitor ratios and a clock signal to define its cutoff frequency precisely. This makes it highly area-efficient, tunable, and well-suited for integration in CMOS processes. The switching operation emulates a resistor using charge transfer, allowing for compact, accurate, and fully integrated filtering essential in low-power EEG front-end systems.

## Target Specification

<div align="center">

| **Parameter**           | **Value**      | **Unit**   |
|-------------------------|-------------|--------|
| Cutoff Frequency (f<sub>c</sub>)  | <250        | Hz     |
| Clock Frequency (f<sub>clk</sub>) | 4         | kHz     |

</div>

## Schematic Design

<p align="center">
  <img src="../../images/LPF_Rev.jpg" alt="LPF_Rev" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1(a). LPF Schematic Inside Chip</h4>

<p align="center">
  <img src="../../images/LPF_EXT_REV.jpg" alt="LPF_EXT_REV" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1(b). LPF Schematic With External Ceramic Capacitor and Inductor</h4>

## Simulation

<p align="center">
  <img src="../../images/TB_LPF1.jpg" alt="TB_LPF1" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Switched-Cap Low Pass Filter Testbench</h4>

<p align="center">
  <img src="../../images/TB_LPF2.jpg" alt="TB_LPF2" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Noise Analysis (1) Result</h4>

<p align="center">
  <img src="../../images/TB_LPF3.jpg" alt="TB_LPF3" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 4. Noise Analysis (2) Result</h4>

<p align="center">
  <img src="../../images/TB_LPF4.jpg" alt="TB_LPF4" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 5. Noise Analysis (3) Result</h4>

## Performance of Designed Switched-Cap Low Pass Filter

<div align="center">

| **Parameter**           | **Value**      | **Unit**   |
|-------------------------|-------------|--------|
| Cutoff Frequency (f<sub>c</sub>)  | <250     | Hz     |
| Clock Frequency (f<sub>clk</sub>) | 4        | kHz     |

Note* : Capacitors have the size of 1u x 1u (m = 3)

</div>

**Last Updated: 16th August**
