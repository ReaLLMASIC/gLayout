from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class PortTreeTests(unittest.TestCase):
    def test_print_writes_the_port_hierarchy(self) -> None:
        from glayout.backend import Component
        from glayout.util.port_utils import PortTree

        component = Component("demo")
        component.add_port(
            name="device_gate_N",
            center=(0, 0),
            width=1,
            orientation=90,
            layer=(1, 0),
        )

        with TemporaryDirectory() as directory:
            output = Path(directory) / "ports.txt"
            PortTree(component).print(savetofile=True, outfile_name=str(output))

            self.assertTrue(output.is_file())
            text = output.read_text()
            self.assertIn("demo", text)
            self.assertIn("device", text)
            self.assertIn("gate", text)
            self.assertIn("N", text)


if __name__ == "__main__":
    unittest.main()
