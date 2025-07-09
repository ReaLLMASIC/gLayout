# Low Mismatch 4 Channels Instrumentation Amplifier for Electroencephalography (EEG) Measurement using LLM 

## GenYZ Team Proposal - Track Analog Automation AI/LLM using Glayout

**1. Functionality and Target Specifications**

This chip is a high-precision, low noise instrumentation amplifier array specifically designed for multichannel Electroencephalography (EEG) signal acquisition. This instrumentation amplifier employs a group-chopping technique, in which multiple chopper switches (MOSFETs) are cascaded to sequentially exchange differential input signals across channels. This cyclic routing allows each input to be amplified by every amplifier in the array, effectively averaging out gain mismatches across channels. Additionally, input-referred DC offset is mitigated through chopper modulation and demodulation, which shifts low-frequency noise and offset to higher frequencies where they can be filtered out. As a result, the amplification across all channels becomes uniform and free from bias. 

