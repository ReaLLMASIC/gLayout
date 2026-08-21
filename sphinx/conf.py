"""Sphinx configuration for the Glayout documentation."""
from __future__ import annotations

import os
import sys
from importlib import metadata
from importlib.util import find_spec
import pathlib
from pathlib import Path

HERE = Path(__file__).parent.resolve()
REPO_ROOT = HERE.parent

# Allow autodoc to import the package without a prior `pip install .`
# (CI installs the package, which makes this a no-op there, but keeps
# `sphinx-build` working from a fresh checkout).
sys.path.insert(0, os.path.abspath("../src"))

# Local extension providing the verification-results directives.
sys.path.insert(0, str(HERE / "_ext"))

project = "glayout"
author = "ReaLLMASIC"
copyright = "2026, ReaLLMASIC"

try:
    release = metadata.version("glayout")
except metadata.PackageNotFoundError:
    release = "0.0.0"
version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
    "glayout_results",
]

# The API reference is generated from docstrings and needs the package to be
# importable. A bare checkout without `pip install -e .` should still build the
# narrative docs, so autosummary is switched off in that case and api.rst
# renders an install hint instead of aborting the build.
GLAYOUT_IMPORTABLE = find_spec("glayout") is not None


def _discover_modules(package: str = "glayout") -> list[str]:
    """Top-level subpackages of *package*, discovered rather than hard-coded.

    autosummary raises a fatal ExtensionError on the first name it cannot
    import, so listing modules by hand makes the build hostage to the package
    layout — a directory without ``__init__.py`` takes the whole build down.

    Only depth-1 names are returned: the ``:recursive:`` flag on the autosummary
    directive walks everything below them. Listing deeper names as well puts the
    same stub in two toctrees and produces one warning per module. Where a
    depth-1 package cannot be resolved, its immediate children are listed
    instead so its contents are not lost.
    """
    if not GLAYOUT_IMPORTABLE:
        return []

    import pkgutil

    spec = find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return []

    search = list(spec.submodule_search_locations)

    def resolves(name: str) -> bool:
        try:
            return find_spec(name) is not None
        except (ImportError, AttributeError, ValueError):
            return False

    found: list[str] = []
    try:
        for info in pkgutil.iter_modules(search, prefix=f"{package}."):
            leaf = info.name.rsplit(".", 1)[-1]
            if leaf.startswith("_") or leaf in ("tests", "test"):
                continue
            if resolves(info.name):
                found.append(info.name)
            elif info.ispkg:
                # Unimportable parent (usually a missing __init__.py): keep the
                # children that do resolve rather than dropping the subtree.
                child_paths = [str(pathlib.Path(p) / leaf) for p in search]
                for child in pkgutil.iter_modules(child_paths,
                                                  prefix=f"{info.name}."):
                    if resolves(child.name):
                        found.append(child.name)
    except Exception:  # discovery is best-effort; never fail the build over it
        return []
    return sorted(found)


GLAYOUT_MODULES = _discover_modules()

# Written on every build as a real page (api.rst lists it in a toctree) rather
# than an included fragment: autosummary scans documents, so a fragment that is
# excluded from the build never gets its stub pages generated.
#
# This file is build output, not source — keep it gitignored.
_api_page = HERE / "api_modules.rst"
_header = "Module index\n============\n\n"
if GLAYOUT_MODULES:
    _api_page.write_text(
        _header
        + f"Discovered from the installed package ({len(GLAYOUT_MODULES)} modules).\n\n"
        ".. autosummary::\n"
        "   :toctree: _autosummary\n"
        "   :recursive:\n\n"
        + "".join(f"   {name}\n" for name in GLAYOUT_MODULES),
        encoding="utf-8",
    )
else:
    _api_page.write_text(
        _header
        + "The module reference is generated from docstrings and needs\n"
        "``glayout`` to be importable. Install the package and rebuild to\n"
        "populate this section:\n\n"
        ".. code-block:: console\n\n"
        "   pip install -e .\n",
        encoding="utf-8",
    )

autosummary_generate = bool(GLAYOUT_MODULES)
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "ignore-module-all": True,
}
autodoc_typehints = "description"
autodoc_member_order = "bysource"

# The layout generators pull in EDA-adjacent packages that are not installed in
# the docs environment. Mock them so autodoc can still read signatures.
autodoc_mock_imports = [
    "gdsfactory",
    "gdstk",
    "klayout",
    "sky130",
    "gf180",
    "torch",
]

napoleon_google_docstring = True
napoleon_numpy_docstring = True

if os.environ.get("GLAYOUT_ENABLE_INTERSPHINX"):
    intersphinx_mapping = {
        "python": ("https://docs.python.org/3", None),
        "gdsfactory": ("https://gdsfactory.github.io/gdsfactory/", None),
    }
else:
    intersphinx_mapping = {}

myst_enable_extensions = ["colon_fence", "deflist"]

templates_path = ["_templates"]
exclude_patterns = [
    "_build", "data", "Thumbs.db", ".DS_Store", "README.md",
]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

# -- Verification results ----------------------------------------------------
# The result tables are generated at build time from the summary.json files the
# runners already write:
#
#     <root>/drc_results/<pdk>/summary.json
#     <root>/lvs_results/<pdk>/summary.json
#     <root>/sim_results/<pdk>/summary.json
#
# A local run or a CI artifact download puts those at the repo root; a bare
# checkout falls back to the committed sample so the docs always build.

glayout_pdks = ["sky130", "gf180"]

_local_results = REPO_ROOT / "sim_results"
glayout_results_root = os.environ.get("GLAYOUT_RESULTS_ROOT") or str(
    REPO_ROOT if _local_results.exists() else HERE / "data" / "sample"
)

# Set GLAYOUT_RESULTS_STRICT=1 in CI so missing or malformed runner output fails
# the build instead of quietly publishing sample data.
glayout_results_strict = os.environ.get("GLAYOUT_RESULTS_STRICT") == "1"

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["glayout.css"]
html_title = f"glayout {release}"

html_theme_options = {
    "source_repository": "https://github.com/ReaLLMASIC/gLayout/",
    "source_branch": "main",
    "source_directory": "sphinx/",
}


def setup(app):
    """Expose package availability to the documents as a Sphinx tag."""
    if GLAYOUT_IMPORTABLE:
        app.tags.add("has_glayout")
    return {"parallel_read_safe": True}
