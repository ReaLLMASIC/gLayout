"""Debug aid: trace a piece of layout back to the Python code that drew it.

Most glayout generators flatten what they return (routes, via stacks, and on
gf180 the finished cells), so the GDS hierarchy rarely says where a shape came
from. When enabled, every Component remembers the glayout call chain that
created it, and when it is placed into a parent it gets a text label on
DEBUG_LAYER at its bbox center. Labels ride along through moves, transforms
and flatten(), so they survive into the written GDS.

Enable before building anything (cached cells built earlier are not tagged):

    GLAYOUT_PROVENANCE=1 python my_script.py
    # or: from glayout.util import provenance; provenance.enable()

Then ask which generators cover a point (coordinates as shown in KLayout):

    python -m glayout.util.provenance cmirror.gds 1.25 -3.4

or switch on layer 255/0 in KLayout and hover the labels. Label text is
"<w>x<h> | innermost call < ... < outermost call".

Debug only: the labels add a layer the PDK does not know, so do not run
DRC/LVS on a GDS built with provenance enabled.

Caveat: @cell functions return cached cells, so a cell reused from the cache
carries the call chain of whoever created it first.
"""

from __future__ import annotations

import os
import sys

DEBUG_LAYER = (255, 0)

_GLAYOUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# helper modules that copy/rename components; they add noise, not context
_SKIP_DIRS = tuple(os.path.join(_GLAYOUT_DIR, d) + os.sep for d in ("backend", "util"))
_LIB_MARKERS = (os.sep + "site-packages" + os.sep, os.sep + "dist-packages" + os.sep)
_STDLIB_PREFIXES = tuple({sys.base_prefix, sys.prefix})

_origins: dict[int, str] = {}
_tagged: set[int] = set()
_enabled = False


def _is_user_frame(filename: str) -> bool:
    filename = os.path.abspath(filename)
    if filename.startswith(_SKIP_DIRS) or any(m in filename for m in _LIB_MARKERS):
        return False
    if filename.startswith(_GLAYOUT_DIR + os.sep):
        return True
    # user scripts: anything that is not the interpreter's own stdlib
    return not filename.startswith(_STDLIB_PREFIXES) and not filename.startswith("<")


def _call_chain(frame) -> str:
    links = []
    while frame is not None:
        code = frame.f_code
        if _is_user_frame(code.co_filename):
            path = os.path.abspath(code.co_filename)
            if path.startswith(_GLAYOUT_DIR + os.sep):
                path = os.path.relpath(path, _GLAYOUT_DIR)
            else:
                path = os.path.basename(path)
            links.append(f"{code.co_name} {path}:{frame.f_lineno}")
        frame = frame.f_back
    return " < ".join(links)


def enable() -> None:
    """Patch the gdsfactory Component class so new geometry is tagged."""
    global _enabled
    if _enabled:
        return
    from glayout.backend import get_backend

    if get_backend() != "gdsfactory":
        raise RuntimeError("provenance tracking only supports the gdsfactory backend")
    from gdsfactory.component import Component

    orig_init = Component.__init__
    orig_register = Component._register_reference

    def __init__(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        chain = _call_chain(sys._getframe(1))
        if chain:
            _origins[id(self)] = chain

    # add_ref(), `<<` and add(ref) all register the reference through here
    def _register_reference(self, reference, alias=None):
        child = reference.parent
        key = id(child)
        chain = _origins.get(key)
        if chain and key not in _tagged:
            (xmin, ymin), (xmax, ymax) = child.bbox
            was_locked = child._locked
            child.unlock()
            child.add_label(
                f"{xmax - xmin:.3f}x{ymax - ymin:.3f} | {chain}",
                position=((xmin + xmax) / 2, (ymin + ymax) / 2),
                layer=DEBUG_LAYER,
            )
            child._locked = was_locked
            _tagged.add(key)
        return orig_register(self, reference, alias=alias)

    Component.__init__ = __init__
    Component._register_reference = _register_reference
    _enabled = True


def where(gds_path: str, x: float, y: float, cell: str | None = None) -> list[tuple[float, str]]:
    """Return (area, call chain) for every tagged component whose bbox holds (x, y),
    smallest first -- the first entry is usually the generator you are after."""
    import gdstk

    if not os.path.isfile(gds_path):
        raise FileNotFoundError(f"no such GDS file: {os.path.abspath(gds_path)}")
    lib = gdstk.read_gds(gds_path)
    tops = lib.top_level()
    top = next(c for c in lib.cells if c.name == cell) if cell else tops[0]
    hits = []
    for label in top.get_labels(layer=DEBUG_LAYER[0], texttype=DEBUG_LAYER[1]):
        size, _, chain = label.text.partition(" | ")
        w, h = (float(v) for v in size.split("x"))
        if round(label.rotation / (3.141592653589793 / 2)) % 2:
            w, h = h, w
        w, h = w * label.magnification, h * label.magnification
        cx, cy = label.origin
        if abs(x - cx) <= w / 2 + 1e-6 and abs(y - cy) <= h / 2 + 1e-6:
            hits.append((w * h, chain))
    return sorted(hits)


if os.environ.get("GLAYOUT_PROVENANCE") and __name__ != "__main__":
    enable()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gds")
    parser.add_argument("x", type=float)
    parser.add_argument("y", type=float)
    parser.add_argument("--cell", help="cell to search (default: the top cell)")
    args = parser.parse_args()
    try:
        hits = where(args.gds, args.x, args.y, args.cell)
    except FileNotFoundError as err:
        sys.exit(str(err))
    if not hits:
        print("no tagged component covers that point; the shape was drawn directly "
              "in the top cell (or the GDS was built without GLAYOUT_PROVENANCE=1)")
    for area, chain in hits:
        print(f"{area:10.3f} um^2  " + "\n                 < ".join(chain.split(" < ")))
