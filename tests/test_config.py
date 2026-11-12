"""Consumer-visible config precedence and safe path boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

from canvas_export.config import load_plan, make_plan
from canvas_export.errors import ExportError


class ConfigTests(unittest.TestCase):
    def test_cli_overrides_figure_and_project(self):
        raw = {"style": "dark", "formats": ["svg"], "figures": {
            "diagram": {"file": "Drawings/A.excalidraw.md", "style": "light", "padding": 8},
        }}
        with tempfile.TemporaryDirectory() as directory:
            plan = make_plan(raw, Path(directory), {"style": "original", "formats": ["pdf", "pdf", "png"]})
            self.assertEqual(plan.figures["diagram"]["style"], "original")
            self.assertEqual(plan.figures["diagram"]["formats"], ["pdf", "png"])
            self.assertEqual(plan.figures["diagram"]["padding"], 8)
            self.assertEqual(plan.output_dir, Path(directory) / "output")

    def test_config_paths_are_not_shell_cwd_relative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "project.json"
            config.write_text(json.dumps({"output_dir": "results", "figures": {"a": {"file": "A.excalidraw.md"}}}))
            self.assertEqual(load_plan(config).output_dir, root / "results")

    def test_rejects_unknown_keys_and_unsafe_canvas_paths(self):
        for raw in [
            {"formtas": ["pdf"], "figures": {"a": {"file": "A.md"}}},
            {"figures": {"../escape": {"file": "A.md"}}},
            {"figures": {"a": {"file": "../A.md"}}},
            {"figures": {"a": {"file": "D:/Vault/A.md"}}},
            {"figures": {"a": {"file": "A.md", "scale": float("nan")}}},
            {"figures": {"a": {"file": "A.md", "padding": True}}},
            {"latest": "builds", "figures": {"a": {"file": "A.md"}}},
        ]:
            with self.subTest(raw=raw), self.assertRaises(ExportError):
                make_plan(raw, Path.cwd())

    def test_tex_inputs_cannot_replace_rendered_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.tex").write_text("document")
            raw = {"figures": {"a": {"file": "A.md", "macro": "AGraphic"}}, "latex": {
                "source": "paper.tex", "inputs": [{"source": "paper.tex", "target": "a.pdf"}],
            }}
            with self.assertRaisesRegex(ExportError, "collides"):
                make_plan(raw, root)

    def test_png_override_requires_no_latex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.tex").write_text("document")
            raw = {"figures": {"a": {"file": "A.md", "macro": "AGraphic"}}, "latex": {"source": "paper.tex"}}
            with self.assertRaisesRegex(ExportError, "requires pdf"):
                make_plan(raw, root, {"formats": ["png"]})
            plan = make_plan(raw, root, {"formats": ["png"], "no_latex": True})
            self.assertIsNone(plan.latex)
            self.assertEqual(plan.figures["a"]["formats"], ["png"])


if __name__ == "__main__":
    unittest.main()
