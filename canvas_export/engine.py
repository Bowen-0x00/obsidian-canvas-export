"""Revision-pinned, source-preserving exports with atomic latest publication."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable

from .bridge import NativeBridge
from .config import Plan
from .errors import ExportError
from .latex import graphics_tex
from .profiles import Profile


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_latex(stage: Path, spec: dict, compiler: str) -> None:
    for source, target in spec["inputs"]:
        destination = stage / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    process = subprocess.run(
        [compiler, "-X", "compile", spec["source"], "--outdir", ".",
         "--keep-logs", "--keep-intermediates"],
        cwd=stage, capture_output=True, text=True, timeout=600, check=False,
    )
    (stage / "build.log").write_text(process.stdout + process.stderr, encoding="utf-8")
    result = stage / spec["output"]
    if process.returncode or not result.is_file():
        raise ExportError(f"LaTeX compilation failed; see {stage / 'build.log'}")
    if not result.read_bytes().startswith(b"%PDF-"):
        raise ExportError(f"Compiler output is not a PDF: {result}")


def run(plan: Plan, profile: Profile, *, timeout: float = 180,
        progress: Callable[[str], None] = lambda message: None) -> dict:
    compiler = None
    if plan.latex:
        compiler = shutil.which("tectonic")
        if not compiler:
            candidate = Path.home() / ".local/bin/tectonic"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                compiler = str(candidate)
        if not compiler:
            raise ExportError("Tectonic not found. Install it for LaTeX builds or use --no-latex.")
    latest = plan.output_dir / plan.latest
    if (latest.exists() or latest.is_symlink()) and not latest.is_symlink():
        raise ExportError(f"Refusing to replace a real file/directory at latest link: {latest}")
    bridge = NativeBridge(profile, timeout=timeout)
    status = bridge.status()
    builds = plan.output_dir / "builds"
    builds.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=builds))
    states = {}
    output_figures = {}
    try:
        for name, figure in plan.figures.items():
            progress(f"Reading {name}: {figure['file']}")
            scene = bridge.read(figure["file"])
            exports = {}
            for fmt in figure["formats"]:
                progress(f"  Exporting {fmt} / {figure['style']}")
                exports[fmt] = bridge.export(
                    scene, fmt, figure["style"], figure["padding"], figure["scale"],
                    stage / f"{name}.{fmt}",
                )
            # Native JSON is an inspection snapshot, not a fabricated portable
            # .excalidraw.md with missing image/LaTeX resources.
            write_json(stage / f"{name}.native.json", {
                "file": scene["file"], "revision": scene["revision"], "elements": scene["elements"],
            })
            write_json(stage / f"{name}.exports.json", exports)
            states[name] = scene
            if "pdf" in exports:
                states[name]["pdf"] = exports["pdf"]
            output_figures[name] = {
                "file": scene["file"], "revision": scene["revision"], "style": figure["style"],
                "artifacts": {fmt: {"path": f"{name}.{fmt}", "sha256": receipt["sha256"]}
                              for fmt, receipt in exports.items()},
            }
        if plan.latex:
            wrapper = stage / plan.latex["wrapper"]
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text(graphics_tex(plan.figures, states), encoding="utf-8")
            progress("Compiling LaTeX")
            compile_latex(stage, plan.latex, compiler)
        # No automatic retry: a mixed batch of before/after edits must not be
        # presented as a coherent successful publication.
        for scene in states.values():
            bridge.assert_unchanged(scene)
        manifest = {
            "status": "exported_not_independently_reviewed", "canvas_mutations": False,
            "connection": profile.summary(), "vault": status.get("vault", {}),
            "figures": output_figures,
        }
        if plan.latex:
            manifest["latex"] = {
                "path": plan.latex["output"],
                "sha256": hashlib.sha256((stage / plan.latex["output"]).read_bytes()).hexdigest(),
            }
        write_json(stage / "build_manifest.json", manifest)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = builds / stamp
        stage.rename(destination)
        stage = destination
        temporary_link = builds / (".latest-" + stamp)
        # This relative target is interpreted at its FINAL parent location.
        temporary_link.symlink_to(destination.relative_to(plan.output_dir))
        os.replace(temporary_link, latest)
        return {"output_dir": str(latest), "run_dir": str(destination),
                "integration_pdf": str(latest / plan.latex["output"]) if plan.latex else None,
                "status": manifest["status"], "canvas_mutations": False,
                "figures": output_figures}
    except Exception as error:
        if isinstance(error, subprocess.TimeoutExpired):
            reason = "LaTeX compiler timed out"
        else:
            reason = str(error)
        # No previous success, reviewed artifacts or source canvas is removed.
        raise ExportError(f"{reason}\nBuild not published; diagnostics retained at {stage}") from error
