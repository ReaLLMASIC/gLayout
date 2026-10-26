"""Independent three-group placement and two-rail H bias-tree assembly.

This is newly authored train-intended high-level assembly. Only frozen MOS,
via and elementary drawing/terminal-access operations are reused. No circuit
assembly or universal compiler is called. Dimensions are configuration inputs;
the independent reference and electrical contract are outside this module.
"""


def device_dimensions(configuration):
    k, ratio = configuration['K'], configuration['R']
    if type(k) is not int or k not in (2, 4, 8) or type(ratio) is not int or ratio not in (1, 2, 4):
        raise ValueError('Only the declared nine configurations are legal')
    return {name: {'per_finger_width': .5, 'length': .6, 'fingers': fingers}
            for name, fingers in [('MREF', k), ('MOUT1', k), ('MOUT2', k * ratio)]}


def build(configuration):
    import gdsfactory as gf
    from glayout import sky130
    from glayout.primitives.fet import nmos
    from src.generators.terminal_access import expose, pin, via, wire

    dimensions = device_dimensions(configuration)
    top = gf.Component(configuration['top_cell'])
    devices = {}
    for name, size in dimensions.items():
        devices[name] = top << nmos(sky130, width=size['per_finger_width'], length=size['length'],
            fingers=size['fingers'], with_dummy=False, with_tie=True, with_dnwell=False)
    snap = lambda value: round(float(value) / .005) * .005
    left, right, reference = devices['MOUT1'], devices['MOUT2'], devices['MREF']
    def place(device, x, y):
        device.move((snap(x - float(device.x)), snap(y - float(device.y))))
    # Unequal output-array widths change the two independently placed columns.
    # The diode branch occupies its own upper tier, not a netlist-to-row bus.
    place(left, -float(left.xsize) / 2 - 20, 0)
    place(right, float(right.xsize) / 2 + 20, 0)
    output_top = max(float(left.ymax), float(right.ymax))
    place(reference, 0, output_top + float(reference.ysize) / 2 + 30)
    contacts = {name: expose(top, device) for name, device in devices.items()}
    rail_left = snap(min(point[0] for access in contacts.values() for point in access.values()) - 12)
    rail_right = snap(max(float(device.xmax) for device in devices.values()) + 12)
    junction_y = snap(output_top + 15)
    ground_y = snap(min(float(device.ymin) for device in devices.values()) - 20)
    lower_bias_y = min(contacts['MOUT1']['G'][1], contacts['MOUT2']['G'][1])
    upper_bias_y = max(contacts['MREF']['D'][1], contacts['MREF']['G'][1])
    # The two met4 side rails and met5 crossbar form an H. Its four leaf
    # connections are the diode D/G and the two independent output gates.
    for x in (rail_left, rail_right):
        wire(top, 'met4', (x, lower_bias_y), (x, upper_bias_y), .8)
        via(top, 'met4', 'met5', (x, junction_y))
    wire(top, 'met5', (rail_left, junction_y), (rail_right, junction_y), 1.6)
    for name, terminal, x in [('MREF', 'G', rail_left), ('MREF', 'D', rail_right),
                               ('MOUT1', 'G', rail_left), ('MOUT2', 'G', rail_right)]:
        point = contacts[name][terminal]
        via(top, 'met3', 'met5', point)
        wire(top, 'met5', point, (x, point[1]), 1.6)
        via(top, 'met4', 'met5', (x, point[1]))
    # Source/body drops use met4 and meet a separate lower met5 ground rail.
    # They cross bias/output met5 geometry without an inter-net via.
    for access in contacts.values():
        for terminal in ('S', 'B'):
            point = access[terminal]
            via(top, 'met3', 'met4', point)
            wire(top, 'met4', point, (point[0], ground_y), .8)
            via(top, 'met4', 'met5', (point[0], ground_y))
    wire(top, 'met5', (rail_left, ground_y), (rail_right, ground_y), 1.6)
    for name, label in [('MOUT1', 'IOUT1'), ('MOUT2', 'IOUT2')]:
        point = contacts[name]['D']; end = (point[0], snap(output_top + 8))
        via(top, 'met3', 'met4', point)
        wire(top, 'met4', point, end, .8); pin(top, label, end)
    for label, y in [('IREF', junction_y), ('VSS', ground_y)]:
        point = (snap((rail_left + rail_right) / 2), y)
        # Generic met4 is physical SKY130 Metal3: enclose that via landing.
        wire(top, 'met4', point, point, .5)
        via(top, 'met4', 'met5', point); pin(top, label, point)
    return top


def write_gds(configuration, output):
    from src.generators.terminal_access import finish
    return finish(build(configuration), output)


if __name__ == '__main__':
    import argparse
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    generated = write_gds(json.loads(args.configuration.read_text()), args.output.parent)
    if generated != args.output:
        generated.replace(args.output)
