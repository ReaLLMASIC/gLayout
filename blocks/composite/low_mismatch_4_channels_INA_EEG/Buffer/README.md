# Buffer Progress Log

An optional unity-gain analog buffer may be inserted at the output stage to maintain signal fidelity when interfacing with external components such as bonding pads, wirebonds, PCB traces, and ADC inputs. Although the buffer does not introduce voltage amplification, it provides high input impedance and low output impedance, effectively isolating the signal source from capacitive and resistive loading effects. This helps prevent signal distortion, such as slow rise/fall times or amplitude attenuation, which could lead to timing inaccuracies in downstream sampling. While not explicitly designed to introduce delay, the buffer can improve signal timing consistency by ensuring that transitions occur cleanly and within expected timing windows.

## Target Specification

<div align="center">

**TBD**

</div>

## Design Reference

<p align="center">
  <img src="../../images/BufferSchemRef.jpg" alt="BufferSchemRef" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Buffer Design Reference</h4>

## Schematic Design 

<p align="center">
  <img src="../../images/BufferSchem.jpg" alt="BufferSchem" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 1. Individual Buffer Schematic</h4>

## Simulation

<p align="center">
  <img src="../../images/BufferFull.jpg" alt="BufferFull" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 2. Buffer Testbench</h4>

<p align="center">
  <img src="../../images/BufferTb.jpg" alt="BufferTb" width="400"/>
</p>
<h4 align="center" style="font-size:16px;">Figure 3. Buffer Result</h4>

## Performance of Designed Chopper Switch 

<div align="center">

**TBD**

</div>

**Last Updated: 1st August**
