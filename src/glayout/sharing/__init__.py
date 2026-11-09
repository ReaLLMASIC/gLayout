"""glayout.sharing: diffusion and gate sharing across the transistors of a device group.

A SharingPlan states, for one group of same-polarity transistors, the order of the unit fingers, their orientation,
which neighbours share a diffusion node and how the gates are grouped into poly straps.  validate_plan checks a plan
before any geometry is drawn; build_mos_group draws it for the active PDK and recomputes, from the drawn rectangles,
how many diffusion nodes and gate conductors are really shared.  group_candidates / named_plans enumerate plans over
six discrete axes.
"""
from .spec import DeviceSpec, SharingPlan, FingerRef, GateGroup, GroupResult, EligibilityReport, SharingPlanRejected
from .rules import rules_for, GroupRules, OVERRIDES
from .group import build_mos_group, validate_plan, independent_plan
from .enumeration import group_candidates, named_plans, AXES, RAW_PER_GROUP
from .evidence import evidence_from_gds, evidence_from_regions
__all__ = ["DeviceSpec", "SharingPlan", "FingerRef", "GateGroup", "GroupResult", "EligibilityReport", "SharingPlanRejected",
           "rules_for", "GroupRules", "OVERRIDES", "build_mos_group", "validate_plan", "independent_plan",
           "evidence_from_gds", "evidence_from_regions", "group_candidates", "named_plans", "AXES", "RAW_PER_GROUP"]
