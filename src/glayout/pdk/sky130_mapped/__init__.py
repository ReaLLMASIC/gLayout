"""Package-level SKY130 mapped PDK export."""

try:
    from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk
except Exception:
    sky130_mapped_pdk = None
