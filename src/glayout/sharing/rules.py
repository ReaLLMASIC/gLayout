"""Design-rule adapter for the shared-group builder.

All numbers come from the MappedPDK generic rule table (``pdk.get_grule``)
except where that table is missing an entry or is known to disagree with the
foundry rule deck.  Those cases are listed explicitly in ``OVERRIDES`` with the
foundry rule identifier so that they can be audited.  Nothing here relaxes a
foundry rule: every override is equal to or more conservative than the deck.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

GRID = 0.005  # manufacturing grid used by all three PDKs (sky130, gf180mcu, sg13g2)


def snap(x: float, grid: float = GRID) -> float:
    return round(round(x / grid) * grid, 4)


def snap_up(x: float, grid: float = GRID) -> float:
    import math
    return round(math.ceil(round(x / grid, 6)) * grid, 4)


def snap2(x: float, grid: float = GRID) -> float:
    """Snap to twice the grid (keeps centred shapes on grid)."""
    return snap(x, 2 * grid)


# Explicit, auditable overrides: pdk -> key -> (value, rule id / justification)
OVERRIDES = {
    "ihp130": {
        "act_enc_cont": (0.07, "Cnt.c"),
        "poly_enc_cont": (0.07, "Cnt.d"),
        "cont_gate_sep": (0.11, "Cnt.f (Cont on Activ to GatPoly)"),
        "contpoly_act_sep": (0.14, "Cnt.e (Cont on GatPoly to Activ)"),
        "m1_enc_cont": (0.05, "M1.c1 endcap (M1.c is 0.00)"),
        "m1_enc_via1": (0.05, "V1.c1 endcap"),
        "m2_enc_via1": (0.05, "M2.c1 endcap"),
        "m2_enc_via2": (0.05, "V2.c1 endcap"),
        "m3_enc_via2": (0.05, "M3.c1 endcap"),
        "endcap": (0.18, "Gat.c"),
        "poly_act_sep": (0.07, "Gat.d"),
        "poly_sep": (0.18, "Gat.b"),
        "pimp_enc_act": (0.18, "pSD.c"),
        "pimp_enc_gate": (0.30, "pSD.i (pSD enclosure of PFET gate)"),
        "pimp_w_min": (0.31, "pSD.a"),
        "pimp_sep": (0.31, "pSD.b"),
        "pimp_to_nact": (0.18, "pSD.d"),
        "nimp_layer": (None, "SG13G2 Activ is n+ by default; nSD drawing is not required for NMOS"),
        "nwell_enc_pact": (0.31, "NW.c"),
        "nwell_enc_ntap": (0.24, "NW.e"),
        "nwell_to_nact": (0.31, "NW.d"),
        "nwell_to_ptap": (0.24, "NW.f"),
        "nwell_w_min": (0.62, "NW.a"),
        "m1_area_min": (0.09, "M1.d"),
        "m2_area_min": (0.144, "M2.d"),
        "m3_area_min": (0.144, "M3.d"),
        "poly_area_min": (0.09, "Gat.e"),
        "act_area_min": (0.122, "Act.d"),
        "act_sd_ext_min": (0.23, "Act.c"),
        "m3_w": (0.20, "M3.a"), "m3_sep": (0.21, "M3.b"),
        "via2_w": (0.19, "V2.a"), "via2_sep": (0.22, "V2.b"),
        "tap_act_sep": (0.21, "Act.b (same layer) + pSD.d 0.18 implant spacing handled separately"),
        "pimp_to_ntap": (0.16, "Cnt.g1 0.09 pSD space to Cont on nSD-Activ + Cnt.c 0.07 (and pSD.d1 0.03)"),
    },
    "sky130": {
        # sky130 generic layers in gLayout: met1=li1, via1=mcon, met2=met1, via2=via, met3=met2
        "contpoly_act_sep": (0.19, "licon.11/poly licon to diff (conservative)"),
        "poly_act_sep": (0.075, "poly.7"),
        "m1_area_min": (0.0561, "li.6"),
        "m2_area_min": (0.083, "m1.6"),
        "m3_area_min": (0.0676, "m2.6"),
        "poly_area_min": (0.0, "n/a"),
        "act_area_min": (0.0, "n/a"),
        "act_sd_ext_min": (0.0, "n/a"),
        "pimp_enc_gate": (0.125, "psdm enclosure (same as diff)"),
        "nwell_enc_pact": (0.18, "nwell.3"),
        "nwell_enc_ntap": (0.18, "nwell.3"),
        "nwell_to_nact": (0.34, "difftap.9 / nwell spacing to ndiff (conservative)"),
        "nwell_to_ptap": (0.13, "difftap.10"),
        "nwell_w_min": (0.84, "nwell.1"),
        "tap_act_sep": (0.27, "difftap.3"),
        "pimp_to_nact": (0.13, "nsdm/psdm spacing to diff"),
        "pimp_to_ntap": (0.13, "psdm spacing to n+ tap diffusion"),
    },
    "gf180": {
        "poly_sep": (0.24, "PL.3a (generic table has no poly spacing entry)"),
        "contpoly_act_sep": (0.15, "poly contact to COMP, conservative value (rule id not confirmed)"),
        "poly_act_sep": (0.1, "PL.5a"),
        "m1_area_min": (0.1444, "metal-1 minimum area, conservative value (rule id not confirmed)"),
        "m2_area_min": (0.1444, "M2.3"),
        "m3_area_min": (0.1444, "M3.3"),
        "poly_area_min": (0.0, "n/a"),
        "act_area_min": (0.2025, "DF.6"),
        "act_sd_ext_min": (0.24, "DF.3a"),
        "pimp_enc_gate": (0.16, "PP.5 (same as comp enclosure)"),
        "nwell_enc_pact": (0.43, "nwell enclosure of PCOMP, conservative value (rule id not confirmed)"),
        "nwell_enc_ntap": (0.12, "NW enclosure of ncomp tap"),
        "nwell_to_nact": (0.43, "NW spacing to ncomp (conservative)"),
        "nwell_to_ptap": (0.12, "nwell to pcomp tap"),
        "nwell_w_min": (0.86, "NW.1a"),
        "tap_act_sep": (0.28, "DF.4"),
        "pimp_to_nact": (0.16, "PP spacing to NCOMP"),
        "pimp_to_ntap": (0.16, "PP spacing to NCOMP tap"),
    },
}


@dataclass
class GroupRules:
    pdk_name: str
    grid: float
    L_min: float
    poly_w_min: float
    poly_sep: float
    endcap: float
    poly_act_sep: float
    act_w_min: float
    act_sep: float
    cont_w: float
    cont_sep: float
    act_enc_cont: float
    poly_enc_cont: float
    cont_gate_sep: float
    contpoly_act_sep: float
    m1_w: float
    m1_sep: float
    m1_enc_cont: float
    via1_w: float
    via1_sep: float
    m1_enc_via1: float
    m2_enc_via1: float
    m2_w: float
    m2_sep: float
    via2_w: float
    via2_sep: float
    m2_enc_via2: float
    m3_enc_via2: float
    m3_w: float
    m3_sep: float
    nimp_layer: Optional[tuple]
    pimp_layer: Optional[tuple]
    nimp_enc_act: float
    pimp_enc_act: float
    pimp_enc_gate: float
    imp_w_min: float
    imp_sep: float
    pimp_to_nact: float
    pimp_to_ntap: float
    nwell_layer: tuple
    nwell_enc_pact: float
    nwell_enc_ntap: float
    nwell_to_nact: float
    nwell_to_ptap: float
    nwell_w_min: float
    tap_act_sep: float
    act_enc_cont_tap: float
    m1_area_min: float
    m2_area_min: float
    m3_area_min: float
    poly_area_min: float
    act_area_min: float
    act_sd_ext_min: float
    layers: dict = field(default_factory=dict)
    overrides_used: dict = field(default_factory=dict)

    # ---- derived -------------------------------------------------------
    @property
    def min_contactable_width(self) -> float:
        """Smallest unit finger width that hosts one contact without a dogbone."""
        return snap_up(self.cont_w + 2 * self.act_enc_cont)

    def m1_bar_w(self) -> float:
        return snap_up(max(self.m1_w, self.cont_w + 2 * self.m1_enc_cont))

    def via1_pad_w(self) -> float:
        return snap_up(max(self.m2_w, self.via1_w + 2 * self.m2_enc_via1, self.sq_from_area(self.m2_area_min)))

    def via1_m1_w(self) -> float:
        return snap_up(max(self.m1_w, self.via1_w + 2 * self.m1_enc_via1))

    @staticmethod
    def sq_from_area(area: float) -> float:
        import math
        return math.sqrt(area) if area > 0 else 0.0

    def to_json(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("layers",)}
        d["layers"] = {k: list(v) if v else None for k, v in self.layers.items()}
        return d


def _ov(pdk_name: str, key: str, default, used: dict):
    ov = OVERRIDES.get(pdk_name, {})
    if key in ov:
        used[key] = {"value": ov[key][0], "rule": ov[key][1]}
        return ov[key][0]
    return default


def rules_for(pdk) -> GroupRules:
    g = pdk.get_grule
    name = pdk.name
    used = {}

    def ovr(key, default):
        return _ov(name, key, default, used)

    def gr(a, b=None, key="min_separation", default=None):
        try:
            v = g(a, b)[key] if b else g(a)[key]
            return v if v is not None else default
        except Exception:
            return default

    layers = {
        "active": pdk.get_glayer("active_diff"), "poly": pdk.get_glayer("poly"), "cont": pdk.get_glayer("mcon"),
        "met1": pdk.get_glayer("met1"), "via1": pdk.get_glayer("via1"), "met2": pdk.get_glayer("met2"),
        "via2": pdk.get_glayer("via2"), "met3": pdk.get_glayer("met3"),
        "nwell": pdk.get_glayer("nwell"), "nimp": pdk.get_glayer("n+s/d"), "pimp": pdk.get_glayer("p+s/d"),
        "tap": pdk.get_glayer("active_tap"),
    }
    for lay in ("met1", "met2", "met3"):
        for suf in ("_pin", "_label"):
            try: layers[lay + suf] = pdk.get_glayer(lay + suf)
            except Exception: layers[lay + suf] = None
    nimp = ovr("nimp_layer", layers["nimp"])
    r = GroupRules(
        pdk_name=name, grid=GRID,
        L_min=gr("poly", key="min_width"), poly_w_min=gr("poly", key="min_width"),
        poly_sep=ovr("poly_sep", gr("poly", key="min_separation")),
        endcap=ovr("endcap", gr("poly", "active_diff", "overhang")),
        poly_act_sep=ovr("poly_act_sep", gr("poly", "active_diff", "min_separation", 0.1)),
        act_w_min=gr("active_diff", key="min_width"), act_sep=gr("active_diff", key="min_separation"),
        cont_w=gr("mcon", key="width"), cont_sep=gr("mcon", key="min_separation"),
        act_enc_cont=ovr("act_enc_cont", gr("active_diff", "mcon", "min_enclosure")),
        poly_enc_cont=ovr("poly_enc_cont", max(gr("poly", "mcon", "min_enclosure", 0.0), gr("mcon", "poly", "min_enclosure", 0.0))),
        cont_gate_sep=ovr("cont_gate_sep", gr("poly", "mcon", "min_separation")),
        contpoly_act_sep=ovr("contpoly_act_sep", 0.2),
        m1_w=gr("met1", key="min_width"), m1_sep=gr("met1", key="min_separation"),
        m1_enc_cont=ovr("m1_enc_cont", gr("mcon", "met1", "min_enclosure", 0.0)),
        via1_w=gr("via1", key="width"), via1_sep=gr("via1", key="min_separation"),
        m1_enc_via1=ovr("m1_enc_via1", gr("met1", "via1", "min_enclosure", 0.0)),
        m2_enc_via1=ovr("m2_enc_via1", gr("via1", "met2", "min_enclosure", 0.0)),
        m2_w=gr("met2", key="min_width"), m2_sep=gr("met2", key="min_separation"),
        via2_w=ovr("via2_w", gr("via2", key="width")), via2_sep=ovr("via2_sep", gr("via2", key="min_separation")),
        m2_enc_via2=ovr("m2_enc_via2", gr("met2", "via2", "min_enclosure", 0.0)),
        m3_enc_via2=ovr("m3_enc_via2", gr("via2", "met3", "min_enclosure", 0.0)),
        m3_w=ovr("m3_w", gr("met3", key="min_width")), m3_sep=ovr("m3_sep", gr("met3", key="min_separation")),
        nimp_layer=nimp, pimp_layer=layers["pimp"],
        nimp_enc_act=gr("n+s/d", "active_diff", "min_enclosure", 0.13),
        pimp_enc_act=ovr("pimp_enc_act", gr("p+s/d", "active_diff", "min_enclosure", 0.13)),
        pimp_enc_gate=ovr("pimp_enc_gate", gr("p+s/d", "active_diff", "min_enclosure", 0.13)),
        imp_w_min=ovr("pimp_w_min", gr("p+s/d", key="min_width", default=0.38)),
        imp_sep=ovr("pimp_sep", gr("p+s/d", key="min_separation", default=0.38)),
        pimp_to_nact=ovr("pimp_to_nact", 0.18), pimp_to_ntap=ovr("pimp_to_ntap", 0.18),
        nwell_layer=layers["nwell"],
        nwell_enc_pact=ovr("nwell_enc_pact", gr("nwell", "active_tap", "min_enclosure", 0.18)),
        nwell_enc_ntap=ovr("nwell_enc_ntap", gr("nwell", "active_tap", "min_enclosure", 0.18)),
        nwell_to_nact=ovr("nwell_to_nact", 0.34), nwell_to_ptap=ovr("nwell_to_ptap", 0.24),
        nwell_w_min=ovr("nwell_w_min", gr("nwell", key="min_width")),
        tap_act_sep=ovr("tap_act_sep", gr("active_diff", "active_tap", "min_separation", 0.27)),
        act_enc_cont_tap=max(gr("active_tap", "mcon", "min_enclosure", 0.0), ovr("act_enc_cont", gr("active_diff", "mcon", "min_enclosure"))),
        m1_area_min=ovr("m1_area_min", 0.0), m2_area_min=ovr("m2_area_min", 0.0), m3_area_min=ovr("m3_area_min", 0.0),
        poly_area_min=ovr("poly_area_min", 0.0), act_area_min=ovr("act_area_min", 0.0), act_sd_ext_min=ovr("act_sd_ext_min", 0.0),
        layers=layers, overrides_used=used,
    )
    return r
