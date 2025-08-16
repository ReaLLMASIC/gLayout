# Instrumentation Amplifier Progress Log

An open-loop amplifier is used to provide high gain for low-amplitude EEG signals while minimizing power and silicon area. Unlike closed-loop designs that require additional components such as compensation networks and feedback resistors, open-loop amplifiers offer a simpler architecture with fewer transistors and passive elements. This results in a significantly smaller layout footprint, making it ideal for compact, low-power multi-channel EEG systems where area efficiency is critical.

## Target Specification

<div align="center">

| **Parameter**            | **Typical Value** | **Unit**   |
|----------------------|----------------|--------|
| Open-Loop Gain       | >50            | dB     |
| Bandwidth            | +/-10           | kHz     |
| Phase Margin         | >60           | degrees|
| UGF | 10 - 40 | MHz | 
| Power Supply Rejection Ratio (PSRR) | +/- 60  | dB     |
| Common-Mode Rejection Ratio (CMRR) | >= 70    | dB     |
| Power | < 500 | uW
| Input range (INA) | <=350 | uV |

</div>

## Schematic Design

<p align="center">
  <img src="../../images/SCHEM_INA.jpg" alt=SCHEM_INA" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Individual Instrumentation Amplifier Schematic</h4>

## Simulation

<p align="center">
  <img src="../../images/TSB_INA1.jpg" alt="TSB_INA1" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Instrumentation Amplifier Testbench</h4>

<p align="center">
  <img src="../../images/TSB_INA2.jpg" alt="TSB_INA2" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Gain Testbench Result</h4>

<p align="center">
  <img src="../../images/TSB_INA3.jpg" alt="TSB_INA3" width="1000"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 4. CMRR Testbench Result</h4>

## Performance of Designed Instrumentation Amplifier

<div align="center">

| **Parameter**            | **Typical Value** | **Unit**   |
|----------------------|----------------|--------|
| Open-Loop Gain       | >53.9            | dB     |
| Bandwidth            | +/-10           | kHz     |
| Phase Margin         | >60           | degrees|
| UGF | 33 | MHz | 
| Power Supply Rejection Ratio (PSRR) | 58.17  | dB     |
| Common-Mode Rejection Ratio (CMRR) | 75.71    | dB     |
| Power | +/- 50 | uW
| Input range (INA) | <=350 | uV |

</div>

**Last Updated: 16th August**
