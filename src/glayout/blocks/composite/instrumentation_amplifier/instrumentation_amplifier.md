# Instrumentation Amplifier
This amplifier uses an open-loop differential architecture to achieve high voltage gain with a relatively simple structure and a small number of transistors.

<img width="611" height="415" alt="image" src="https://github.com/user-attachments/assets/5718d6a5-ebc6-4ec8-b07d-6c73bba0663c" />


### Differential Input Pair
Transistors PM1 and PM2 form the differential input pair, which receives the input signals VIN+ and VIN−. They convert the input voltage difference into differential current.

### Gain Stage / Active Load
Transistors NM1, NM2, NM3, and NM4 act as the active load and gain stage, converting the differential current into output voltages at VOUT+ and VOUT− while maintaining differential operation.

### Biasing Transistor
Transistor PM3 provides the bias current for the amplifier. The current is controlled by a bias voltage (Vbias) applied to its gate (VB), meaning the circuit uses voltage biasing instead of an Ibias current source.

### Differential Output
The amplifier produces differential outputs, VOUT+ and VOUT−, which represent the amplified difference between the input signals.

## Parameterization
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

  ""
  Creates an open-loop differential amplifier using a PMOS input pair,
  NMOS active loads, and voltage biasing (Vbias).
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
  ""

```

## DRC Report

