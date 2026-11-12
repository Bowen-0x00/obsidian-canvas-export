from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from canvas_export.bridge import NativeBridge
from canvas_export.errors import ExportError
from canvas_export.profiles import Profile


def png_document(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00\x00\x00\xff" * width) * height))
            + chunk(b"IEND", b""))


def pdf_document():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 120 80] /Contents 4 0 R >>",
        b"<< /Length 20 >>\nstream\n0 0 100 60 re S\n0 g\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 5\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data


class BridgeFixture:
    """A real loopback HTTP server, with independent scene and binary artifacts."""
    def __init__(self):
        self.calls = []
        self.failures = []
        self.page_size = 2
        self.query_mutator = None
        self.export_mutator = None
        self.status_mutator = None
        self.summary_revision = "rev-1"
        self.actual_scale = 2
        self.error_route = None
        self.redirect_route = None
        self.source = [
            {"id": "a", "type": "rectangle", "x": -15.125, "y": 12.75,
             "width": 100.0, "height": 60.0, "angle": 0, "strokeColor": "#202020",
             "version": 12, "isDeleted": False,
             "customData": {"agentDiagram": {"logicalId": "panel-a"}}},
            {"id": "b", "type": "line", "points": [[0, 0], [20.125, 15.6]], "version": 2},
            {"id": "c", "type": "text", "text": "Native title α", "fontFamily": 5, "fontSize": 19.75},
            {"id": "d", "type": "image", "fileId": "native-image"},
            {"id": "deleted", "type": "rectangle", "isDeleted": True},
        ]
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request("GET")

            def do_POST(self):
                self.handle_request("POST")

            def handle_request(self, method):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body) if body else None
                fixture.calls.append((method, self.path, payload, dict(self.headers)))
                allowed = {
                    ("GET", "/v3/status"), ("POST", "/v3/canvases/bind"),
                    ("POST", "/v3/elements/query"), ("POST", "/v3/elements/summary"),
                    ("POST", "/v3/export"), ("POST", "/v3/render"),
                }
                if (method, self.path) not in allowed:
                    fixture.failures.append("Unexpected route: " + self.path)
                    self.send_error(405)
                    return
                if self.headers.get("Authorization") != "Bearer fixture-private-bearer":
                    fixture.failures.append("Missing paired bearer authentication")
                if self.path != "/v3/status":
                    if self.headers.get("X-Excalidraw-Host-Id") != "host-1" or self.headers.get("X-Excalidraw-Vault-Id") != "vault-1":
                        fixture.failures.append("Missing target identity headers")
                if fixture.redirect_route == self.path:
                    self.send_response(302)
                    self.send_header("Location", fixture.url + "/credential-leak")
                    self.end_headers()
                    return
                if fixture.error_route == self.path:
                    self.reply({"ok": False, "error": {"code": "PDF_EXPORT_UNAVAILABLE",
                               "message": "fixture-private-bearer", "details": {"contextToken": "private-context"}}}, status=409)
                    return
                if self.path == "/v3/status":
                    response = {
                        "ok": True, "host": {"id": "host-1", "name": "Fixture Host", "platform": "win32"},
                        "vault": {"id": "vault-1", "name": "Fixture Vault", "path": "D:\\Notes\\Fixture"},
                        "bridge_token": "fixture-private-bearer", "contextToken": "private-context",
                    }
                    if fixture.status_mutator:
                        fixture.status_mutator(response)
                elif self.path == "/v3/canvases/bind":
                    response = {"file": "Diagrams/example.excalidraw.md", "revision": "rev-1", "contextToken": "private-context"}
                elif self.path == "/v3/elements/summary":
                    response = {"file": "Diagrams/example.excalidraw.md", "revision": fixture.summary_revision}
                elif self.path == "/v3/elements/query":
                    if payload.get("detail") != "full" or payload.get("filter") != {"includeDeleted": True}:
                        fixture.failures.append("Full native elements including deleted records were not requested")
                    if payload.get("limit") != 2000 or payload.get("contextToken") != "private-context":
                        fixture.failures.append("Invalid query binding or page size")
                    offset = payload["offset"]
                    limit = min(payload["limit"], fixture.page_size)
                    page = deepcopy(fixture.source[offset:offset + limit])
                    response = {"file": "Diagrams/example.excalidraw.md", "revision": "rev-1", "total": len(fixture.source),
                                "offset": offset, "truncated": offset + len(page) < len(fixture.source), "elements": page}
                    if fixture.query_mutator:
                        fixture.query_mutator(response, payload)
                else:
                    padding = payload["padding"]
                    width, height = 100 + 2 * padding, 60 + 2 * padding
                    format = "png" if self.path == "/v3/render" else payload["format"]
                    response = {
                        "file": "Diagrams/example.excalidraw.md", "revision": "rev-1", "complete": True,
                        "width": width, "height": height, "bounds": {"x": -15.125, "y": 12.75, "width": 100, "height": 60},
                        "resourceIssues": [], "contextToken": "private-context", "bridge_token": "fixture-private-bearer",
                        "canvasSummary": {"private": "fixture-private-bearer"},
                        "export": {"renderer": "ea.createPNG" if format == "png" else "ea.createSVG",
                                   "scope": "all", "theme": payload.get("theme", "light"),
                                   "rasterImages": 1, "embeddedSvgImages": 0,
                                   "secret": "fixture-private-bearer", "contextToken": "private-context"},
                    }
                    if format == "png":
                        image_width, image_height = round(width * fixture.actual_scale), round(height * fixture.actual_scale)
                        content = png_document(image_width, image_height)
                        response.update(width=image_width, height=image_height, actualScale=fixture.actual_scale)
                        key, mime = "image", "image/png"
                    elif format == "pdf":
                        content = pdf_document()
                        key, mime = "artifact", "application/pdf"
                    else:
                        pixel = base64.b64encode(png_document(1, 1)).decode()
                        content = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
                                   f'<rect x="0" y="0" width="100" height="60"/>'
                                   f'<image href="data:image/png;base64,{pixel}" width="1" height="1"/></svg>').encode()
                        key, mime = "artifact", "image/svg+xml"
                    response[key] = {"base64": base64.b64encode(content).decode(), "mimeType": mime}
                    if fixture.export_mutator:
                        fixture.export_mutator(response, payload)
                self.reply(response)

            def reply(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = BridgeFixture()
        self.addCleanup(self.fixture.close)
        self.profile = Profile("fixture", "Fixture Vault", "vault-1", "Fixture Host", "host-1",
                               self.root / "private.json", {
                                   "bridge_url": self.fixture.url, "bridge_token": "fixture-private-bearer",
                                   "host_vault_path": "d:/notes/fixture",
                               })
        self.bridge = NativeBridge(self.profile, timeout=5)

    def tearDown(self):
        self.assertEqual(self.fixture.failures, [])

    def scene(self):
        return self.bridge.read("Diagrams/example.excalidraw.md")

    def test_http_full_scene_pagination_preserves_exact_native_data(self):
        scene = self.scene()
        self.assertEqual(scene["elements"], self.fixture.source)
        self.assertEqual(scene["revision"], "rev-1")
        pages = [payload for method, path, payload, headers in self.fixture.calls if path == "/v3/elements/query"]
        self.assertEqual([page["offset"] for page in pages], [0, 2, 4])
        self.assertEqual(scene["elements"][0]["x"], -15.125)
        self.assertEqual(scene["elements"][0]["customData"]["agentDiagram"]["logicalId"], "panel-a")

    def test_native_artifacts_decode_end_to_end_and_public_metadata_is_redacted(self):
        scene = self.scene()
        for format in ("png", "svg", "pdf"):
            with self.subTest(format=format):
                output = self.root / f"staged.{format}"
                metadata = self.bridge.export(scene, format, "dark", 10, 2, output)
                content = output.read_bytes()
                self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(metadata["bytes"], len(content))
                self.assertEqual(metadata["width"], 120)
                self.assertEqual(metadata["height"], 80)
                self.assertEqual(metadata["bounds"], {"x": -15.125, "y": 12.75, "width": 100, "height": 60})
                self.assertEqual(metadata["theme"], "dark")
                public = json.dumps(metadata)
                for private in ("fixture-private-bearer", "private-context", "contextToken", "base64", "canvasSummary", "bridge_token"):
                    self.assertNotIn(private, public)
                if format == "png":
                    self.assertEqual(content, png_document(240, 160))
                    self.assertEqual((metadata["pixel_width"], metadata["pixel_height"]), (240, 160))
                    self.assertEqual(metadata["actual_scale"], 2)
                elif format == "pdf":
                    self.assertEqual(content, pdf_document())
                else:
                    self.assertTrue(content.startswith(b"<svg"))
                    self.assertEqual(metadata["raster_images"], 1)
                    self.assertIn("No all-vector guarantee", metadata["vector_notice"])
        exports = [(route, payload) for method, route, payload, headers in self.fixture.calls if route in {"/v3/render", "/v3/export"}]
        self.assertEqual([route for route, payload in exports], ["/v3/render", "/v3/export", "/v3/export"])
        for route, payload in exports:
            self.assertEqual(payload["theme"], "dark")
            self.assertEqual(payload["scope"], "all")
            self.assertEqual(payload["baseRevision"], "rev-1")
            self.assertTrue(payload["embedFonts"])
            self.assertTrue(payload["withBackground"])
            self.assertNotIn("elements", payload)
            self.assertNotIn("operations", payload)


    def test_status_is_redacted_and_mismatched_vault_fails_before_bind(self):
        status = self.bridge.status()
        self.assertEqual(status["vault"]["id"], "vault-1")
        self.assertNotIn("fixture-private-bearer", json.dumps(status))
        self.fixture.calls.clear()
        self.fixture.status_mutator = lambda response: response["vault"].update(id="wrong-vault")
        with self.assertRaisesRegex(ExportError, "identity"):
            self.scene()
        self.assertEqual([route for method, route, payload, headers in self.fixture.calls], ["/v3/status"])

    def test_identity_rejects_wrong_host_path_name_and_missing_ids(self):
        mutations = [
            lambda response: response["host"].update(id="wrong-host"),
            lambda response: response["vault"].update(path="D:\\Notes\\Other"),
            lambda response: response["vault"].update(name="Wrong Vault"),
            lambda response: response["vault"].pop("id"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.fixture.status_mutator = mutate
                with self.assertRaises(ExportError):
                    self.bridge.status()

    def test_legacy_identity_requires_matching_host_name_vault_name_and_path(self):
        profile = Profile("legacy", "Fixture Vault", "", "Fixture Host", "",
                          self.profile.config_path, dict(self.profile.settings))
        bridge = NativeBridge(profile)
        self.assertEqual(bridge.status()["vault"]["path"], "D:\\Notes\\Fixture")
        self.fixture.status_mutator = lambda response: response["host"].update(name="Other Host")
        with self.assertRaises(ExportError):
            bridge.status()
        profile = Profile("unverifiable", "", "", "", "",
                          self.profile.config_path, dict(self.profile.settings))
        with self.assertRaisesRegex(ExportError, "verifiable"):
            NativeBridge(profile).status()

    def test_concurrent_revision_change_during_pagination_fails_closed(self):
        def mutate(response, payload):
            if payload["offset"]:
                response["revision"] = "rev-2"
        self.fixture.query_mutator = mutate
        with self.assertRaisesRegex(ExportError, "pagination"):
            self.scene()
        self.assertFalse(list(self.root.glob("*.png")))

    def test_truncated_duplicate_and_changed_total_pages_fail_closed(self):
        mutations = [
            lambda response, payload: response.update(truncated=False),
            lambda response, payload: response.update(total=len(self.fixture.source) + payload["offset"]),
            lambda response, payload: response.update(elements=[]) if payload["offset"] else None,
            lambda response, payload: response["elements"][0].update(id="a") if payload["offset"] else None,
            lambda response, payload: response.pop("revision"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.fixture.query_mutator = mutate
                with self.assertRaises(ExportError):
                    self.scene()

    def test_revision_changed_after_read_is_reported(self):
        scene = self.scene()
        self.fixture.summary_revision = "rev-2"
        with self.assertRaisesRegex(ExportError, "changed"):
            self.bridge.assert_unchanged(scene)

    def test_incomplete_stale_wrong_file_or_missing_identity_exports_never_write(self):
        scene = self.scene()
        mutations = [
            lambda response, payload: response.update(complete=False),
            lambda response, payload: response.pop("complete"),
            lambda response, payload: response.pop("revision"),
            lambda response, payload: response.update(revision="rev-2"),
            lambda response, payload: response.update(file="Other.excalidraw.md"),
            lambda response, payload: response["export"].update(scope="selection"),
            lambda response, payload: response["export"].update(theme="light"),
            lambda response, payload: response.update(bounds={"x": 0, "y": 0, "width": 0, "height": 1}),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                self.fixture.export_mutator = mutate
                target = self.root / f"invalid-{number}.svg"
                with self.assertRaises(ExportError):
                    self.bridge.export(scene, "svg", "dark", 10, 2, target)
                self.assertFalse(target.exists())

    def test_invalid_mime_base64_or_document_format_never_write(self):
        scene = self.scene()
        cases = [
            ("png", "image", {"mimeType": "image/svg+xml"}),
            ("png", "image", {"base64": "not base64!"}),
            ("png", "image", {"base64": base64.b64encode(b"<svg/>").decode()}),
            ("svg", "artifact", {"base64": base64.b64encode(b"<html/>").decode()}),
            ("svg", "artifact", {"base64": base64.b64encode(b"<svg>").decode()}),
            ("svg", "artifact", {"base64": base64.b64encode(b'<!DOCTYPE svg [<!ENTITY x "bad">]><svg>&x;</svg>').decode()}),
            ("pdf", "artifact", {"base64": base64.b64encode(b"%PDF-1.4\ntruncated").decode()}),
            ("pdf", "artifact", {"base64": base64.b64encode(b"not-pdf\n%%EOF\n").decode()}),
        ]
        for number, (format, key, changes) in enumerate(cases):
            with self.subTest(number=number):
                self.fixture.export_mutator = lambda response, payload, key=key, changes=changes: response[key].update(changes)
                target = self.root / f"invalid-document-{number}.{format}"
                with self.assertRaises(ExportError):
                    self.bridge.export(scene, format, "original", 10, 2, target)
                self.assertFalse(target.exists())

    def test_png_capped_scale_is_disclosed_not_claimed_requested_resolution(self):
        scene = self.scene()
        self.fixture.actual_scale = 0.5
        metadata = self.bridge.export(scene, "png", "original", 10, 4, self.root / "limited.png")
        self.assertEqual(metadata["actual_scale"], 0.5)
        self.assertEqual(metadata["requested_scale"], 4)
        self.assertTrue(metadata["scale_limited"])
        self.assertEqual((metadata["pixel_width"], metadata["pixel_height"]), (60, 40))
        self.assertEqual(metadata["raster_limits"], {"longest_side_pixels": 1600, "total_pixels": 4000000})

    def test_revision_change_while_resources_resolve_leaves_no_staged_artifact(self):
        scene = self.scene()
        def mutate(response, payload):
            self.fixture.summary_revision = "rev-2"
        self.fixture.export_mutator = mutate
        target = self.root / "stale.svg"
        with self.assertRaisesRegex(ExportError, "changed"):
            self.bridge.export(scene, "svg", "original", 10, 2, target)
        self.assertFalse(target.exists())

    def test_existing_destination_is_not_overwritten(self):
        scene = self.scene()
        target = self.root / "existing.svg"
        target.write_bytes(b"user-file")
        with self.assertRaisesRegex(ExportError, "new staged"):
            self.bridge.export(scene, "svg", "original", 10, 2, target)
        self.assertEqual(target.read_bytes(), b"user-file")

    def test_invalid_format_style_scale_and_padding_fail_before_native_export(self):
        scene = self.scene()
        self.fixture.calls.clear()
        for format, style, padding, scale in (("jpeg", "original", 10, 2), ("svg", "rewrite-fonts", 10, 2),
                                               ("svg", "original", -1, 2), ("png", "original", 10, 0),
                                               ("png", "original", 10, float("nan")), ("png", "original", True, 2)):
            with self.subTest(format=format, style=style, padding=padding, scale=scale), self.assertRaises(ExportError):
                self.bridge.export(scene, format, style, padding, scale, self.root / "invalid")
        self.assertEqual(self.fixture.calls, [])

    def test_no_proxy_or_redirect_leaks_private_bearer(self):
        with patch.dict("os.environ", {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            bridge = NativeBridge(self.profile)
            bridge.status()
        self.fixture.redirect_route = "/v3/status"
        with self.assertRaises(ExportError) as caught:
            bridge.status()
        self.assertNotIn("fixture-private-bearer", str(caught.exception))
        self.assertFalse(any(route == "/credential-leak" for method, route, payload, headers in self.fixture.calls))

    def test_http_errors_are_actionable_without_echoing_private_payloads(self):
        scene = self.scene()
        self.fixture.error_route = "/v3/export"
        with self.assertRaisesRegex(ExportError, "Excalidraw Extras PDF") as caught:
            self.bridge.export(scene, "pdf", "original", 10, 2, self.root / "missing.pdf")
        self.assertNotIn("fixture-private-bearer", str(caught.exception))
        self.assertNotIn("private-context", str(caught.exception))
        self.assertFalse((self.root / "missing.pdf").exists())

    def test_mutating_route_is_unreachable_even_through_internal_request(self):
        with self.assertRaisesRegex(ExportError, "read-only"):
            self.bridge._request("POST", "/v3/operations/apply", {"operations": []})
        self.assertEqual(self.fixture.calls, [])

    def test_absolute_and_traversing_canvas_paths_fail_before_network(self):
        for path in ("/absolute.excalidraw.md", "../outside.md", "D:\\Notes\\example.md", "D:/Notes/example.md", ""):
            with self.subTest(path=path), self.assertRaises(ExportError):
                self.bridge.read(path)
        self.assertEqual(self.fixture.calls, [])


if __name__ == "__main__":
    unittest.main()
