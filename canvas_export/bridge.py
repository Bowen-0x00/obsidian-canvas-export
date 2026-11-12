"""Small, read-only client for the paired native Excalidraw Bridge HTTP API.

Only bind/read/render routes are reachable here. Theme overrides belong to the
native transient export workbench, never to canvas elements or app settings.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
from urllib import error, request
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .errors import ExportError
from .profiles import Profile, path_identity


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, never forward the paired bearer credential to another URL.
        return None


_ALLOWED = {
    ("GET", "/v3/status"),
    ("POST", "/v3/canvases/bind"),
    ("POST", "/v3/elements/query"),
    ("POST", "/v3/elements/summary"),
    ("POST", "/v3/export"),
    ("POST", "/v3/render"),
}
_ERRORS = {
    "PDF_EXPORT_UNAVAILABLE": "Enable and authorize Excalidraw Extras PDF on the host before exporting PDF; no host setting was changed",
    "SVG_EXPORT_UNAVAILABLE": "The paired native Bridge does not expose SVG export",
    "REVISION_CONFLICT": "Canvas changed during reading or exporting; no final artifact can be published",
    "INCOMPLETE_EXPORT": "Native export has incomplete resources",
    "NO_ELEMENTS_TO_RENDER": "The requested canvas has no active elements to render",
    "IDENTITY_MISMATCH": "The responding Bridge does not match the paired host and vault",
    "AUTH_MISSING": "Paired Bridge authentication is missing",
    "UNAUTHORIZED": "Paired Bridge authentication was rejected",
    "FORBIDDEN": "Paired Bridge authentication was rejected",
    "CONTEXT_NOT_FOUND": "The native canvas binding is no longer available",
}
_VECTOR_NOTICE = (
    "Native shapes and paths remain vector in SVG/PDF; images, captured HTML and "
    "some effects may contain raster content. No all-vector guarantee."
)


def _number(value, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExportError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ExportError(f"{name} must be {'positive' if positive else 'non-negative'}")
    return float(value)


def _signed_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExportError(f"Native {name} must be a finite number")
    return float(value)


def _revision(result: dict) -> str:
    revision = result.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ExportError("Native Bridge omitted the canvas revision")
    return revision


def _file(result: dict) -> str:
    file = result.get("file")
    if not isinstance(file, str) or not file:
        raise ExportError("Native Bridge omitted the canvas file identity")
    return file


def _native_error(result: dict, http_status: int | None = None) -> ExportError:
    details = result.get("error")
    code = details.get("code") if isinstance(details, dict) else None
    message = _ERRORS.get(code, "Native Bridge request failed") if isinstance(code, str) else "Native Bridge request failed"
    if http_status is not None:
        message += f" (HTTP {http_status})"
    # Deliberately omit arbitrary native messages/details: they may contain URLs,
    # private configuration, image data, context tokens, or bearer credentials.
    return ExportError(message)


class NativeBridge:
    def __init__(self, profile: Profile, timeout: float = 180):
        self.profile = profile
        self.timeout = _number(timeout, "timeout", positive=True)
        self._url = profile.settings.get("bridge_url", "").rstrip("/")
        self._token = profile.settings.get("bridge_token", "")
        try:
            parsed = urlsplit(self._url)
            port = parsed.port
        except ValueError:
            raise ExportError("Paired Bridge URL is invalid") from None
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path or port == 0):
            raise ExportError("Paired Bridge URL must be an HTTP loopback address")
        if not isinstance(self._token, str) or not self._token or any(ord(char) < 32 or ord(char) == 127 for char in self._token):
            raise ExportError("A valid paired Bridge credential is required")
        # Explicit proxy disabling is essential for forwarded loopback Bridges.
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        if (method, route) not in _ALLOWED:
            raise ExportError("Only read-only native Bridge routes are allowed")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if route != "/v3/status":
            for value, header in ((self.profile.host_id, "X-Excalidraw-Host-Id"),
                                  (self.profile.vault_id, "X-Excalidraw-Vault-Id")):
                if value:
                    headers[header] = value
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(self._url + route, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                try:
                    result = json.loads(exc.read().decode("utf-8"))
                except (ValueError, UnicodeError, OSError):
                    result = {}
            finally:
                exc.close()
            raise _native_error(result if isinstance(result, dict) else {}, exc.code) from None
        except (error.URLError, OSError, TimeoutError):
            raise ExportError("Cannot reach the selected paired Bridge; check its local forwarding and host connection") from None
        except (ValueError, UnicodeError):
            raise ExportError("Native Bridge returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ExportError("Native Bridge response must be a JSON object")
        if result.get("ok") is False:
            raise _native_error(result)
        return result

    def status(self) -> dict:
        result = self._request("GET", "/v3/status")
        host = result.get("host")
        vault = result.get("vault")
        if not isinstance(host, dict) or not isinstance(vault, dict):
            raise ExportError("Native Bridge omitted the responding host/vault identity")
        expected_path = self.profile.settings.get("host_vault_path") or self.profile.settings.get("vault_path")
        has_ids = bool(self.profile.host_id and self.profile.vault_id)
        has_fallback = bool(self.profile.host_name and self.profile.vault_name and expected_path)
        if not has_ids and not has_fallback:
            raise ExportError("Paired connection lacks a verifiable host/vault identity")
        for expected, actual in ((self.profile.host_id, host.get("id")),
                                 (self.profile.vault_id, vault.get("id")),
                                 (self.profile.host_name, host.get("name")),
                                 (self.profile.vault_name, vault.get("name"))):
            if expected and expected != actual:
                raise ExportError("Responding Bridge host/vault identity does not match the selected paired connection")
        if expected_path and (not isinstance(vault.get("path"), str)
                              or path_identity(expected_path) != path_identity(vault["path"])):
            raise ExportError("Responding Bridge vault path does not match the selected paired connection")
        return {
            "host": {key: host[key] for key in ("id", "name", "platform") if isinstance(host.get(key), str)},
            "vault": {key: vault[key] for key in ("id", "name", "path") if isinstance(vault.get(key), str)},
        }

    def read(self, file_path: str) -> dict:
        if (not isinstance(file_path, str) or not file_path or "\x00" in file_path
                or "\\" in file_path or PurePosixPath(file_path).is_absolute()
                or ".." in PurePosixPath(file_path).parts or re.match(r"^[A-Za-z]:", file_path)):
            raise ExportError("Canvas file must be an explicit vault-relative path")
        self.status()
        bound = self._request("POST", "/v3/canvases/bind", {"filePath": file_path})
        token = bound.get("contextToken")
        if not isinstance(token, str) or not token:
            raise ExportError("Native Bridge omitted the canvas binding")
        revision, file = _revision(bound), _file(bound)
        if PurePosixPath(file) != PurePosixPath(file_path):
            raise ExportError("Native Bridge bound a different canvas file")
        elements: list[dict] = []
        ids: set[str] = set()
        total = None
        while True:
            page = self._request("POST", "/v3/elements/query", {
                "contextToken": token, "detail": "full", "offset": len(elements), "limit": 2000,
                "filter": {"includeDeleted": True},
            })
            if _revision(page) != revision or _file(page) != file:
                raise ExportError("Canvas changed during full-scene pagination")
            page_total, page_elements = page.get("total"), page.get("elements")
            if isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0 or not isinstance(page_elements, list):
                raise ExportError("Native Bridge returned an invalid full-scene page")
            if total is None:
                total = page_total
            if page_total != total or page.get("offset", len(elements)) != len(elements):
                raise ExportError("Native Bridge changed the full-scene pagination boundaries")
            for element in page_elements:
                if not isinstance(element, dict) or not isinstance(element.get("id"), str) or not element["id"] or element["id"] in ids:
                    raise ExportError("Native Bridge returned invalid or duplicate scene elements")
                ids.add(element["id"])
                elements.append(element)
            if len(elements) > total:
                raise ExportError("Native Bridge returned more scene elements than declared")
            truncated = page.get("truncated")
            if not isinstance(truncated, bool) or truncated != (len(elements) < total):
                raise ExportError("Native Bridge returned incomplete or inconsistent full-scene pagination")
            if not truncated:
                break
            if not page_elements:
                raise ExportError("Native Bridge returned an empty intermediate full-scene page")
        scene = {"file": file, "revision": revision, "elements": elements, "context_token": token}
        self.assert_unchanged(scene)
        return scene

    def assert_unchanged(self, scene: dict) -> None:
        self.status()
        result = self._request("POST", "/v3/elements/summary", {"contextToken": scene["context_token"]})
        if _revision(result) != scene["revision"] or _file(result) != scene["file"]:
            raise ExportError("Canvas changed since the full scene was read; no final artifacts can be published")

    def export(self, scene: dict, format: str, style: str, padding: float,
               scale: float, out_path: Path) -> dict:
        if format not in {"png", "svg", "pdf"}:
            raise ExportError("Export format must be png, svg or pdf")
        if style not in {"original", "light", "dark"}:
            raise ExportError("Export style must be original, light or dark")
        padding = _number(padding, "padding")
        scale = _number(scale, "scale", positive=True)
        self.status()
        payload = {
            "contextToken": scene["context_token"], "baseRevision": scene["revision"],
            "scope": "all", "padding": padding, "embedFonts": True, "withBackground": True,
        }
        if style != "original":
            payload["theme"] = style
        if format == "png":
            payload["scale"] = scale
            payload["embedScene"] = False
            route = "/v3/render"
        else:
            payload["format"] = format
            route = "/v3/export"
        result = self._request("POST", route, payload)
        if _revision(result) != scene["revision"] or _file(result) != scene["file"]:
            raise ExportError("Native export does not match the requested canvas revision")
        if result.get("complete") is not True:
            raise ExportError("Native export resources are incomplete; no artifact was written")
        native = result.get("export")
        if not isinstance(native, dict) or native.get("scope") != "all" or not isinstance(native.get("renderer"), str):
            raise ExportError("Native export omitted full-canvas renderer metadata")
        theme = native.get("theme")
        if theme not in {"light", "dark", None} or (style != "original" and theme != style):
            raise ExportError("Native export did not honor the requested transient theme")
        bounds = result.get("bounds")
        if not isinstance(bounds, dict):
            raise ExportError("Native export omitted source-scene bounds")
        bounds = {"x": _signed_number(bounds.get("x"), "bounds.x"),
                  "y": _signed_number(bounds.get("y"), "bounds.y"),
                  "width": _number(bounds.get("width"), "bounds.width", positive=True),
                  "height": _number(bounds.get("height"), "bounds.height", positive=True)}
        artifact = result.get("image" if format == "png" else "artifact")
        expected_mime = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[format]
        if not isinstance(artifact, dict) or artifact.get("mimeType") != expected_mime or not isinstance(artifact.get("base64"), str):
            raise ExportError("Native artifact MIME type or encoding does not match the requested format")
        try:
            content = base64.b64decode(artifact["base64"], validate=True)
        except (ValueError, binascii.Error):
            raise ExportError("Native artifact contains invalid base64") from None
        pixels = None
        if format == "png":
            if len(content) < 33 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[8:16] != b"\x00\x00\x00\rIHDR":
                raise ExportError("Native exporter did not return a PNG document")
            pixels = struct.unpack(">II", content[16:24])
            if not all(pixels):
                raise ExportError("Native exporter returned a zero-sized PNG")
        elif format == "pdf":
            if not re.match(rb"%PDF-\d\.\d(?:\r|\n)", content) or not content.rstrip().endswith(b"%%EOF"):
                raise ExportError("Native exporter did not return a complete PDF document")
        else:
            try:
                if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                    raise ElementTree.ParseError("Document declarations are not allowed")
                root = ElementTree.fromstring(content)
                if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
                    raise ElementTree.ParseError("Root must be SVG")
            except (ElementTree.ParseError, ValueError):
                raise ExportError("Native exporter did not return an SVG document") from None
        metadata = {
            "file": scene["file"], "revision": scene["revision"], "format": format,
            "mime_type": expected_mime, "complete": True, "style": style,
            "theme": theme, "renderer": native["renderer"], "scope": "all",
            "bounds": bounds, "padding": padding,
            # All public dimensions use scene units, never PDF points or PNG pixels.
            "width": bounds["width"] + 2 * padding if format == "png" else _number(result.get("width"), "export.width", positive=True),
            "height": bounds["height"] + 2 * padding if format == "png" else _number(result.get("height"), "export.height", positive=True),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        }
        if format == "png":
            actual_scale = _number(result.get("actualScale"), "actualScale", positive=True)
            metadata.update(pixel_width=pixels[0], pixel_height=pixels[1], requested_scale=scale,
                            actual_scale=actual_scale, raster=True,
                            raster_limits={"longest_side_pixels": 1600, "total_pixels": 4000000},
                            scale_limited=actual_scale < scale)
        else:
            for native_key, public_key in (("rasterImages", "raster_images"), ("embeddedSvgImages", "embedded_svg_images")):
                value = native.get(native_key)
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ExportError("Native export returned invalid image resource counts")
                    metadata[public_key] = value
            metadata["vector_notice"] = _VECTOR_NOTICE
        # Export responses are revision-bound, but resources can resolve while a
        # user edits the source. Verify once more before creating even a staged file.
        self.assert_unchanged(scene)
        target = Path(out_path)
        created = False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                created = True
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            raise ExportError("Cannot create a new staged export artifact; the destination may already exist") from None
        return metadata
