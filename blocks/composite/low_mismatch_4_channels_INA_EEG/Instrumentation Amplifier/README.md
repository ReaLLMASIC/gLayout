# Instrumentation Amplifier Progress Log

An open-loop amplifier is used to provide high gain for low-amplitude EEG signals while minimizing power and silicon area. Unlike closed-loop designs that require additional components such as compensation networks and feedback resistors, open-loop amplifiers offer a simpler architecture with fewer transistors and passive elements. This results in a significantly smaller layout footprint, making it ideal for compact, low-power multi-channel EEG systems where area efficiency is critical.

## Target Specification

<div align="center">

| **Parameter**            | **Typical Value** | **Unit**   |
|----------------------|----------------|--------|
| Open-Loop Gain       | >50            | dB     |
| Bandwidth            | 10           | kHz     |
| Phase Margin         | >45            | degrees|
| Power Supply Rejection Ratio (PSRR) | >= 60  | dB     |
| Common-Mode Rejection Ratio (CMRR) | >= 80    | dB     |

</div>

## Schematic Design

<p align="center">
  <img src="../../images/INASchem.jpg" alt="SwitchSchem" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Individual Instrumentation Amplifier Schematic</h4>

## Simulation

<p align="center">
  <img src="../../images/INAFull.jpg" alt="SwitchFull" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Instrumentation Amplifier Testbench</h4>

<p align="center">
  <img src="../../images/INATb.jpg" alt="SwitchTb" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Testbench Result</h4>

## Performance of Designed Instrumentation Amplifier

<div align="center">

| **Parameter**            | **Typical Value** | **Unit**   |
|----------------------|----------------|--------|
| Open-Loop Gain       | 52.65            | dB     |
| Bandwidth            | 10            | kHz     |
| Phase Margin         | TBD            | degrees|
| Power Supply Rejection Ratio (PSRR) | TBD    | dB     |
| Common-Mode Rejection Ratio (CMRR) | 95    | dB     |

</div>

**Last Updated: 1st August**
