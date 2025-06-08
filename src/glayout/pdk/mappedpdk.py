"""
MappedPDK - A PDK-agnostic layout automation framework for analog circuit design
"""

from gdsfactory.pdk import Pdk
from gdsfactory.typings import Component, PathType, Layer
from pydantic import validator, StrictStr, ValidationError
from typing import ClassVar, Optional, Any, Union, Literal, Iterable, TypedDict
from pathlib import Path
from decimal import Decimal, ROUND_UP
import tempfile
import subprocess
import xml.etree.ElementTree as ET
import pathlib
import shutil
import os
import sys

class SetupPDKFiles:
    """Class to setup the PDK files required for DRC and LVS checks."""

    def __init__(
        self, 
        pdk_root: Optional[PathType] = None, 
        klayout_drc_file: Optional[PathType] = None, 
        lvs_schematic_ref_file: Optional[PathType] = None,
        lvs_setup_tcl_file: Optional[PathType] = None, 
        magic_drc_file: Optional[PathType] = None,
        temp_dir: Optional[PathType] = None,
        pdk: Optional[str] = 'sky130'
    ):
        """Initializes the class with the required PDK files for DRC and LVS checks."""
        self.pdk = pdk
        self.temp_dir = temp_dir
        self.pdk_root = pdk_root
        self.klayout_drc_file = klayout_drc_file
        self.lvs_schematic_ref_file = lvs_schematic_ref_file
        self.lvs_setup_tcl_file = lvs_setup_tcl_file
        self.magic_drc_file = magic_drc_file

    def return_dict_of_files(self) -> dict:
        """Returns a dictionary of all PDK files."""
        return {
            'pdk': self.pdk,
            'temp_dir': self.temp_dir,
            'pdk_root': self.pdk_root,
            'klayout_drc_file': self.klayout_drc_file,
            'lvs_schematic_ref_file': self.lvs_schematic_ref_file,
            'lvs_setup_tcl_file': self.lvs_setup_tcl_file,
            'magic_drc_file': self.magic_drc_file
        }

class MappedPDK(Pdk):
    """A PDK-agnostic layout automation framework for analog circuit design.
    
    Inherits everything from the Pdk class but also requires mapping to glayers.
    glayers are generic layers which can be returned with get_glayer(name: str).
    has_required_glayers(list[str]) is used to verify all required generic layers are present.
    """

    valid_glayers: ClassVar[tuple[str]] = (
        "dnwell",
        "pwell",
        "nwell",
        "p+s/d",
        "n+s/d",
        "active_diff",
        "active_tap",
        "poly",
        "mcon",
        "met1",
        "via1",
        "met2",
        "via2",
        "met3",
        "via3",
        "met4",
        "via4",
        "met5",
        "capmet",
        # _pin layers
        "met5_pin",
        "met4_pin",
        "met3_pin",
        "met2_pin",
        "met1_pin",
        "poly_pin",
        "active_diff_pin",
        # _label layers
        "met5_label",
        "met4_label",
        "met3_label",
        "met2_label",
        "met1_label",
        "poly_label",
        "active_diff_label",
    )

    models: dict = {
        "nfet": "",
        "pfet": "",
        "mimcap": ""
    }

    glayers: dict[StrictStr, Union[StrictStr, tuple[int,int]]]
    grules: dict[StrictStr, dict[StrictStr, Optional[dict[StrictStr, Any]]]]
    pdk_files: dict[StrictStr, Union[PathType, None]]

    @validator("models")
    def models_check(cls, models_obj: dict[StrictStr, StrictStr]):
        """Validates that only nfet, pfet, or mimcap models are specified."""
        for model in models_obj.keys():
            if not model in ["nfet","pfet","mimcap"]:
                raise ValueError(f"specify nfet, pfet, or mimcap models only")
        return models_obj

    @validator("glayers")
    def glayers_check_keys(cls, glayers_obj: dict[StrictStr, Union[StrictStr, tuple[int,int]]]):
        """Validates that glayers keys are from the valid_glayers set."""
        for glayer, mapped_layer in glayers_obj.items():
            if (not isinstance(glayer, str)) or (not isinstance(mapped_layer, Union[str, tuple])):
                raise TypeError("glayers should be passed as dict[str, Union[StrictStr, tuple[int,int]]]")
            if glayer not in cls.valid_glayers:
                raise ValueError(
                    "glayers keys must be one of generic layers listed in class variable valid_glayers"
                )
        return glayers_obj

    def get_glayer(self, layer: str) -> Layer:
        """Returns the pdk layer from the generic layer name."""
        direct_mapping = self.glayers[layer]
        if isinstance(direct_mapping, tuple):
            return direct_mapping
        else:
            return self.get_layer(direct_mapping)

    def get_grule(
        self, glayer1: str, glayer2: Optional[str] = None, return_decimal = False
    ) -> dict[StrictStr, Union[float,Decimal]]:
        """Returns a dictionary describing the relationship between two layers.
        
        If one layer is specified, returns a dictionary with all intra layer rules.
        """
        if glayer1 not in MappedPDK.valid_glayers:
            raise ValueError("get_grule, " + str(glayer1) + " not valid glayer")
        
        # decide if two or one inputs and set rules_dict accordingly
        rules_dict = None
        if glayer2 is not None:
            if glayer2 not in MappedPDK.valid_glayers:
                raise ValueError("get_grule, " + str(glayer2) + " not valid glayer")
            rules_dict = self.grules.get(glayer1, dict()).get(glayer2)
            if rules_dict is None or rules_dict == {}:
                rules_dict = self.grules.get(glayer2, dict()).get(glayer1)
        else:
            glayer2 = glayer1
            rules_dict = self.grules.get(glayer1, dict()).get(glayer1)
        
        # error check, convert type, and return
        if rules_dict is None or rules_dict == {}:
            raise NotImplementedError(
                "no rules found between " + str(glayer1) + " and " + str(glayer2)
            )
        
        for rule in rules_dict:
            if type(rule) == float and return_decimal:
                rules_dict[rule] = Decimal(str(rule))
        return rules_dict

    def has_required_glayers(self, layers_required: list[str]):
        """Raises ValueError if any of the generic layers in layers_required are not mapped.
        
        Also checks that the values in the glayers dictionary map to real Pdk layers.
        """
        for layer in layers_required:
            if layer not in self.glayers:
                raise ValueError(
                    f"{layer!r} not in self.glayers {list(self.glayers.keys())}"
                )
            if isinstance(self.glayers[layer], str):
                self.validate_layers([self.glayers[layer]])
            elif not isinstance(self.glayers[layer], tuple):
                raise TypeError("glayer mapped value should be str or tuple[int,int]")

    def layer_to_glayer(self, layer: tuple[int, int]) -> str:
        """Returns the glayer name if layer corresponds to a glayer, else raises an exception.
        
        Takes layer as a tuple(int,int).
        """
        # lambda for finding last matching key in dict from val
        find_last = lambda val, d: [x for x, y in d.items() if y == val].pop()
        
        if layer in self.glayers.values():
            return find_last(layer, self.glayers)
        elif self.layers is not None:
            # find glayer verifying presence along the way
            pdk_real_layers = self.layers.values()
            if layer in pdk_real_layers:
                layer_name = find_last(layer, self.layers)
                if layer_name in self.glayers.values():
                    glayer_name = find_last(layer_name, self.glayers)
                else:
                    raise ValueError("layer does not correspond to a glayer")
            else:
                raise ValueError("layer is not a layer present in the pdk")
            return glayer_name
        else:
            raise ValueError("layer might not be a layer present in the pdk")

    @classmethod
    def is_routable_glayer(cls, glayer: StrictStr) -> bool:
        """Returns True if the glayer is routable (metal, active, or poly)."""
        return any(hint in glayer for hint in ["met", "active", "poly"])

    def snap_to_2xgrid(self, value: float) -> float:
        """Snaps a value to 2x grid size."""
        grid_size = self.grid_size
        return round(value / (2 * grid_size)) * (2 * grid_size)

    def util_max_metal_seperation(
        self, 
        metal_levels: Union[list[int], list[str], str, int] = range(1,6)
    ) -> float:
        """Returns the maximum of the min_seperation rule for all layers specified.
        
        Although the name of this function is util_max_metal_seperation, 
        layers do not have to be metals. You can specify non metals by using 
        metal_levels=list of glayers.
        
        Args:
            metal_levels: If list of int, integers are converted to metal levels.
                        If a single int is provided, all metals below and including 
                        that int level are considered.
                        By default returns the maximum metal separation of metals1-5.
        """
        if type(metal_levels)==int:
            metal_levels = range(1,metal_levels+1)
        metal_levels = metal_levels if isinstance(metal_levels,Iterable) else [metal_levels]
        if len(metal_levels)<1:
            raise ValueError("metal levels cannot be empty list")
        if type(metal_levels[0])==int:
            metal_levels = [f"met{i}" for i in metal_levels]
        
        sep_rules = list()
        for met in metal_levels:
            sep_rules.append(self.get_grule(met)["min_separation"])
        return self.snap_to_2xgrid(max(sep_rules)) 