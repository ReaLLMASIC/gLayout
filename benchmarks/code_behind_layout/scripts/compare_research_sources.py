"""Report source overlap and actual dependencies; no similarity admission score."""
import ast
from difflib import SequenceMatcher
from itertools import combinations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["five_t", "compact_miller", "cascode_mirror", "source_follower",
         "stacked_switch", "common_source_stage", "resistive_diff", "validation_mirror"]


def features(path):
    tree = ast.parse(path.read_text())
    imports = sorted({node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} |
                     {name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names})
    tokens = []
    for node in ast.walk(tree):
        tokens.append(type(node).__name__)
        if isinstance(node, ast.Name):
            tokens.append(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.append(node.attr)
        elif isinstance(node, ast.Constant):
            tokens.append("NUMBER" if isinstance(node.value, (int, float)) else repr(node.value))
    return {"imports": imports,
            "target_assembly_imports": [name for name in imports if name.startswith(("glayout.cells", "glayout.blocks", "textbook_sharing", "glayout.sharing"))],
            "frozen_terminal_access_helper": "src.generators.terminal_access" in imports}, tokens


if __name__ == "__main__":
    records = {}
    sequences = {}
    for name in FILES:
        path = Path("src/generators") / (name + ".py")
        records[str(path)], sequences[str(path)] = features(ROOT / path)
    result = {"scope": "source_review_not_formal_task_or_split_admission", "source_files": records,
        "comparisons": [{"left": left, "right": right,
                         "numeric_neutral_AST_token_similarity": SequenceMatcher(None, sequences[left], sequences[right], autojunk=False).ratio()}
                        for left, right in combinations(records, 2)],
        "shared_library": "PDK, MOS/via/MIM and basic drawing/terminal escape may be frozen shared dependencies. terminal_access contains no circuit graph or placement/routing policy.",
        "assembly_review": {
            "five_t": "Row-based input, mirror and tail groups with explicit orthogonal net buses.",
            "compact_miller": "Separated input/mirror/second-stage/MIM blocks and local collectors.",
            "cascode_mirror": "Three columns, two stack levels, separate diode-bias stack and spine/rail routing.",
            "source_follower": "L-shaped signal and bias devices, right output collector, lower bias crossbar and ground floor.",
            "stacked_switch": "Vertical complementary switch pair with continuous signal columns and control escapes at opposite ends.",
            "common_source_stage": "Triangular reference/load/signal groups, short right output spine and separate upper bias track.",
            "resistive_diff": "Separated upper input branches and lower tail/reference devices with distinct outer M5 collectors.",
            "validation_mirror": "Explicit three-net mirror; validation only."},
        "interpretation": "These high-level assemblies do not call each other or the public train compiler. The vendor elementary targets and OTAs remain one connected circuit-specific dependency cluster. Similarity is descriptive, not a statistical proof of independence; analysis must retain the disclosed common-access library sensitivity."}
    destination = ROOT / "results/derived/research_source_comparison.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"source_files": len(records), "pairs": len(result["comparisons"]), "output": str(destination)}))
