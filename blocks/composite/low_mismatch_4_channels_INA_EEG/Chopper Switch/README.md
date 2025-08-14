# Chopper Switch Progress Log

The chopper switch is implemented to reduce low-frequency (1/f) noise and input offset voltage that can severely degrade the quality of EEG signals. It operates by modulating the input signal with a square wave, shifting it to a higher frequency band where amplifier noise is more uniform and less intrusive. After amplification, the signal is demodulated back to baseband, effectively canceling out the low-frequency noise and offset introduced by the amplifier. 

## Target Specification

<div align="center">

| **Parameter**                        | **Value / Target** | **Unit** |
|-------------------------------------|--------------------|----------|
| Stage 1 : Chopper A Operating Frequency       | 4              | kHz       |
| Stage 2 : Chopper B Operating Frequency       | 2            | kHz       |
| Stage 3 : Chopper C Operating Frequency       | 1               | Hz       |
| R<sub>on</sub>                                 | <1                | kΩ       |
| Delay Time Between stages | +/-500              | ns       |
| Off Leakage Current | <0.1 | uA
| Clock divider (to _Clk and Clk) delay | <1 | ms

</div>

## Schematic Design

<p align="center">
  <img src="../../images/SwitchSchem.jpg" alt="SwitchSchem" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Individual Chopper Switch Schematic</h4>

## Simulation

<p align="center">
  <img src="../../images/SwitchFull.jpg" alt="SwitchFull" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Individual Chopper Switch Testbench</h4>

<p align="center">
  <img src="../../images/SwitchTb.jpg" alt="SwitchTb" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Testbench Result</h4>

## Performance of Designed Chopper Switch 

<div align="center">

| **Parameter**                        | **Value / Target** | **Unit** |
|-------------------------------------|--------------------|----------|
| R<sub>on</sub>                                 | TBD                | kΩ       |
| Delay tolerance between CLK and CLK̅ | 0.107              | us       |

</div>

**Last Updated: 1st August**
