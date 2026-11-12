from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canvas_export.errors import ExportError
from canvas_export.profiles import discover_profiles, select_profile


class ProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def config(self, root=None, name="one", **changes):
        root = root or self.root
        settings = {
            "bridge_url": "http://127.0.0.1:27124",
            "bridge_token": "private-fixture-token",
            "host_id": "host-1", "host_name": "Host One",
            "vault_id": "vault-1", "vault_name": "Research",
            "host_vault_path": "D:\\Notes\\Research", "mode": "remote",
            "private_extension": {"password": "private-extension-secret"},
        }
        settings.update(changes)
        path = root / "connections" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path

    def test_discovery_and_public_metadata_never_expose_private_fields(self):
        self.config()
        profile, = discover_profiles([self.root])
        self.assertEqual(profile.id, "one")
        for text in (repr(profile), json.dumps(profile.summary())):
            self.assertNotIn("private-fixture-token", text)
            self.assertNotIn("private-extension-secret", text)
            self.assertNotIn("bridge_token", text)
            self.assertNotIn("private_extension", text)
        self.assertEqual(profile.summary()["vault_name"], "Research")
        self.assertEqual(select_profile([profile], vault="Research"), profile)
        self.assertEqual(select_profile([profile], vault="vault-1"), profile)
        self.assertEqual(select_profile([profile], vault="d:/notes/research"), profile)

    def test_unknown_vault_never_falls_back_to_single_connection(self):
        self.config()
        profiles = discover_profiles([self.root])
        with self.assertRaisesRegex(ExportError, "requested vault"):
            select_profile(profiles, vault="Not paired")
        with self.assertRaises(ExportError):
            select_profile(profiles, connection="missing")

    def test_ambiguous_vault_requires_explicit_connection(self):
        first = self.config()
        self.config(name="two", host_id="host-2", host_name="Host Two", bridge_url="http://127.0.0.1:27125")
        profiles = discover_profiles([self.root])
        with self.assertRaisesRegex(ExportError, "Multiple"):
            select_profile(profiles)
        with self.assertRaisesRegex(ExportError, "Multiple"):
            select_profile(profiles, vault="Research")
        self.assertEqual(select_profile(profiles, vault="Research", connection="two").host_id, "host-2")
        self.assertEqual(select_profile(profiles, connection=str(first)).id, "one")
        with self.assertRaises(ExportError):
            select_profile(profiles, vault="Different", connection="two")

    def test_pointer_uses_canonical_profile_not_stale_copied_credentials(self):
        canonical = self.config(name="selected", bridge_token="canonical-token")
        pointer = self.root / "connection.json"
        pointer.write_text(json.dumps({"connection_id": "selected", "bridge_url": "http://127.0.0.1:1",
                                       "bridge_token": "stale-token", "vault_name": "Wrong"}), encoding="utf-8")
        before = pointer.read_bytes(), canonical.read_bytes()
        profiles = discover_profiles([self.root])
        self.assertEqual(len(profiles), 1)
        selected = select_profile(profiles, vault="Research", connection=str(pointer))
        self.assertEqual(selected.id, "selected")
        self.assertEqual(selected.config_path, canonical)
        self.assertEqual(selected.settings["bridge_token"], "canonical-token")
        self.assertEqual((pointer.read_bytes(), canonical.read_bytes()), before)

    def test_broken_pointer_does_not_use_embedded_stale_credentials(self):
        pointer = self.root / "connection.json"
        pointer.write_text(json.dumps({"connection_id": "gone", "bridge_url": "http://127.0.0.1:1",
                                       "bridge_token": "stale-token"}), encoding="utf-8")
        self.config(name="other")
        with self.assertRaises(ExportError):
            select_profile(discover_profiles([self.root]), connection=str(pointer))
        self.assertEqual([p.id for p in discover_profiles([self.root])], ["other"])

    def test_pointer_cannot_escape_state_directory(self):
        pointer = self.root / "connection.json"
        pointer.write_text(json.dumps({"connection_id": "../../private"}), encoding="utf-8")
        with self.assertRaisesRegex(ExportError, "Invalid connection ID"):
            select_profile([], connection=str(pointer))

    def test_deduplicates_identity_but_not_different_endpoints(self):
        first = self.config()
        other_root = self.root / "second-state"
        self.config(root=other_root, name="duplicate")
        self.config(root=other_root, name="different", bridge_url="http://127.0.0.1:27125")
        profiles = discover_profiles([self.root, other_root, self.root])
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0].config_path, first)
        self.assertEqual({p.id for p in profiles}, {"one", "different"})

    def test_only_known_paired_locations_are_scanned(self):
        self.config()
        nested = self.root / "arbitrary-vault"
        self.config(root=nested, name="not-a-known-state-root", host_id="not-scanned")
        (self.root / "random.json").write_text("{}", encoding="utf-8")
        self.assertEqual([p.id for p in discover_profiles([self.root])], ["one"])

    def test_invalid_configs_are_skipped_and_explicit_selection_fails(self):
        self.config()
        invalid = self.config(name="untrusted", bridge_url="https://attacker.invalid")
        corrupt = self.root / "connections" / "corrupt.json"
        corrupt.write_text('{"bridge_token": "secret-on-broken-line",', encoding="utf-8")
        self.assertEqual([p.id for p in discover_profiles([self.root])], ["one"])
        for path in (invalid, corrupt):
            with self.subTest(path=path), self.assertRaises(ExportError) as caught:
                select_profile([], connection=str(path))
            self.assertNotIn("secret-on-broken-line", str(caught.exception))
            self.assertNotIn("private-fixture-token", str(caught.exception))

    def test_remote_credentials_and_unverifiable_identity_are_rejected(self):
        for number, changes in enumerate((
            {"bridge_url": "http://public.example:27124"},
            {"bridge_url": "http://user:password@127.0.0.1:27124"},
            {"bridge_url": "http://127.0.0.1:27124/?token=secret"},
            {"bridge_token": "bad\r\nheader"},
            {"host_id": "", "vault_id": "", "host_name": ""},
        )):
            with self.subTest(changes=changes):
                path = self.config(name=f"invalid-{number}", **changes)
                with self.assertRaises(ExportError):
                    select_profile([], connection=str(path))

    def test_default_roots_include_override_platform_and_remote_state(self):
        home = self.root / "home"
        override = self.root / "override"
        xdg = self.root / "xdg"
        self.config(root=override, name="override", host_id="override")
        self.config(root=xdg / "obsidian-excalidraw-agent", name="local", host_id="local")
        self.config(root=home / ".local/share/obsidian-excalidraw-agent-remote/state", name="remote", host_id="remote")
        with patch("canvas_export.profiles.Path.home", return_value=home), \
                patch("canvas_export.profiles.sys.platform", "linux"), \
                patch.dict(os.environ, {"EXCALIDRAW_AGENT_STATE_DIR": str(override), "XDG_DATA_HOME": str(xdg)}):
            self.assertEqual([p.id for p in discover_profiles()], ["override", "local", "remote"])


if __name__ == "__main__":
    unittest.main()
