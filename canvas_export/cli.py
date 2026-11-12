"""Command-line interface; no project-specific names or drawing generators."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .config import DEFAULTS, FORMATS, STYLES, load_plan, make_plan, positive
from .errors import ExportError
from .profiles import discover_profiles, select_profile

STYLE_HELP = {
    "original": "Keep the source canvas theme; no source mutations.",
    "light": "Render with the native light theme in the temporary export workbench.",
    "dark": "Render with the native dark theme in the temporary export workbench.",
}


def finite_arg(text: str, *, zero: bool = False) -> float:
    try:
        return positive(float(text), "value", allow_zero=zero)
    except (ValueError, ExportError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def selectors(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vault", help="Paired vault name or vault ID; ambiguous names are rejected")
    parser.add_argument("--connection", help="Paired connection ID or private connection JSON path; selection is per-call")
    parser.add_argument("--state-dir", action="append", type=Path, default=None,
                        help="Search this paired-profile state directory (repeatable; overrides default discovery roots)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON (never auth tokens)")


def export_arguments(parser: argparse.ArgumentParser) -> None:
    selectors(parser)
    parser.add_argument("--format", dest="formats", nargs="+", action="extend", choices=FORMATS,
                        help="Export formats; e.g. --format pdf svg png (default: pdf, or project config)")
    parser.add_argument("--style", choices=STYLES,
                        help="Native export theme only; does not change fonts, palette attributes, layout or source")
    parser.add_argument("--padding", type=lambda x: finite_arg(x, zero=True),
                        help="Nonnegative canvas-unit padding (default: 20, or project config)")
    parser.add_argument("--scale", type=finite_arg,
                        help="Requested PNG scale (default: 1.5); host may cap pixels; SVG/PDF stay vector")
    parser.add_argument("--out", dest="output_dir", type=Path,
                        help="Local output root; successful runs in builds/, stable latest/ link")
    parser.add_argument("--latest", help="Latest-success link name under output root (default: latest)")
    parser.add_argument("--timeout", type=finite_arg, default=180,
                        help="Native HTTP request timeout in seconds (default: 180)")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="canvas-export",
        description="Export manually edited Obsidian Excalidraw canvases without modifying source scenes.",
        epilog="Requires a paired, running Obsidian Bridge. No AI session, GUI automation or global vault switch.",
    )
    root.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = root.add_subparsers(dest="command", required=True)
    vaults = commands.add_parser("vaults", help="List locally paired vault/connection profiles, without secrets",
                                 description="List paired profiles only; this does not pair, connect or start a vault.")
    vaults.add_argument("--state-dir", action="append", type=Path, default=None,
                        help="Only search these profile state directories (repeatable)")
    vaults.add_argument("--json", action="store_true", help="Print public profile JSON")
    styles = commands.add_parser("styles", help="Explain supported source-preserving export themes")
    styles.add_argument("--json", action="store_true", help="Print style catalog JSON")
    single = commands.add_parser(
        "export", help="Export one or more explicit vault-relative canvases",
        description="Read live canvas contents, pin revision, export requested formats, verify unchanged, publish latest.",
        epilog="Example: canvas-export export --vault Research --canvas 'Drawings/My Figure.excalidraw.md' --format pdf svg --style light --out ./output",
    )
    export_arguments(single)
    single.add_argument("--canvas", action="append", required=True,
                        help="Explicit vault-relative .excalidraw.md path (repeatable); never inferred from active tab")
    single.add_argument("--name", help="Output basename for a single --canvas; otherwise derived from canvas filename")
    batch = commands.add_parser(
        "build", help="Batch export a JSON project and optionally compile its LaTeX document",
        description="Project-relative inputs, per-figure overrides, optional anchor-based TeX panel headings and Tectonic build.",
        epilog="CLI options override per-figure values; per-figure values override project defaults. No renderer or source-edit fallbacks.",
    )
    export_arguments(batch)
    batch.add_argument("--config", type=Path, required=True, help="Version-1 JSON project file")
    batch.add_argument("--no-latex", action="store_true", help="Only export figures; skip wrapper generation and TeX compilation")
    return root


def canvas_name(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    for ending in (".excalidraw.md", ".excalidraw", ".md"):
        if name.endswith(ending):
            name = name[:-len(ending)]
            break
    name = "".join(char if char.isalnum() or char in "_-" else "_" for char in name).lstrip("_-")
    return name or "canvas"


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command == "styles":
            if args.json:
                print(json.dumps(STYLE_HELP, ensure_ascii=False, indent=2))
            else:
                for name, description in STYLE_HELP.items():
                    print(f"{name:10} {description}")
                print("These are native light/dark export themes, not paper/presentation font or line-style presets.")
            return 0
        profiles = discover_profiles(args.state_dir)
        if args.command == "vaults":
            public = [profile.summary() for profile in profiles]
            if args.json:
                print(json.dumps(public, ensure_ascii=False, indent=2))
            elif public:
                for profile in public:
                    print(json.dumps(profile, ensure_ascii=False))
            else:
                print("No paired profiles found. Pair/start the Bridge on the Obsidian host first.")
            return 0
        overrides = {name: getattr(args, name, None) for name in
                     ("vault", "connection", "formats", "style", "padding", "scale", "output_dir", "latest", "no_latex")}
        if args.command == "build":
            plan = load_plan(args.config.expanduser().resolve(), overrides)
        else:
            if args.name and len(args.canvas) != 1:
                raise ExportError("--name requires exactly one --canvas")
            figures = {}
            for path in args.canvas:
                name = args.name or canvas_name(path)
                if name in figures:
                    raise ExportError(f"Output basename collision: {name}; use separate calls with --name or a project config")
                figures[name] = {"file": path}
            raw = {"figures": figures, "formats": list(DEFAULTS["formats"])}
            plan = make_plan(raw, Path.cwd(), overrides)
        profile = select_profile(profiles, vault=plan.vault, connection=plan.connection)
        from .engine import run
        result = run(plan, profile, timeout=args.timeout,
                     progress=lambda line: print(line, file=sys.stderr, flush=True))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Exported: " + result["output_dir"])
            if result["integration_pdf"]:
                print("LaTeX PDF: " + result["integration_pdf"])
            print("Source canvas unchanged. Exporting does not grant an independent review PASS.")
        return 0
    except (ExportError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; no new latest-success publication.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
