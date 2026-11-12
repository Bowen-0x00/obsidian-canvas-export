"""Atomic publication boundaries exercised through a real local HTTP Bridge."""
import json
from pathlib import Path
import tempfile
import unittest

from canvas_export.config import make_plan
from canvas_export.engine import run
from canvas_export.errors import ExportError
from canvas_export.profiles import Profile
from test_bridge import BridgeFixture


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BridgeFixture()
        self.addCleanup(self.fixture.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.profile = Profile("fixture", "Fixture Vault", "vault-1", "Fixture Host", "host-1",
                               self.root / "connection.json", {
                                   "bridge_url": self.fixture.url,
                                   "bridge_token": "fixture-private-bearer",
                                   "host_vault_path": "D:\\Notes\\Fixture",
                               })
        self.plan = make_plan({"output_dir": "exports", "figures": {
            "example": {"file": "Diagrams/example.excalidraw.md", "formats": ["pdf", "png"]},
        }}, self.root)

    def test_success_and_failed_next_run_preserve_published_success(self):
        first = run(self.plan, self.profile)
        latest = self.root / "exports/latest"
        self.assertTrue(latest.is_symlink())
        self.assertEqual(latest.resolve(), Path(first["run_dir"]))
        original = (latest / "example.pdf").read_bytes()
        manifest = json.loads((latest / "build_manifest.json").read_text())
        self.assertEqual(manifest["status"], "exported_not_independently_reviewed")
        self.assertNotIn("fixture-private-bearer", (latest / "build_manifest.json").read_text())
        self.fixture.error_route = "/v3/render"
        with self.assertRaises(ExportError):
            run(self.plan, self.profile)
        self.assertEqual(latest.resolve(), Path(first["run_dir"]))
        self.assertEqual((latest / "example.pdf").read_bytes(), original)
        failed = list((self.root / "exports/builds").glob(".pending-*"))
        self.assertEqual(len(failed), 1)
        self.assertTrue((failed[0] / "example.pdf").is_file())
        self.assertFalse((failed[0] / "build_manifest.json").exists())

    def test_edit_during_export_never_publishes_mixed_revision(self):
        self.fixture.export_mutator = lambda response, payload: setattr(self.fixture, "summary_revision", "rev-2")
        with self.assertRaisesRegex(ExportError, "Canvas changed"):
            run(self.plan, self.profile)
        self.assertFalse((self.root / "exports/latest").exists())
        self.assertFalse(list((self.root / "exports/builds").glob("*/build_manifest.json")))

    def test_real_latest_directory_is_not_replaced(self):
        latest = self.root / "exports/latest"
        latest.mkdir(parents=True)
        marker = latest / "manual-work.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ExportError, "Refusing"):
            run(self.plan, self.profile)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(self.fixture.calls, [])


if __name__ == "__main__":
    unittest.main()
