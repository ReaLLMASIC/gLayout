# Glayout

A PDK-agnostic layout automation framework for analog circuit design.

## Overview

Glayout is a powerful layout automation tool that generates DRC-clean circuit layouts for any technology implementing the Glayout framework. It is implemented as an easy-to-install Python package with all dependencies available on PyPI.

Key features:
- PDK-agnostic layout generation
- Support for multiple technology nodes (sky130, gf180)
- DRC-clean layout generation
- Natural language processing for circuit design
- Integration with Klayout for visualization and verification

## Installation

### Basic Installation

```bash
pip install .
```

### Development Installation

```bash
git clone https://github.com/your-username/glayout.git
cd glayout
pip install -e ".[dev]"
```

### ML Features Installation

```bash
pip install -e ".[ml]"
```

### LLM Features Installation

```bash
pip install -e ".[llm]"
```

## Quick Start

```python
from glayout import sky130, gf180, nmos ,pmos,via_stack

# Generate a via stack
#met2 is the bottom layer. met3 is the top layer.
via = via_stack(sky130, "met2", "met3", centered=True) 

# Generate a transistor
transistor = nmos(sky130, width=1.0, length=0.15, fingers=2)

# Write to GDS
via.write_gds("via.gds")
transistor.write_gds("transistor.gds")
```

## Documentation

For detailed documentation, please visit our [documentation site](https://glayout.readthedocs.io/).

## Features

### PDK Agnostic Layout
- Generic layer mapping
- Technology-independent design rules
- Support for multiple PDKs (sky130, gf180)

### Circuit Generators
- Via stack generation
- Transistor generation (NMOS/PMOS)
- Guard ring generation
- And more...

### Natural Language Processing/Large Language Model Framework
- Convert natural language descriptions to layouts
- Support for standard components
- Custom component definitions

### Supported Open Source PDKs
- SkyWater [SKY-130A](https://skywater-pdk.readthedocs.io/en/main/)
- GlobalFoundries [GF-180mcuD](https://gf180mcu-pdk.readthedocs.io/en/latest/)

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/contributor_guide.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Citation

If you use Glayout in your research, please cite our papers:

```bibtex
@article{hammoud2024human,
  title={Human Language to Analog Layout Using Glayout Layout Automation Framework},
  author={Hammoud, A. and Goyal, C. and Pathen, S. and Dai, A. and Li, A. and Kielian, G. and Saligane, M.},
  journal={Accepted at MLCAD},
  year={2024}
}

@article{hammoud2024reinforcement,
  title={Reinforcement Learning-Enhanced Cloud-Based Open Source Analog Circuit Generator for Standard and Cryogenic Temperatures in 130-nm and 180-nm OpenPDKs},
  author={Hammoud, A. and Li, A. and Tripathi, A. and Tian, W. and Khandeparkar, H. and Wans, R. and Kielian, G. and Murmann, B. and Sylvester, D. and Saligane, M.},
  journal={Accepted at ICCAD},
  year={2024}
}
```

## Contact

For questions and support, please contact:
- Email: mehdi_saligane@brown.edu
