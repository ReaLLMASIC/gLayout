"""Package-level GF180 mapped PDK export."""

try:
    from glayout.pdk.gf180_mapped.gf180_mapped import gf180_mapped_pdk
except Exception:
    gf180_mapped_pdk = None
