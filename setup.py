from setuptools import setup, find_packages
from pathlib import Path

# Read README.md
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="glayout",
    version="0.2.0",
    description="A PDK-agnostic layout automation framework for analog circuit design",
    long_description=long_description,
    long_description_content_type="text/markdown", 
    author="OpenFASOC Team",
    author_email="mehdi@umich.edu",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=[
        "gdsfactory>6.0.0,<=7.7.0",
        "numpy>1.21.0,<=1.24.0",
        "pandas>1.3.0,<=2.3.0",
        "matplotlib>3.4.0,<=3.10.0",
        "klayout>0.28.0,<=0.29",
        # `docopt` is imported by gf180mcu's bundled `run_lvs.py` (under
        # `$PDK_ROOT/ciel/gf180mcu/versions/<hash>/gf180mcuD/libs.tech/
        # klayout/tech/lvs/run_lvs.py`). The gf180 LVS dispatch in
        # `tests/lvs/klayout_gf180.py` execs that script via the active
        # python3, so docopt must be importable from the venv that runs
        # LVS — otherwise every gf180 LVS report contains only
        # `ModuleNotFoundError: No module named 'docopt'` and the deck
        # never runs.
        "docopt",
        # `PortTree.print()` passes `default_orientation`, which PrettyPrintTree
        # removed in 2.0, so an unconstrained install raises TypeError. 1.36.x
        # keeps the argument but does not constrain its own `cmd2` dependency,
        # and cmd2 4.x moved `cmd2.ansi`, which makes `PrettyPrint` unimportable
        # — `port_utils` then silently falls back to its no-op shim. Both bounds
        # are needed for the printer to actually produce output.
        "prettyprinttree>=1.36.4,<2",
        "cmd2<3",
        "gdstk",
        "svgutils",
        "nltk",
        "ipywidgets",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "isort>=5.0.0",
            "flake8>=4.0.0",
        ],
        "ml": [
            "torch>=1.10.0",
            "transformers>=4.0.0",
            "scikit-learn>=1.0.0",
        ],
        "llm": [
            "torch>=2.0.0",
            "transformers>=4.30.0",
            "datasets>=2.12.0",
            "google-generativeai>=0.3.0",
            "seaborn>=0.11.0",
            "pandas>=1.5.0",
            "numpy>=1.24.0",
            "matplotlib>=3.6.0",
            "accelerate>=0.20.0",
            "tiktoken",
            "jupyter",
            "scipy>=1.10.0",
            "pathlib2",
            "argparse",          
        ]
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
    ],
)
