"""Read paired Bridge profiles without changing the host's selected connection."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import ntpath
import os
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import urlsplit

from .errors import ExportError


@dataclass(frozen=True)
class Profile:
    id: str
    vault_name: str
    vault_id: str
    host_name: str
    host_id: str
    config_path: Path
    settings: dict = field(repr=False)

    def summary(self) -> dict:
        """Only explicitly public fields; never return the private settings object."""
        return {
            "id": self.id,
            "vault_name": self.vault_name,
            "vault_id": self.vault_id,
            "host_name": self.host_name,
            "host_id": self.host_id,
            "config_path": str(self.config_path),
        }


def path_identity(value: str) -> str:
    """Compare host paths on the client, including Windows paths on Unix clients."""
    if ntpath.splitdrive(value)[0] or "\\" in value:
        return ntpath.normpath(value).replace("\\", "/").casefold()
    return posixpath.normpath(value)


def _default_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        default = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local"))) / "ObsidianExcalidrawAgent"
    elif sys.platform == "darwin":
        default = home / "Library/Application Support/ObsidianExcalidrawAgent"
    else:
        default = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "obsidian-excalidraw-agent"
    roots = [default, home / ".local/share/obsidian-excalidraw-agent-remote/state"]
    override = os.environ.get("EXCALIDRAW_AGENT_STATE_DIR")
    if override:
        roots.insert(0, Path(override))
    return roots


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ExportError(f"Cannot read paired connection configuration: {path}") from None
    if not isinstance(data, dict):
        raise ExportError(f"Paired connection configuration must be a JSON object: {path}")
    return data


def _load_profile(path: Path) -> Profile:
    path = path.expanduser().resolve()
    settings = _read_json(path)
    connection_id = settings.get("connection_id")
    if connection_id is not None:
        if not isinstance(connection_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", connection_id):
            raise ExportError(f"Invalid connection ID in paired configuration: {path}")
        # connection.json is a pointer, even when it contains stale copied credentials.
        if path.parent.name != "connections":
            path = path.parent / "connections" / f"{connection_id}.json"
            settings = _read_json(path)
            if settings.get("connection_id", connection_id) != connection_id:
                raise ExportError("Paired connection pointer and profile IDs disagree")
        elif path.stem != connection_id:
            raise ExportError("Paired connection filename and profile ID disagree")
    for key in ("bridge_url", "bridge_token", "vault_name", "vault_id", "host_name", "host_id", "host_vault_path", "vault_path"):
        if key in settings and not isinstance(settings[key], str):
            raise ExportError(f"Invalid {key} in paired configuration: {path}")
    url, token = settings.get("bridge_url", ""), settings.get("bridge_token", "")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ExportError("Paired Bridge URL is invalid") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or port == 0):
        raise ExportError("Paired Bridge URL must be an HTTP loopback address without credentials, path, query or fragment")
    if not token or any(ord(char) < 32 or ord(char) == 127 for char in token):
        raise ExportError(f"Missing or invalid paired Bridge credential: {path}")
    host_id, vault_id = settings.get("host_id", ""), settings.get("vault_id", "")
    vault_path = settings.get("host_vault_path") or settings.get("vault_path")
    if not (host_id and vault_id) and not (settings.get("host_name") and settings.get("vault_name") and vault_path):
        raise ExportError("Paired configuration needs host/vault IDs or host name, vault name and host vault path")
    settings = dict(settings)
    settings["bridge_url"] = url.rstrip("/")
    profile_id = connection_id or settings.get("connection_id")
    if not profile_id:
        profile_id = path.stem if path.parent.name == "connections" else hashlib.sha256(
            json.dumps([host_id, vault_id, settings["bridge_url"], vault_path], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:24]
    return Profile(profile_id, settings.get("vault_name", ""), vault_id,
                   settings.get("host_name", ""), host_id, path, settings)


def _identity(profile: Profile) -> tuple[str, str, str]:
    settings = profile.settings
    host = profile.host_id or profile.host_name
    vault = profile.vault_id or path_identity(settings.get("host_vault_path") or settings.get("vault_path", ""))
    return host, vault, settings["bridge_url"]


def discover_profiles(state_dirs: list[Path] | None = None) -> list[Profile]:
    """Inspect only paired connection.json and connections/*.json in known roots.

    Invalid/unpaired files are not candidates. Explicit selection of such a file
    produces an error instead of falling back to another paired connection.
    """
    profiles: list[Profile] = []
    seen: set[tuple[str, str, str]] = set()
    roots = state_dirs if state_dirs is not None else _default_roots()
    for root in dict.fromkeys(Path(root).expanduser().resolve() for root in roots):
        candidates = sorted((root / "connections").glob("*.json"))
        if (root / "connection.json").is_file():
            candidates.append(root / "connection.json")
        for path in candidates:
            try:
                profile = _load_profile(path)
            except ExportError:
                continue
            identity = _identity(profile)
            if identity not in seen:
                profiles.append(profile)
                seen.add(identity)
    return profiles


def _matches_vault(profile: Profile, vault: str) -> bool:
    if vault in {profile.vault_name, profile.vault_id} - {""}:
        return True
    paths = [profile.settings.get(key) for key in ("host_vault_path", "vault_path")]
    return any(path and path_identity(path) == path_identity(vault) for path in paths)


def select_profile(profiles: list[Profile], vault: str | None = None,
                   connection: str | None = None) -> Profile:
    """Select once for this caller; never overwrite global connection.json."""
    candidates = list(profiles)
    if connection is not None:
        exact = [profile for profile in candidates if profile.id == connection]
        if exact:
            candidates = exact
        else:
            path = Path(connection).expanduser()
            if path.is_file():
                candidates = [_load_profile(path)]
            else:
                # Known paths are useful even if a paired file has since vanished:
                # do not silently reuse stale settings or choose a different host.
                raise ExportError("Unknown connection; choose a listed connection ID or an existing private config file")
    if vault is not None:
        candidates = [profile for profile in candidates if _matches_vault(profile, vault)]
        if not candidates:
            raise ExportError("No paired connection matches the requested vault")
    if not candidates:
        raise ExportError("No paired Bridge connections found; pair the intended vault first")
    if len(candidates) != 1:
        raise ExportError("Multiple paired connections match; select an explicit connection ID or private config file")
    return candidates[0]
