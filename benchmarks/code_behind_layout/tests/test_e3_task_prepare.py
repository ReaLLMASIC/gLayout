import ast
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from src.e3_task_prepare import TARGETS, EDITABLE, DEFAULTS, INITIALS, compact_pdk, generator_wrapper, objective, render_parameters
from scripts.e3_task_prepare import capsule
from src.candidate_executor import apply_source_patch

ROOT = Path(__file__).resolve().parents[1]


class EditingPreparationTests(unittest.TestCase):
    def test_readonly_frozen_capsule_allows_real_patch_only_in_working_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);pack = root/'frozen';module = pack/'nested/layout.py'
            module.parent.mkdir(parents=True);module.write_text('spacing = 1\n')
            (pack/'generator.py').write_text('# complete generator fixture\n')
            original = module.read_bytes();wrapper = root/'wrapper.py';wrapper.write_text('# exact wrapper\n')
            initial = root/'initial.py';initial.write_bytes(original)
            task = {'task_id': 'software_fixture', 'source_pack_base': str(pack),
                'source_files': ['generator.py', 'nested/layout.py'], 'entrypoint': 'generator.py',
                'editable_paths': ['nested/layout.py'], 'source_overrides': {'nested/layout.py': str(initial)},
                'frozen_source_overrides': {'generator.py': str(wrapper)}}
            task_file = root/'task.json';task_file.write_text(json.dumps(task))
            for filename in pack.rglob('*'):
                filename.chmod(0o555 if filename.is_dir() else 0o444)
            pack.chmod(0o555)
            try:
                working = root/'working';capsule(task_file, working)
                apply_source_patch(working, '--- a/nested/layout.py\n+++ b/nested/layout.py\n@@ -1 +1 @@\n-spacing = 1\n+spacing = 2\n', ['nested/layout.py'])
                self.assertEqual((working/'nested/layout.py').read_text(), 'spacing = 2\n')
                self.assertEqual(module.read_bytes(), original)
                self.assertEqual(pack.stat().st_mode & 0o777, 0o555)
                self.assertEqual(module.parent.stat().st_mode & 0o777, 0o555)
                self.assertEqual(module.stat().st_mode & 0o777, 0o444)
                self.assertTrue((working/'nested').stat().st_mode & 0o200)
            finally:
                pack.chmod(0o755);module.parent.chmod(0o755)

    def test_complete_modules_distinct_and_device_calls_unchanged(self):
        for target in TARGETS[1:]:
            before = (ROOT/EDITABLE[target]).read_text()
            def device_calls(text):
                return [ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(text))
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("nmos", "pmos", "mimcap")]
            generated = [render_parameters(target, before, controls) for controls in INITIALS[target]]
            self.assertEqual(generated[0], before)
            self.assertEqual(len(set(generated)), 3)
            for source in generated:
                self.assertEqual(device_calls(source), device_calls(before))

    def test_mirror_sites_and_undeclared_parameters(self):
        text = "a=route(extension=3*maxmet_sep)\nb=route(extension=3*maxmet_sep)\n"
        self.assertEqual(render_parameters("mirror", text, DEFAULTS["mirror"]), text)
        self.assertEqual(render_parameters("mirror", text, {"route_extension_multiplier": 7}).count("7*maxmet_sep"), 2)
        with self.assertRaises(ValueError):
            render_parameters("mirror", text, {"route_extension_multiplier": 99})

    def test_every_rule_roundtrips(self):
        original = {"layers": {"met1": [68, 20]}, "rules": {
            "met1": {"met1": {"min_width": .14, "min_separation": .14},
                     "via1": {"min_enclosure": .055}},
            "via1": {"via1": {"min_width": .15}}}, "units": "um"}
        encoded = compact_pdk(original)
        reconstructed = {}
        for field, rows in encoded["rules"].items():
            for row in rows.splitlines():
                first, second, value = row.split(" ", 2)
                reconstructed.setdefault(first, {}).setdefault(second, {})[field] = json.loads(value)
        self.assertEqual(reconstructed, original["rules"])
        self.assertEqual(encoded["layers"], original["layers"])

    def test_capsule_overrides_only_complete_editable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);base = root/"base";base.mkdir()
            (base/"layout.py").write_text("old = 1\n")
            (base/"generator.py").write_text("from layout import old\n")
            replacement = root/"new.py";replacement.write_text("old = 2\n")
            task = root/"task.json";task.write_text(json.dumps({"task_id": "x", "source_pack_base": str(base),
                "source_files": ["generator.py", "layout.py"], "source_overrides": {"layout.py": str(replacement)},
                "editable_paths": ["layout.py"], "entrypoint": "generator.py"}))
            result = capsule(task, root/"output")
            self.assertEqual((root/"output/layout.py").read_text(), "old = 2\n")
            self.assertEqual((root/"output/generator.py").read_bytes(), (base/"generator.py").read_bytes())
            self.assertEqual(result["editable_paths"], ["layout.py"])

    def test_prospective_objectives(self):
        self.assertEqual(objective("mirror")["metric"], "area")
        self.assertEqual(objective("five_t")["unit"], "Hz/um2")

    def test_export_transport_unwraps_and_contains_auxiliary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);out = root/"output";out.mkdir()
            (root/"generator.py").write_text(generator_wrapper("mirror"))
            (root/"component_build.py").write_text('def build(parameters,output):\n'
                '    assert parameters == {"width": 3}\n'
                '    (output.parent/"auxiliary.json").write_text("aux")\n'
                '    output.write_bytes(b"transport fixture")\n')
            config = root/"configuration.json";config.write_text(json.dumps({"parameters": {"width": 3}}))
            subprocess.run([sys.executable, str(root/"generator.py"), "--configuration", str(config),
                "--output", str(out/"candidate.gds")], check=True)
            self.assertEqual([p.name for p in out.iterdir()], ["candidate.gds"])
            self.assertEqual((out/"candidate.gds").read_bytes(), b"transport fixture")


if __name__ == "__main__":
    unittest.main()
