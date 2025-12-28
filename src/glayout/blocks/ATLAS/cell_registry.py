#!/usr/bin/env python3
"""
Cell Registry - Configuration for all supported cell types

This module provides a centralized configuration system for different cell types
in the dataset generator. Each cell type has metadata about:
- Which module/function to import
- Parameter format and requirements
- Output naming conventions
- Label/pin annotation functions

This allows the main dataset generator to be generic and work with any cell type
without hardcoding cell-specific logic.
"""

CELL_CONFIGS = {
    "txgate": {
        # Module and function information
        "module": "glayout.blocks.ATLAS.transmission_gate",
        "function": "transmission_gate",
        "label_function": "sky130_add_tg_labels",
        
        # Output naming
        "prefix": "tg",
        "display_name": "Transmission Gate",
        
        # Parameter structure
        "param_format": "complementary",  # (nmos, pmos) tuples for width/length
        "required_params": ["width", "length", "fingers", "multipliers"],
        
        # Description
        "description": "CMOS transmission gate with complementary NMOS/PMOS transistors",
    },
    
    "fvf": {
        "module": "glayout.blocks.ATLAS.fvf",
        "function": "flipped_voltage_follower",
        "label_function": "sky130_add_fvf_labels",
        
        "prefix": "fvf",
        "display_name": "Flipped Voltage Follower",
        
        "param_format": "complementary",  # (nmos, pmos) tuples
        "required_params": ["width", "length", "fingers", "multipliers"],
        
        "description": "Flipped voltage follower amplifier circuit",
    },
    
    "lvcm": {
        "module": "glayout.blocks.elementary.lvcm.lvcm",
        "function": "low_voltage_current_mirror",
        "label_function": "sky130_add_lvcm_labels",
        
        "prefix": "lvcm",
        "display_name": "Low Voltage Current Mirror",
        
        "param_format": "mixed",  # width is tuple, length is scalar
        "required_params": ["width", "length", "fingers", "multipliers"],
        
        "description": "Low voltage current mirror with width tuple and scalar length",
    },
    
    "current_mirror": {
        "module": "glayout.blocks.elementary.current_mirror.current_mirror",
        "function": "current_mirror_netlist",
        "label_function": None,  # No label function for current mirror
        
        "prefix": "cm",
        "display_name": "Current Mirror",
        
        "param_format": "single",  # scalar values (not tuples)
        "required_params": ["width", "length", "numcols"],
        
        "description": "Basic current mirror circuit with scalar parameters",
    },
    
    "diff_pair": {
        "module": "glayout.blocks.elementary.diff_pair.diff_pair",
        "function": "diff_pair",
        "label_function": None,  # No label function for diff pair
        
        "prefix": "dp",
        "display_name": "Differential Pair",
        
        "param_format": "single",  # scalar values
        "required_params": ["width", "length", "fingers", "n_or_p_fet"],
        
        "description": "Differential pair amplifier with selectable FET type",
    },
    
    "opamp": {
        "module": "glayout.blocks.ATLAS.opamp",
        "function": "opamp",
        "label_function": None,  # No label function for opamp
        
        "prefix": "opamp",
        "display_name": "Operational Amplifier",
        
        "param_format": "complex",  # nested tuples and multiple sub-components
        "required_params": [
            "half_diffpair_params",
            "diffpair_bias",
            "half_common_source_params",
            "common_source_bias",
            "output_bias",
        ],
        
        "description": "Complete operational amplifier with multiple stages",
    },
}


def get_cell_config(cell_type):
    """
    Get configuration for a specific cell type.
    
    Args:
        cell_type: String identifier for the cell type (e.g., "txgate", "fvf")
        
    Returns:
        Dictionary containing cell configuration
        
    Raises:
        ValueError: If cell_type is not supported
        
    Example:
        >>> config = get_cell_config("txgate")
        >>> print(config["display_name"])
        Transmission Gate
        >>> print(config["prefix"])
        tg
    """
    if cell_type not in CELL_CONFIGS:
        supported = list(CELL_CONFIGS.keys())
        raise ValueError(
            f"Unknown cell type: '{cell_type}'\n"
            f"Supported cell types: {supported}"
        )
    return CELL_CONFIGS[cell_type]


def list_supported_cells():
    """
    Get list of all supported cell types.
    
    Returns:
        List of cell type identifiers
        
    Example:
        >>> cells = list_supported_cells()
        >>> print(cells)
        ['txgate', 'fvf', 'lvcm', 'current_mirror', 'diff_pair', 'opamp']
    """
    return list(CELL_CONFIGS.keys())


def get_cell_info(cell_type=None):
    """
    Get human-readable information about cell types.
    
    Args:
        cell_type: Optional specific cell type. If None, returns info for all cells.
        
    Returns:
        Formatted string with cell information
        
    Example:
        >>> print(get_cell_info("txgate"))
        Transmission Gate (txgate)
        Description: CMOS transmission gate with complementary NMOS/PMOS transistors
        Parameters: width, length, fingers, multipliers
        Output prefix: tg
    """
    if cell_type is not None:
        config = get_cell_config(cell_type)
        return (
            f"{config['display_name']} ({cell_type})\n"
            f"Description: {config['description']}\n"
            f"Parameters: {', '.join(config['required_params'])}\n"
            f"Output prefix: {config['prefix']}"
        )
    else:
        lines = ["Available Cell Types:\n"]
        for ct in list_supported_cells():
            config = CELL_CONFIGS[ct]
            lines.append(
                f"  • {config['display_name']} ({ct})"
                f" - {config['description']}"
            )
        return "\n".join(lines)


def validate_parameters(cell_type, params):
    """
    Validate that parameters contain all required fields for a cell type.
    
    Args:
        cell_type: Cell type identifier
        params: Dictionary of parameters
        
    Returns:
        Tuple of (is_valid, missing_params)
        
    Example:
        >>> params = {"width": (1.0, 2.0), "length": (0.15, 0.15)}
        >>> valid, missing = validate_parameters("txgate", params)
        >>> if not valid:
        ...     print(f"Missing: {missing}")
        Missing: ['fingers', 'multipliers']
    """
    config = get_cell_config(cell_type)
    required = set(config['required_params'])
    provided = set(params.keys())
    missing = required - provided
    
    return len(missing) == 0, list(missing)


if __name__ == "__main__":
    # Demo/test code
    print("=" * 70)
    print("Cell Registry Demo")
    print("=" * 70)
    
    # List all supported cells
    print("\n📋 Supported Cell Types:")
    for cell in list_supported_cells():
        config = get_cell_config(cell)
        print(f"  ✓ {config['display_name']:30s} [{cell}] -> {config['prefix']}_*")
    
    # Show detailed info
    print("\n" + "=" * 70)
    print(get_cell_info())
    
    # Example: Get config for txgate
    print("\n" + "=" * 70)
    print("Example: Get Transmission Gate Configuration")
    print("=" * 70)
    txgate_config = get_cell_config("txgate")
    print(f"Module to import: {txgate_config['module']}")
    print(f"Function to call: {txgate_config['function']}")
    print(f"Label function: {txgate_config['label_function']}")
    print(f"Output prefix: {txgate_config['prefix']}")
    print(f"Parameter format: {txgate_config['param_format']}")
    
    # Test parameter validation
    print("\n" + "=" * 70)
    print("Example: Parameter Validation")
    print("=" * 70)
    test_params = {
        "width": (1.0, 2.0),
        "length": (0.15, 0.15),
        "fingers": (4, 4),
        # Missing 'multipliers'
    }
    valid, missing = validate_parameters("txgate", test_params)
    if valid:
        print("✅ Parameters are valid!")
    else:
        print(f"❌ Parameters are incomplete. Missing: {missing}")
    
    # Test error handling
    print("\n" + "=" * 70)
    print("Example: Error Handling")
    print("=" * 70)
    try:
        get_cell_config("nonexistent_cell")
    except ValueError as e:
        print(f"✅ Caught expected error:\n   {e}")
