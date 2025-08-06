from setuptools import setup, find_packages
from pathlib import Path

# Read README.md
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="glayout",
    version="0.1.2",
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
        "klayout>=0.28.0",
        "prettyprint",
        "prettyprinttree",
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
