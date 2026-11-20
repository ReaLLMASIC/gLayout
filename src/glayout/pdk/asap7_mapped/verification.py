"""Open KLayout verification for the ASAP7 proof of concept.

This is a documented subset of r1p7 DRM checks, not the official Calibre
signoff deck. LVS extracts MOS channels and the SDT/LISD/LIG/V0/M1-M5
connectivity from GDS; it never uses generator metadata to infer devices.
NFIN in the reference is converted to occupied fin-track W for KLayout's
MOS extractor. Actual FIN/channel intersections are checked separately.
"""

from pathlib import Path
import re
import klayout.db as k

# Physical threshold-adjust masks from the ASAP7 r1p7 layer map.
VT_MASKS = {"lvt": 98, "slvt": 97, "sram": 110}


def read_layout(path, topcell=None):
    layout = k.Layout()
    layout.read(str(path))
    top = layout.cell(topcell) if topcell else layout.top_cell()
    if top is None:
        raise ValueError("layout top cell not found or ambiguous")
    return layout, top


def drc(path, topcell=None):
    """Return rule -> violation count. Empty means this POC rule subset passed."""
    layout, top = read_layout(path, topcell)
    dbu = layout.dbu
    errors = {}

    def region(number):
        return k.Region(top.begin_shapes_rec(layout.layer(number, 0))).merged()

    def add(rule, shapes):
        count = shapes.size() if hasattr(shapes, "size") else int(shapes)
        if count:
            errors[rule] = errors.get(rule, 0) + count

    def u(microns):
        return round(microns / dbu)

    def minimum(number, name, width, space, area=0):
        r = region(number)
        add(name + ".W", r.width_check(u(width)))
        add(name + ".S", r.space_check(u(space)))
        if area:
            add(
                name + ".A",
                sum(1 for p in r.each() if p.area() * dbu * dbu < area - 1e-12),
            )
        return r

    # Coordinates are tested before any geometry is rounded to a coarser DBU.
    from glayout.pdk.asap7_mapped import asap7_mapped_pdk
    from glayout.backend import Component

    proxy = Component()
    for info in layout.layer_infos():
        idx = layout.find_layer(info)
        for poly in k.Region(top.begin_shapes_rec(idx)).each():
            proxy.add_polygon(
                [(p.x * dbu, p.y * dbu) for p in poly.each_point_hull()],
                layer=(info.layer, info.datatype),
            )
    try:
        asap7_mapped_pdk.finfet.validate(proxy)
    except ValueError:
        add("GRID", 1)
    active = minimum(11, "ACTIVE", 0.027, 0.027, 0.000864)
    gate = region(7) - region(10)
    fins = region(2)
    for poly in fins.each():
        b = poly.bbox()
        add("FIN.W.1", abs(b.height() * dbu - 0.007) > 1e-9)
        add("FIN.W.2", b.width() * dbu < 0.108 - 1e-9)
    # ACTIVE height must span an integer number of complete fin tracks.
    for poly in active.each():
        b = poly.bbox()
        add(
            "ACTIVE.W.2",
            abs(b.height() * dbu / 0.027 - round(b.height() * dbu / 0.027)) > 1e-6,
        )
    minimum(12, "NSELECT", 0.054, 0)
    minimum(13, "PSELECT", 0.054, 0)
    add("NSELECT.PSELECT.AUX.1", region(12) & region(13))
    thresholds = {vt: region(number) for vt, number in VT_MASKS.items()}
    for vt, mask in thresholds.items():
        add(vt.upper() + ".W.2", mask.width_check(u(0.054)))
        add(vt.upper() + ".W.1", sum(p.bbox().width() < u(0.108) for p in mask.each()))
        covered = active.interacting(mask)
        add(vt.upper() + ".ACTIVE.EN", covered - mask.sized(-u(0.046), -u(0.027), 2))
        add(vt.upper() + ".GATE.EX", gate.interacting(covered) - mask.sized(-u(0.007)))
    masks = list(thresholds.values())
    for i, a in enumerate(masks):
        for b in masks[i + 1 :]:
            add("VT.AUX.2", a & b)
    minimum(1, "WELL", 0.054, 0.054, 0.005832)
    sdt = minimum(88, "SDT", 0.024, 0.030)
    lisd = minimum(17, "LISD", 0.024, 0.018, 0.000648)
    lig = minimum(16, "LIG", 0.016, 0.018, 0.000324)
    for polygon in lig.interacting(gate).each():
        overlap = (k.Region(polygon) & gate).area() * dbu * dbu
        add("LIG.GATE.A.3", overlap < 0.000320 - 1e-12)
    add("SDT.GATE.AUX.1", sdt & gate)
    add("SDT.LISD.AUX.4", sdt - lisd)
    add("SDT.ACTIVE.AUX.3", sdt.not_interacting(active))
    add("LIG.GATE.S.10", lig.separation_check(active & gate, u(0.005)))
    add("LIG.LISD.S.6", lig.separation_check(lisd, u(0.014)))
    metals = []
    for number, name in ((19, "M1"), (20, "M2"), (30, "M3")):
        metals.append(minimum(number, name, 0.018, 0.018, 0.000504))
    for number, name in ((40, "M4"), (50, "M5")):
        metals.append(minimum(number, name, 0.024, 0.024, 0.001152))
    for i, number in enumerate((18, 21, 25, 35, 45)):
        via = minimum(number, f"V{i}", 0.018 if i < 4 else 0.024, 0.018)
        add(f"V{i}.UPPER.INSIDE", via - metals[i])
        if i:
            add(f"V{i}.LOWER.INSIDE", via - metals[i - 1])
        else:
            add("V0.AUX.1", via.not_interacting(lig + lisd))
            add("V0.LISD.INSIDE", via.interacting(lisd) - lisd)
    # A missing/moved FIN must not silently pass as an ordinary planar MOS.
    channels = active & gate
    for ch in channels.each():
        count = (k.Region(ch) & fins).count()
        expected = round(ch.bbox().height() * dbu / 0.027)
        add("CHANNEL.NFIN", count != expected or count < 1)
    return errors


def lvs(gds, spice, output_dir, topcell=None):
    """Extract connectivity, compare against external SPICE, and save evidence."""
    layout, top = read_layout(gds, topcell)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    l2n = k.LayoutToNetlist(k.RecursiveShapeIterator(layout, top, []))

    layer_cache = {}

    def layer(number):
        if number not in layer_cache:
            layer_cache[number] = l2n.make_layer(layout.layer(number, 0), str(number))
        return layer_cache[number]

    active = layer(11)
    gates = layer(7) - layer(10)
    threshold_masks = {vt: layer(number) for vt, number in VT_MASKS.items()}
    marker_union = k.Region()
    for mask in threshold_masks.values():
        if not (marker_union & mask).is_empty():
            raise ValueError("overlapping threshold-adjust masks")
        marker_union += mask
    nbulk = l2n.make_layer("nmos_bulk")
    pbulk = layer(1)
    well_names = l2n.make_text_layer(layout.layer(1, 251), "well_names")
    l2n.connect(pbulk)
    l2n.connect(pbulk, well_names)
    if well_names.is_empty():
        l2n.connect_global(pbulk, "B")
    names = {
        s.text.string for s in top.shapes(layout.layer(3, 251)).each() if s.is_text()
    }
    if len(names) > 1:
        raise ValueError("conflicting implicit substrate names")
    l2n.connect_global(nbulk, next(iter(names), "B"))
    sds = []
    for polarity, select, bulk in (("nmos", 12, nbulk), ("pmos", 13, pbulk)):
        selected = active & layer(select)
        for mask in threshold_masks.values():
            if not (selected.interacting(mask) - mask).is_empty():
                raise ValueError("threshold marker partially covers transistor ACTIVE")
        for vt in ("rvt", *VT_MASKS):
            act = (
                selected - marker_union
                if vt == "rvt"
                else selected & threshold_masks[vt]
            )
            sd = act - gates
            l2n.extract_devices(
                k.DeviceExtractorMOS4Transistor(polarity + "_" + vt),
                {"SD": sd, "G": act & gates, "P": gates, "W": bulk},
            )
            l2n.connect(sd)
            sds.append(sd)
    # Virtual body-contact markers bind the implicit substrate/well to the
    # existing metal rails without inventing planar diffusion masks.
    body = l2n.make_layer(layout.layer(100, 20), "body_contacts")
    well = layer(1)
    body_n = body - well
    body_p = body & well
    names = {
        s.text.string for s in top.shapes(layout.layer(3, 251)).each() if s.is_text()
    }
    substrate = next(iter(names), "B")
    l2n.connect_global(body_n, substrate)
    l2n.connect(body_p, well)
    lig, lisd, sdt, v0 = (layer(n) for n in (16, 17, 88, 18))
    metals = [layer(n) for n in (19, 20, 30, 40, 50)]
    vias = [layer(n) for n in (21, 25, 35, 45)]
    l2n.connect(body_n, metals[0])
    l2n.connect(body_p, metals[0])
    for region in [gates, lig, lisd, sdt, v0] + metals + vias:
        l2n.connect(region)
    for a, b in [
        (gates, lig),
        (sdt, lisd),
        (lig, lisd),
        (lig, v0),
        (lisd, v0),
        (v0, metals[0]),
    ]:
        l2n.connect(a, b)
    for sd in sds:
        l2n.connect(sd, sdt)
    for a, via, b in zip(metals, vias, metals[1:]):
        l2n.connect(a, via)
        l2n.connect(via, b)
    for metal, number in zip(metals, (19, 20, 30, 40, 50)):
        texts = l2n.make_text_layer(layout.layer(number, 2), f"M{number}_labels")
        l2n.connect(metal, texts)
    l2n.extract_netlist()
    extracted = l2n.netlist()
    # MOM extraction measures the actual neighbouring M3 finger edges and
    # probes their physical nets. Broken fingers/contacts create different
    # capacitances or floating nodes and are visible to the comparer.
    from glayout.primitives.momcap import (
        MOM_MARKER,
        MOM_WIDTH,
        MOM_PITCH,
        MOM_FF_PER_UM,
    )

    markers = k.Region(top.begin_shapes_rec(layout.layer(*MOM_MARKER)))
    capclass = k.DeviceClassCapacitor()
    capclass.name = "CAP"
    extracted.add(capclass)
    tc = extracted.circuit_by_name(top.name)
    for marker in markers.each():
        rods = k.Region(top.begin_shapes_rec(layout.layer(30, 0))) & k.Region(marker)
        rods.merge()
        boxes = sorted((p.bbox() for p in rods.each()), key=lambda b: b.left)
        if len(boxes) < 2:
            raise ValueError("MOM marker has fewer than two metal fingers")
        for index, (left, right) in enumerate(zip(boxes, boxes[1:])):
            gap = (right.left - left.right) * layout.dbu
            overlap = (
                min(left.top, right.top) - max(left.bottom, right.bottom)
            ) * layout.dbu
            if gap <= 0 or overlap <= 0:
                raise ValueError("invalid MOM finger geometry")
            nets = []
            for b in (left, right):
                point = k.DPoint(
                    (b.left + b.right) * layout.dbu / 2,
                    (b.bottom + b.top) * layout.dbu / 2,
                )
                net = l2n.probe_net(metals[2], point)
                if net is None:
                    raise ValueError("unconnected MOM finger")
                nets.append(net)
            if nets[0] == nets[1]:
                raise ValueError("shorted MOM plates")
            dev = tc.create_device(capclass)
            dev.set_parameter(
                "C", overlap * (MOM_PITCH - MOM_WIDTH) / gap * MOM_FF_PER_UM * 1e-15
            )
            dev.connect_terminal("A", nets[0])
            dev.connect_terminal("B", nets[1])
    # Well/substrate pins are implicit bulk terminals in ASAP7. Repeated
    # bulk pin labels denote the same external bulk connection. Restrict
    # alias merging to bulk names; ordinary D/G/S opens must remain opens.
    bulk_names = {"B"}
    for number in (1, 3):
        for cell in layout.each_cell():
            bulk_names.update(
                s.text.string
                for s in cell.shapes(layout.layer(number, 251)).each()
                if s.is_text()
            )
    for circuit in extracted.each_circuit():
        for name in bulk_names:
            nets = list(circuit.nets_by_name(name))
            for other in nets[1:]:
                circuit.join_nets(nets[0], other)
    extracted.make_top_level_pins()
    extracted.flatten()
    extracted.purge()
    extracted.combine_devices()
    text = Path(spice).read_text()
    # Only the schematic's nfin determines its expected width. Geometry never
    # supplies reference parameters. Keep L and topology for independent LVS.
    text = re.sub(
        r"\bnfin=(\d+)\b", lambda m: f"w={int(m[1])*0.027:.9g}u", text, flags=re.I
    )
    # Legacy higher-level schematics use X-prefixed MOS leaves, W in um,
    # and SPICE subcircuit parameters. Translate at the verification boundary
    # rather than replacing their netlist or placement generators.
    from glayout.pdk.asap7_mapped import asap7_mapped_pdk

    text = re.sub(
        r"^X(\S+)(\s+\S+\s+\S+\s+\S+\s+\S+\s+(?:nmos|pmos)_(?:rvt|lvt|slvt|sram)\b)",
        r"M\1\2",
        text,
        flags=re.M | re.I,
    )
    text = re.sub(
        r"\bw=([0-9.eE+-]+)(u)?(?=\s|$)",
        lambda m: f"w={asap7_mapped_pdk.finfet.fin_count(float(m[1]))*.027:.9g}u",
        text,
        flags=re.M | re.I,
    )
    text = re.sub(r"\bl=([0-9.eE+-]+)(?=\s|$)", r"l=\1u", text, flags=re.M | re.I)
    reference_path = out / "reference.spice"
    reference_path.write_text(text)
    reference = k.Netlist()
    reference.read(str(reference_path), k.NetlistSpiceReader())
    reference.flatten()
    reference.purge()
    reference.combine_devices()
    if (
        next(extracted.each_circuit_top_down(), None) is None
        or next(reference.each_circuit_top_down(), None) is None
    ):
        raise ValueError("empty extracted or reference circuit")
    next(extracted.each_circuit_top_down(), None).name = next(
        reference.each_circuit_top_down(), None
    ).name
    extracted.write(str(out / "extracted.spice"), k.NetlistSpiceWriter())
    (out / "extracted.txt").write_text(extracted.to_s())
    (out / "reference.txt").write_text(reference.to_s())
    l2n.write(str(out / "extracted.l2n"))
    comparer = k.NetlistComparer()
    ec, rc = next(extracted.each_circuit_top_down(), None), next(
        reference.each_circuit_top_down(), None
    )
    ep = {p.name().upper(): ec.net_for_pin(p.id()) for p in ec.each_pin()}
    rp = {p.name().upper(): rc.net_for_pin(p.id()) for p in rc.each_pin()}
    pins_match = ep.keys() == rp.keys()
    if pins_match:
        for name in ep:
            comparer.same_nets(ep[name], rp[name], True)
    matched = pins_match and comparer.compare(extracted, reference)
    errors = list(l2n.each_log_entry())
    return {
        "match": bool(matched) and not errors,
        "extraction_errors": [str(e) for e in errors],
        "devices": sum(1 for c in extracted.each_circuit() for d in c.each_device()),
    }
