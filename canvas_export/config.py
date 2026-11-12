"""Strict project configuration and command-line override precedence."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path, PurePosixPath

from .errors import ExportError

FORMATS = ("pdf", "svg", "png")
STYLES = ("original", "light", "dark")
DEFAULTS = {"formats": ["pdf"], "style": "original", "padding": 20.0, "scale": 1.5}


@dataclass
class Plan:
    figures: dict
    output_dir: Path
    latest: str
    vault: str | None
    connection: str | None
    latex: dict | None


def known_keys(value: dict, allowed: set[str], location: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise ExportError(f"{location}: unknown keys: {', '.join(sorted(extra))}")


def identifier(value: object, location: str) -> str:
    if (not isinstance(value, str) or not value or not value[0].isalnum()
            or not all(char.isalnum() or char in "_-" for char in value)):
        raise ExportError(f"{location}: use letters, digits, '_' or '-' (start with a letter/digit)")
    return value


def positive(value: object, location: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExportError(f"{location}: expected a finite number")
    if value < 0 or (value == 0 and not allow_zero):
        raise ExportError(f"{location}: expected {'nonnegative' if allow_zero else 'positive'} number")
    return float(value)


def relative_file(value: object, location: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ExportError(f"{location}: expected a nonempty relative path with '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value or not path.name:
        raise ExportError(f"{location}: absolute paths and '..' are not allowed")
    if str(path) == ".":
        raise ExportError(f"{location}: a file path is required")
    return str(path)


def local_path(value: object, base: Path, location: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ExportError(f"{location}: expected a local path")
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def export_options(global_values: dict, figure: dict, overrides: dict) -> dict:
    merged = {**DEFAULTS, **global_values, **figure, **{k: v for k, v in overrides.items() if v is not None}}
    formats = merged["formats"]
    if not isinstance(formats, list) or not formats or any(fmt not in FORMATS for fmt in formats):
        raise ExportError("formats: expected a nonempty list containing pdf, svg and/or png")
    style = merged["style"]
    if style not in STYLES:
        raise ExportError(f"style: choose {', '.join(STYLES)}; styles are export themes, not canvas edits")
    return {
        "formats": list(dict.fromkeys(formats)), "style": style,
        "padding": positive(merged["padding"], "padding", allow_zero=True),
        "scale": positive(merged["scale"], "scale"),
    }


def normalize_latex(value: object, base: Path, figures: dict) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ExportError("latex: expected an object")
    known_keys(value, {"source", "inputs", "wrapper", "output"}, "latex")
    source = local_path(value.get("source"), base, "latex.source")
    wrapper = relative_file(value.get("wrapper", "canvas_graphics.tex"), "latex.wrapper")
    output = relative_file(value.get("output", source.stem + ".pdf"), "latex.output")
    if output != source.stem + ".pdf":
        raise ExportError("latex.output must equal the source filename with a .pdf extension (Tectonic output)")
    inputs = [(source, source.name)]
    items = value.get("inputs", [])
    if not isinstance(items, list):
        raise ExportError("latex.inputs: expected a list of paths or {source,target} objects")
    for item in items:
        if isinstance(item, str):
            src = local_path(item, base, "latex.inputs")
            target = relative_file(item, "latex.inputs target")
        elif isinstance(item, dict):
            known_keys(item, {"source", "target"}, "latex.inputs")
            src = local_path(item.get("source"), base, "latex.inputs.source")
            target = relative_file(item.get("target", src.name), "latex.inputs.target")
        else:
            raise ExportError("latex.inputs: expected paths or {source,target} objects")
        inputs.append((src, target))
    # Source files must never overwrite a generated artifact, wrapper or manifest.
    generated = {"build_manifest.json", "build.log", wrapper, output}
    for name, figure in figures.items():
        generated.update(f"{name}.{fmt}" for fmt in FORMATS)
        generated.update((f"{name}.native.json", f"{name}.exports.json"))
        if figure.get("macro") and "pdf" not in figure["formats"]:
            raise ExportError(f"{name}: a LaTeX graphic macro requires pdf in formats (or use --no-latex)")
    targets = set()
    for src, target in inputs:
        if target in generated or target in targets:
            raise ExportError(f"latex input target collides with another file: {target}")
        targets.add(target)
        if not src.is_file():
            raise ExportError(f"LaTeX input does not exist: {src}")
    return {"source": source.name, "inputs": inputs, "wrapper": wrapper, "output": output}


def make_plan(raw: dict, base: Path, overrides: dict | None = None) -> Plan:
    if not isinstance(raw, dict):
        raise ExportError("Project config must be a JSON object")
    known_keys(raw, {"version", "vault", "connection", "style", "formats", "padding", "scale",
                     "output_dir", "latest", "figures", "latex"}, "project")
    if raw.get("version", 1) != 1 or isinstance(raw.get("version"), bool):
        raise ExportError("Unsupported config version; expected 1")
    overrides = overrides or {}
    figures_raw = raw.get("figures")
    if not isinstance(figures_raw, dict) or not figures_raw:
        raise ExportError("figures: expected a nonempty object")
    figures = {}
    globals_ = {key: raw[key] for key in DEFAULTS if key in raw}
    for name, value in figures_raw.items():
        identifier(name, "figure basename")
        if not isinstance(value, dict):
            raise ExportError(f"figures.{name}: expected an object")
        known_keys(value, {"file", "style", "formats", "padding", "scale", "macro", "panel_scope", "panels"}, name)
        figure = {**value, **export_options(globals_, value, overrides)}
        figure["file"] = relative_file(value.get("file"), name + ".file")
        if "panels" in value and not isinstance(value["panels"], list):
            raise ExportError(f"{name}.panels: expected a list")
        if value.get("panels") and not value.get("macro"):
            raise ExportError(f"{name}: panels require a LaTeX macro")
        figures[name] = figure
    output_value = overrides.get("output_dir") or raw.get("output_dir", "output")
    # Config-relative paths; CLI output overrides are shell-cwd-relative.
    output_base = Path.cwd() if overrides.get("output_dir") else base
    output_dir = local_path(str(output_value), output_base, "output_dir")
    latest = identifier(overrides.get("latest") or raw.get("latest", "latest"), "latest link name")
    if latest == "builds":
        raise ExportError("latest link name cannot be 'builds'")
    vault = overrides.get("vault") or raw.get("vault")
    connection = overrides.get("connection") or raw.get("connection")
    for name, value in (("vault", vault), ("connection", connection)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ExportError(f"{name}: expected a nonempty string")
    if connection and not overrides.get("connection") and ("/" in connection or connection.endswith(".json")):
        connection = str(local_path(connection, base, "connection"))
    latex = None if overrides.get("no_latex") else normalize_latex(raw.get("latex"), base, figures)
    return Plan(figures, output_dir, latest, vault, connection, latex)


def load_plan(path: Path, overrides: dict | None = None) -> Plan:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ExportError(f"Cannot read project config {path}: {error}") from error
    return make_plan(raw, path.resolve().parent, overrides)
