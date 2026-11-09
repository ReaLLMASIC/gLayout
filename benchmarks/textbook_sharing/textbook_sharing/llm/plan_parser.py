"""Restricted-Python front end for model-written sharing programs.

A model answer must contain one ```python block whose only statement is

    plans = { <group index>: <plan expression>, ... }          # one entry per sharing group of the task

<plan expression> is either
    SharingPlan(finger_order=[("M1", 0), ...], orientations=["SD", ...], diffusion_joins=[True, ...],
                gate_groups=[GateGroup(fingers=(0, 2), side="bottom", pad_end="left"), ...])
or  axis_plan(arrangement=..., orientation=..., diffusion=..., gate=..., strap_start=..., contact_end=...)

This is NOT a Python interpreter: the AST is walked by `_ev`, which accepts only literals, list/tuple/dict displays,
unary minus, list/tuple concatenation and repetition by an integer literal, `range(...)`, `list(...)`, `tuple(...)`,
and calls of the three names above with keyword arguments.  Anything else is rejected with a structured error
(code, message, line).  The parsed plans are then checked by glayout.sharing.validate_plan (the same legality check
the builders use) and built by textbook_sharing.layout.build."""
from __future__ import annotations
import ast, re

ALLOWED_CALLS = {"SharingPlan", "GateGroup", "axis_plan", "fet_row", "range", "list", "tuple"}
# interface variants: "sharing" (the sharing interface) and "base" (capability of base gLayout multi-finger devices and
# interdigitated / common-centroid placement helpers: per-device finger arrangement, orientation and contact end,
# fingers of one device share diffusion, NO cross-device diffusion node and NO shared gate conductor)
INTERFACE_CALLS = {"sharing": ("SharingPlan", "axis_plan"), "base": ("fet_row",)}
BASE_FIXED = {"diffusion": "none", "gate": "per_device", "strap_start": "bottom"}
BASE_AXES = {"arrangement": ("block", "interleave", "abba", "mirror"), "orientation": ("alt_SD", "alt_DS"), "contact_end": ("left", "right")}


class ParseError(Exception):
    def __init__(self, code, message, line=None):
        super().__init__(message); self.code = code; self.message = message; self.line = line

    def to_json(self):
        return {"code": self.code, "message": self.message, "line": self.line}


def extract_code(answer: str) -> str:
    m = re.findall(r"```(?:python|py)?\s*\n(.*?)```", answer, re.S)
    if not m:
        raise ParseError("no_code_block", "the answer must contain exactly one ```python code block")
    if len(m) > 1:
        raise ParseError("multiple_code_blocks", f"found {len(m)} code blocks; give exactly one")
    return m[0]


def _ev(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None: return node.value
        raise ParseError("literal_type", f"literal of type {type(node.value).__name__} not allowed", node.lineno)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _ev(node.operand)
        if isinstance(v, (int, float)): return -v
        raise ParseError("operator", "unary minus only on numbers", node.lineno)
    if isinstance(node, (ast.List, ast.Tuple)):
        vals = [_ev(e) for e in node.elts]
        return vals if isinstance(node, ast.List) else tuple(vals)
    if isinstance(node, ast.Dict):
        return {_ev(k): _ev(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        a, b = _ev(node.left), _ev(node.right)
        if isinstance(node.op, ast.Add) and isinstance(a, (list, tuple)) and type(a) == type(b): return a + b
        if isinstance(node.op, ast.Mult) and isinstance(a, (list, tuple)) and isinstance(b, int) and 0 <= b <= 512: return a * b
        if isinstance(node.op, ast.Mult) and isinstance(b, (list, tuple)) and isinstance(a, int) and 0 <= a <= 512: return b * a
        raise ParseError("operator", "only list/tuple concatenation and repetition by a small integer are allowed", node.lineno)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            raise ParseError("call_not_allowed", f"only {sorted(ALLOWED_CALLS)} may be called", node.lineno)
        name = node.func.id
        args = [_ev(a) for a in node.args]; kw = {k.arg: _ev(k.value) for k in node.keywords if k.arg}
        if any(k.arg is None for k in node.keywords):
            raise ParseError("syntax", "**kwargs not allowed", node.lineno)
        if name == "range":
            if kw or not (1 <= len(args) <= 3) or not all(isinstance(a, int) for a in args):
                raise ParseError("range", "range takes 1-3 integer arguments", node.lineno)
            r = list(range(*args))
            if len(r) > 4096: raise ParseError("range", "range too long", node.lineno)
            return r
        if name in ("list", "tuple"):
            if kw or len(args) != 1 or not isinstance(args[0], (list, tuple)):
                raise ParseError("call_args", f"{name}() takes one list/tuple/range", node.lineno)
            return list(args[0]) if name == "list" else tuple(args[0])
        if args:
            raise ParseError("call_args", f"{name}() takes keyword arguments only", node.lineno)
        return {"__call__": name, **kw, "__line__": node.lineno}
    raise ParseError("syntax", f"construct {type(node).__name__} is not allowed in a plan program", getattr(node, "lineno", None))


def parse_program(code: str, interface: str = "sharing") -> dict:
    """Returns {group_index: call-dict}. Raises ParseError."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ParseError("python_syntax", f"Python syntax error: {e.msg}", e.lineno)
    stmts = [s for s in tree.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Assign) or len(stmts[0].targets) != 1 or not isinstance(stmts[0].targets[0], ast.Name) or stmts[0].targets[0].id != "plans":
        raise ParseError("program_shape", "the program must consist of exactly one statement: plans = {...}")
    val = _ev(stmts[0].value)
    if not isinstance(val, dict):
        raise ParseError("program_shape", "plans must be a dict {group_index: plan}")
    out = {}
    for k, v in val.items():
        if not isinstance(k, int): raise ParseError("group_key", f"group keys must be integers, got {k!r}")
        allowed = INTERFACE_CALLS[interface]
        if not (isinstance(v, dict) and v.get("__call__") in allowed):
            raise ParseError("plan_value", f"group {k}: value must be one of {' / '.join(a + '(...)' for a in allowed)} in this interface")
        out[k] = v
    return out


def to_sharing_plan(call: dict, devices, pdk):
    """Turn a parsed call into a glayout.sharing.SharingPlan (or raise ParseError with a structured reason)."""
    from glayout.sharing import SharingPlan, GateGroup, FingerRef
    from glayout.sharing import enumeration as E
    line = call.get("__line__")
    if call["__call__"] == "fet_row":
        keys = set(k for k in call if not k.startswith("__"))
        if keys != set(BASE_AXES):
            raise ParseError("fet_row_args", f"fet_row needs exactly {sorted(BASE_AXES)}; got {sorted(keys)}", line)
        for k, vals in BASE_AXES.items():
            if call[k] not in vals: raise ParseError("axis_value", f"{k}={call[k]!r} not in {list(vals)}", line)
        call = {**{k: v for k, v in call.items()}, **BASE_FIXED, "__call__": "axis_plan"}
        pl = to_sharing_plan(call, devices, pdk); pl.mode_label = "llm:fet_row"; return pl
    if call["__call__"] == "axis_plan":
        keys = set(k for k in call if not k.startswith("__"))
        need = set(E.AXES)
        if keys != need:
            raise ParseError("axis_plan_args", f"axis_plan needs exactly {sorted(need)}; got {sorted(keys)}", line)
        for k in need:
            if call[k] not in E.AXES[k]:
                raise ParseError("axis_value", f"{k}={call[k]!r} not in {list(E.AXES[k])}", line)
        dev = {d.logical_id: d for d in devices}
        order, why = E._order(devices, call["arrangement"])
        if order is None: raise ParseError("axis_illegal", why, line)
        orient = E._orientations(order, dev, call["orientation"])
        joins = E._joins(order, orient, dev, call["diffusion"])
        gg, why = E._gate_groups(order, dev, call["gate"], call["strap_start"], call["contact_end"])
        if gg is None: raise ParseError("axis_illegal", why, line)
        return SharingPlan(order, orient, joins, gg, mode_label="llm:axis_plan")
    req = {"finger_order", "orientations", "diffusion_joins", "gate_groups"}
    keys = set(k for k in call if not k.startswith("__"))
    if not req <= keys or keys - req:
        raise ParseError("sharingplan_args", f"SharingPlan needs exactly {sorted(req)}; got {sorted(keys)}", line)
    try:
        fo = [FingerRef(str(a), int(b)) for a, b in call["finger_order"]]
    except Exception:
        raise ParseError("finger_order", "finger_order must be a list of (device_name, finger_index) pairs", line)
    gg = []
    for g in call["gate_groups"]:
        if not (isinstance(g, dict) and g.get("__call__") == "GateGroup"):
            raise ParseError("gate_groups", "gate_groups must be a list of GateGroup(...)", line)
        gk = set(k for k in g if not k.startswith("__"))
        if gk != {"fingers", "side", "pad_end"}:
            raise ParseError("gategroup_args", f"GateGroup needs fingers, side, pad_end; got {sorted(gk)}", g.get("__line__"))
        try:
            gg.append(GateGroup(tuple(int(x) for x in g["fingers"]), str(g["side"]), str(g["pad_end"])))
        except Exception:
            raise ParseError("gategroup_args", "GateGroup fingers must be integer positions", g.get("__line__"))
    ori = call["orientations"]; joins = call["diffusion_joins"]
    if not (isinstance(ori, list) and all(isinstance(o, str) for o in ori)):
        raise ParseError("orientations", "orientations must be a list of 'SD'/'DS' strings", line)
    if not (isinstance(joins, list) and all(isinstance(j, bool) for j in joins)):
        raise ParseError("diffusion_joins", "diffusion_joins must be a list of True/False", line)
    return SharingPlan(fo, list(ori), list(joins), gg, mode_label="llm:SharingPlan")
