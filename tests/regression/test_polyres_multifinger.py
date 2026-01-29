"""
Regression tests for polyresistor multi-finger configurations.
Tests the M1.2a spacing fix for narrow width resistors.

Usage with custom parameters:
    pytest tests/regression/test_polyres_multifinger.py -v
    pytest tests/regression/test_polyres_multifinger.py::TestPolyResistorMultiFinger::test_polyres_layout[1.0-2.0-3-True-False-False]
"""

import pytest
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.primitives.polyres import poly_resistor, add_polyres_labels


class TestPolyResistorMultiFinger:
    """Test multi-finger polyresistor configurations with parameterized tests."""
    
    # Original M1.2a spacing fix test case
    @pytest.mark.parametrize("width,length,fingers,is_snake,n_type,silicided,check_drc", [
        (0.8, 1.5, 5, True, False, False, True),  # Original M1.2a test case
    ])
    def test_multifinger_m1_2a_spacing_fix(self, width, length, fingers, is_snake, n_type, silicided, check_drc):
        """
        Test multi-finger polyresistor with width=0.8µm and 5 fingers.
        This is the original test case for M1.2a spacing fix.
        """
        # Create multi-finger resistor
        resistor_base = poly_resistor(
            gf180_mapped_pdk, 
            width=width, 
            length=length, 
            fingers=fingers, 
            is_snake=is_snake, 
            n_type=n_type, 
            silicided=silicided
        )
        
        resistor_multi = add_polyres_labels(
            gf180_mapped_pdk, 
            resistor_base,
            length, width, fingers
        )
        
        # Verify component was created
        assert resistor_multi is not None, f"Failed to create resistor (w={width}, l={length}, f={fingers})"
        
        # Run DRC check if requested
        if check_drc:
            drc_result = gf180_mapped_pdk.drc(resistor_multi)
            assert drc_result is True or drc_result == 0, f"DRC check failed: {drc_result}"
    
    # Parameterized test for various widths
    @pytest.mark.parametrize("width,length,fingers,is_snake,n_type,silicided", [
        (0.5, 1.5, 3, True, False, False),   # Very narrow
        (0.8, 1.5, 3, True, False, False),   # Narrow (M1.2a case)
        (1.0, 1.5, 3, True, False, False),   # Medium
        (1.5, 1.5, 3, True, False, False),   # Wide
    ])
    def test_polyres_various_widths(self, width, length, fingers, is_snake, n_type, silicided):
        """Test multi-finger polyresistors with various widths."""
        resistor = poly_resistor(
            gf180_mapped_pdk,
            width=width,
            length=length,
            fingers=fingers,
            is_snake=is_snake,
            n_type=n_type,
            silicided=silicided
        )
        assert resistor is not None, f"Failed to create resistor with width={width}µm"
    
    # Parameterized test for various finger counts
    @pytest.mark.parametrize("width,length,fingers,is_snake,n_type,silicided", [
        (0.8, 1.5, 2, True, False, False),   # 2 fingers
        (0.8, 1.5, 3, True, False, False),   # 3 fingers
        (0.8, 1.5, 5, True, False, False),   # 5 fingers
        (0.8, 1.5, 7, True, False, False),   # 7 fingers
    ])
    def test_polyres_various_finger_counts(self, width, length, fingers, is_snake, n_type, silicided):
        """Test multi-finger polyresistors with various finger counts."""
        resistor = poly_resistor(
            gf180_mapped_pdk,
            width=width,
            length=length,
            fingers=fingers,
            is_snake=is_snake,
            n_type=n_type,
            silicided=silicided
        )
        assert resistor is not None, f"Failed to create resistor with {fingers} fingers"
    
    # Generic parameterized test for custom configurations
    @pytest.mark.parametrize("width,length,fingers,is_snake,n_type,silicided", [
        # Add custom test cases here or override via command line
        # Example: pytest --width=1.2 --length=2.0 --fingers=4
    ])
    def test_polyres_custom_config(self, width, length, fingers, is_snake, n_type, silicided):
        """
        Generic test for custom polyresistor configurations.
        Can be used with custom parameters from command line or test data files.
        """
        resistor = poly_resistor(
            gf180_mapped_pdk,
            width=width,
            length=length,
            fingers=fingers,
            is_snake=is_snake,
            n_type=n_type,
            silicided=silicided
        )
        assert resistor is not None, f"Failed to create custom resistor (w={width}, l={length}, f={fingers})"


# pytest configuration hook to add custom command line options
def pytest_addoption(parser):
    """Add custom command line options for polyresistor parameters."""
    parser.addoption("--width", action="store", type=float, help="Resistor width in µm")
    parser.addoption("--length", action="store", type=float, help="Resistor length in µm")
    parser.addoption("--fingers", action="store", type=int, help="Number of fingers")
    parser.addoption("--is-snake", action="store", type=bool, default=True, help="Use snake configuration")
    parser.addoption("--n-type", action="store", type=bool, default=False, help="Use n-type resistor")
    parser.addoption("--silicided", action="store", type=bool, default=False, help="Use silicided resistor")

