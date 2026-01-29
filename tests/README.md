# gLayout Regression Tests

This directory contains regression tests for gLayout to ensure previously fixed bugs don't reappear.

## Structure

```
tests/
├── README.md
└── regression/
    └── test_polyres_multifinger.py  # Polyresistor multi-finger tests (M1.2a spacing fix)
```

## Running Tests

### Basic usage

```bash
# Set PDK_ROOT (required)
export PDK_ROOT=/path/to/your/pdk

# Run all regression tests
pytest tests/regression/

# Run with verbose output
pytest tests/regression/test_polyres_multifinger.py -v
```

### Run specific parameterized tests

```bash
# Run only the M1.2a spacing fix test
pytest tests/regression/test_polyres_multifinger.py::TestPolyResistorMultiFinger::test_multifinger_m1_2a_spacing_fix -v

# Run tests for various widths
pytest tests/regression/test_polyres_multifinger.py::TestPolyResistorMultiFinger::test_polyres_various_widths -v

# Run a specific parameter combination
pytest tests/regression/test_polyres_multifinger.py::TestPolyResistorMultiFinger::test_polyres_various_widths[1.0-1.5-3-True-False-False] -v
```

### Using custom parameters via command line

```bash
# Test with custom parameters (requires modifying the test or using conftest.py)
pytest tests/regression/ --width=1.2 --length=2.0 --fingers=4

# Run only tests matching a pattern
pytest tests/regression/ -k "width" -v
```

## Polyresistor Multi-finger Tests

Tests multi-finger polyresistor configurations with the M1.2a spacing fix for narrow width resistors.

### Test Parameters

All tests are parameterized with the following options:
- `width`: Resistor width in µm (e.g., 0.5, 0.8, 1.0, 1.5)
- `length`: Resistor length in µm (e.g., 1.5, 2.0)
- `fingers`: Number of fingers (e.g., 2, 3, 5, 7)
- `is_snake`: Use snake configuration (True/False)
- `n_type`: Use n-type resistor (True/False)
- `silicided`: Use silicided resistor (True/False)

### Key test cases

1. **M1.2a spacing fix** (original bug case)
   - Width: 0.8µm, Length: 1.5µm, Fingers: 5
   - Tests narrow width resistor with M1.2a spacing requirements

2. **Various widths**
   - Tests: 0.5µm, 0.8µm, 1.0µm, 1.5µm widths
   - Validates layout generation across width range

3. **Various finger counts**
   - Tests: 2, 3, 5, 7 fingers
   - Ensures multi-finger scaling works correctly

### Adding Custom Test Cases

Edit `test_polyres_multifinger.py` and add parameters to `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize("width,length,fingers,is_snake,n_type,silicided", [
    (1.2, 2.0, 4, True, False, False),  # Your custom test case
])
def test_polyres_custom_config(self, width, length, fingers, is_snake, n_type, silicided):
    # Test implementation
```
