# Instrumentation Amplifier
This amplifier uses an open-loop differential architecture to achieve high voltage gain with a relatively simple structure and a small number of transistors.

<img width="611" height="415" alt="image" src="https://github.com/user-attachments/assets/5718d6a5-ebc6-4ec8-b07d-6c73bba0663c" />


### Differential Input Pair
Transistors PM1 and PM2 form the differential input pair, which receives the input signals VIN+ and VIN−. They convert the input voltage difference into differential current.

### Gain Stage / Active Load
Transistors NM1, NM2, NM3, and NM4 act as the active load and gain stage, converting the differential current into output voltages at VOUT+ and VOUT− while maintaining differential operation.

**dnwell must be added manually to nmos pair

### Biasing Transistor
Transistor PM3 provides the bias current for the amplifier. The current is controlled by a bias voltage (Vbias) applied to its gate (VB), meaning the circuit uses voltage biasing instead of an Ibias current source.

### Differential Output
The amplifier produces differential outputs, VOUT+ and VOUT−, which represent the amplified difference between the input signals.


## Parameterization
Configuration  : Contains the PMOS and NMOS device parameters used in the amplifier, including transistor width, length,
               finger count, multipliers, dummy devices, and metal tie layers, which define the sizing and layout
               configuration of each transistor block.
               
x_distance    : Sets the horizontal separation between the left and right sides of the differential pair.

row_gap       : Defines the vertical spacing between different transistor rows.

bias_gap      : Defines the vertical spacing between the bias block and the main circuit.

trunk_pitch_in: Controls the pitch (spacing/width) of the vertical routing trunks for the input signals.

trunk_pitch_out: Controls the pitch of the vertical routing trunks for the output signals.

outpad_margin : Sets the spacing buffer between the core amplifier layout and the I/O pads or chip boundary.

outer_keepout : Defines the clearance distance for the outer guard ring.

nmos_pair_outer_ring_padding: Sets the spacing between the NMOS differential pair and the outer guard ring.

bias_gate_route_dx: Specifies the horizontal extension used to route the VBIAS connection.

c_route_extension: Defines the extension length for the common routing path.

vcm_dx        : Sets the horizontal offset for the VCM (common-mode voltage) connection.

vin_dx        : Specifies the horizontal routing extension for the input connections.

vout_dx       : Specifies the horizontal routing extension for the output connections.

```
def generate_ina(
    pdk: MappedPDK,
    Configuration: Dict[str,Any] = None,
    x_distance: int = 5,
    row_gap: float = 6.0,
    bias_gap: float = 4.0,
    trunk_pitch_in: float =3.4,
    trunk_pitch_out: float =1.0,
    outpad_margin: float = 35.0,
    outer_keepout: float = 6.0,
    nmos_pair_outer_ring_padding: float = 2.2,
    bias_gate_route_dx: float = 25.0,
    c_route_extension: float = 6.0,
    vcm_dx: float = -20.0,
    vin_dx: float = 40.0,
    vout_dx: float = 40.0,
    nmos_kwargs: Dict[str,Any] = None,
    pmos_kwargs: Dict[str,Any] = None,
    **kwargs
    ) -> Component:
```
Example of how to define Configuration:
```
CFG = {
    "pmos_pair": {"pdk": gf180, "placement": "horizontal", "width": (6, 6), "length": (3, 3), "fingers": (6, 6), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
    "pmos_bias": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
    "nmos_pair": {"pdk": gf180, "placement": "horizontal", "width": (3, 3), "length": (3, 3), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
    "nmos_mirror": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1},
    "pmos_diode": {"pdk": gf180, "placement": "horizontal", "width": (0.5, 0.5), "length": (6.9, 6.9), "fingers": (1, 1), "multipliers": (1, 1), "dummy_1": (True, True), "dummy_2": (True, True), "tie_layers1": ("met2", "met1"), "tie_layers2": ("met2", "met1"), "sd_rmult": 1}
    }
```

## Generated GDS
<img width="841" height="781" alt="image" src="https://github.com/user-attachments/assets/1880dc68-3f74-4034-9741-364415cc0efa" />

## DRC Report
```
using default pdk_root
Defaulting to stale magic_commands.tcl

Magic 8.3 revision 528 - Compiled on Wed Jun 18 09:45:25 PM CEST 2025.
Starting magic under Tcl interpreter
Using the terminal as the console.
WARNING: RLIMIT_NOFILE is above 1024 and Tcl_Version<9 this may cause runtime issues [rlim_cur=1048576]
Using NULL graphics device.
Processing system .magicrc file
Sourcing design .magicrc for technology gf180mcuD ...
10 Magic internal units = 1 Lambda
Input style import: scaleFactor=10, multiplier=2
The following types are not handled by extraction and will be treated as non-electrical types:
    obsactive mvobsactive filldiff fillpoly m1hole obsm1 fillm1 obsv1 m2hole obsm2 fillm2 obsv2 m3hole obsm3 fillm3 m4hole obsm4 fillm4 m5hole obsm5 fillm5 glass fillblock lvstext obscomment 
Scaled tech values by 10 / 1 to match internal grid scaling
Loading gf180mcuD Device Generator Menu ...
Loading "/tmp/tmpu3sxch2e/magic_commands.tcl" from command line.
Warning: Calma reading is not undoable!  I hope that's OK.
Library written using GDS-II Release 6.0
Library name: library
Reading "INA".
[INFO]: Loading INA

Loading DRC CIF style.
No errors found.
[INFO]: DONE with /tmp/tmpu3sxch2e/INA.rpt

Using technology "gf180mcuD", version 1.0.525-0-gf2e289d

{'result_str': 'magic drc script passed\nNo errors found in DRC report',
 'subproc_code': 0}
```
