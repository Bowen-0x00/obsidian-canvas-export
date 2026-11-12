# Obsidian Canvas Export

**[English](README.md) · [简体中文](README.zh-CN.md)**

Export live, manually edited Obsidian Excalidraw canvases to **PNG, SVG and PDF**, without rewriting the source scene. Use a standalone CLI for one figure or a JSON project for a batch, with optional LaTeX integration and anchor-based panel headings.

Version **1.0.0** · Python **3.10+** · standard-library-only runtime · **MIT**

No AI session, MCP client, drawing generator, browser automation or global vault switch is required. **A paired, running native Obsidian Bridge is required**: this is not an offline `.excalidraw.md` converter.

## 1. Prepare the Obsidian host

The exporter and its graphical rendering host are separate installations:

1. Install and enable [Obsidian Excalidraw-ymjr](https://github.com/Bowen-0x00/obsidian-excalidraw-plugin-ymjr) in your intended Obsidian Desktop vault. **Vanilla upstream Excalidraw alone is not sufficient.**
2. Follow the companion [quick start](https://github.com/Bowen-0x00/obsidian-excalidraw-agent-skill#quick-start) and [connection/state/remote setup guide](https://github.com/Bowen-0x00/obsidian-excalidraw-agent-skill/blob/main/skills/obsidian-excalidraw/references/agent-setup.md). The compatible baseline for this exporter is Bridge **0.13.8** with companion launcher **0.10.8**; follow the companion's current instructions when upgrading.
3. Keep Obsidian open, the intended vault paired, and its Bridge running. Installing this exporter does **not** install or upgrade the host plugin, pair a vault, grant permissions, or launch Obsidian.

For initial setup, run these commands **in the companion repository on the graphical host**, not in this exporter repository:

```sh
uv sync --frozen
uv run --frozen python launcher.py connect
uv run --frozen python launcher.py status
uv run --frozen python launcher.py doctor
```

If needed, select a returned vault using `connect --vault-name "VAULT_ID_OR_UNIQUE_NAME"`. Without automatic startup, run `Agent-Drawing/mcp/Start-Agent-Drawing` in Obsidian, then check `status`/`doctor` again. A `launched:false` result does not mean the Bridge started. The companion has its own Python/uv requirements; these are separate from this exporter's Python 3.10+ requirement.

For a remote client, follow the companion's host-side pairing/deployment and SSH loopback-tunnel workflow. Keep the tunnel running; remote clients use their existing private paired profiles, not host filesystem discovery or remote `connect` against a desktop vault path.

**PDF additionally requires the host's already-enabled and authorized Excalidraw Extras PDF component.** PNG/SVG do not require Extras PDF. Optional LaTeX builds require [Tectonic](https://tectonic-typesetting.github.io/) on the client; image export alone does not require TeX.

## 2. Install the exporter

Install directly from this public GitHub repository; these commands do **not** assume a PyPI release. Git and Python 3.10+ are needed for Git-based installation. Choose one method.

### pipx — recommended

With [pipx](https://pipx.pypa.io/stable/installation/) installed:

```sh
pipx install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --version
```

### uv tool

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
uv tool install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --help
```

If your shell cannot find the installed command, follow your installer's PATH setup (`pipx ensurepath` or `uv tool update-shell`), then reopen the shell.

### Python virtual environment

POSIX shell example, without pipx or uv:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --help
```

On Windows, use the environment's `Scripts` directory/activation command instead. Windows runtime operation has not been verified; see the symlink requirement below.

### Run from a checkout

This also gives you the example JSON and TeX files:

```sh
git clone https://github.com/Bowen-0x00/obsidian-canvas-export.git
cd obsidian-canvas-export
python3 -m canvas_export --help
./bin/canvas-export --help
```

The checkout entry points need no package installation. For an editable development install, use `python -m pip install -e .` inside a virtual environment. All three entry points—`canvas-export`, `python -m canvas_export`, and `bin/canvas-export`—expose the same CLI.

## 3. First export

List your client's paired profiles, then choose your vault. `Research` and the canvas paths below are **examples**: replace them with your own values.

```sh
canvas-export vaults
canvas-export styles
canvas-export export \
  --vault Research \
  --canvas 'Drawings/My Figure.excalidraw.md' \
  --name my_figure \
  --format png svg \
  --style original \
  --out ./exports
```

Start with PNG/SVG if Extras PDF is not configured. Add `pdf` to `--format` when the host is ready. **Omitting `--format` defaults to PDF.** Save your drawing first and avoid editing it during export or optional compilation: the exporter reads the host's live scene, not an old client-side JSON copy.

After a successful run, find the artifacts under `exports/latest/`. `latest` is a symlink to a timestamped build, not a directory that is overwritten in place.

### Commands and options

| Command | Purpose |
| --- | --- |
| `canvas-export vaults [--json] [--state-dir PATH]` | List local paired profiles without credentials; does not test whether the host is online |
| `canvas-export styles [--json]` | Explain the three native export themes; no host connection needed |
| `canvas-export export --canvas PATH ...` | Export one or more explicit vault-relative canvases |
| `canvas-export build --config project.json ...` | Export a JSON project and optionally compile its TeX document |
| `canvas-export --version` / `--help` | Show version or help; each subcommand also supports `--help` |

`export` and `build` share these options:

| Option | Meaning / default |
| --- | --- |
| `--vault NAME_OR_ID` | Select a paired vault by unique name, ID, or host vault path recorded in the profile |
| `--connection ID_OR_PATH` | Select a connection ID or existing private pairing JSON file, for this invocation only |
| `--state-dir PATH` | Repeatable; replace the default profile-discovery roots |
| `--format pdf svg png` | One or more formats; repeatable; duplicates removed; default `pdf` |
| `--style original\|light\|dark` | Native transient export theme; default `original` |
| `--padding NUMBER` | Nonnegative padding in canvas units; default `20` |
| `--scale NUMBER` | Positive requested PNG scale; default `1.5`; host pixel caps may reduce it |
| `--out PATH` | Client-side output root; default `output` |
| `--latest NAME` | Latest-success symlink name; default `latest`; cannot be `builds` |
| `--timeout SECONDS` | Positive timeout per native HTTP request; default `180` |
| `--json` | Machine-readable success result on stdout; progress/errors go to stderr |

For `export`, repeat `--canvas` for multiple drawings in the same selected vault. Paths use `/` and are **vault-relative**, not client paths or absolute host paths; absolute paths and `..` are rejected. `--name` is allowed only with one canvas. Otherwise basenames are derived from filenames, replacing punctuation/spacing with `_` and retaining letters/digits, including non-ASCII letters. Collisions fail: use separate named calls or a batch configuration. For `build`, `--config` is required; `--no-latex` skips both wrapper generation and TeX compilation.

### Private profiles and target selection

```sh
canvas-export vaults --json
canvas-export export \
  --connection CONNECTION_ID_FROM_VAULTS \
  --canvas 'Drawings/My Figure.excalidraw.md' --format png --out ./exports

# If the companion uses a custom private state directory:
canvas-export vaults --state-dir ~/.config/canvas-bridge-state
canvas-export export \
  --state-dir ~/.config/canvas-bridge-state --vault Research \
  --canvas 'Drawings/My Figure.excalidraw.md' --format png
```

With exactly one paired candidate, selectors can be omitted. Multiple candidates, including duplicate vault names, require an unambiguous selection. If both `--connection` and `--vault` are supplied, they must match. An unknown target never falls back to another vault, and selection never rewrites the companion's global `connection.json`.

Discovery reads only `connection.json` and `connections/*.json` under:

- The local platform's default `ObsidianExcalidrawAgent` data directory (Linux: `${XDG_DATA_HOME:-~/.local/share}/obsidian-excalidraw-agent`; macOS: `~/Library/Application Support/ObsidianExcalidrawAgent`; Windows: `%LOCALAPPDATA%/ObsidianExcalidrawAgent`).
- `~/.local/share/obsidian-excalidraw-agent-remote/state`.
- `EXCALIDRAW_AGENT_STATE_DIR`, when set, in addition to the defaults.

Explicit `--state-dir` entries replace those roots. There is no recursive vault scan, pairing, or lookup in another machine's registry. `vaults` lists local paired records, not a live-host guarantee; export authenticates and verifies host/vault identity.

Keep pairing files private: do not paste bearer tokens into project JSON or commit state directories. Connections are restricted to loopback HTTP, with proxies and redirects disabled. JSON results do not include bearer or context tokens, but profile metadata, canvas snapshots, manifests and logs can still disclose your drawing content or local paths—review them before sharing.

### Themes, not redesigns

| Style | Behavior |
| --- | --- |
| `original` | Preserve the source canvas theme and native properties |
| `light` | Request the host's native light theme in a temporary export workbench |
| `dark` | Request the host's native dark theme in a temporary export workbench |

These are **not** paper/slide templates, font replacements, line-width presets or layout transformations. The host decides native light/dark conversion, including treatment of explicitly set element colors. The source theme, text, coordinates and shapes are not rewritten. Edit the canvas in Obsidian when you need a different design.

## Batch configuration

Use [examples/export.json](examples/export.json) as a template; replace its vault/canvas placeholders. For example, save this as `project.json`:

```json
{
  "version": 1,
  "vault": "Research",
  "formats": ["png", "svg"],
  "style": "original",
  "output_dir": "./exports",
  "figures": {
    "architecture": {"file": "Drawings/Architecture.excalidraw.md"},
    "datapath": {"file": "Drawings/Datapath.excalidraw.md", "style": "light"}
  }
}
```

```sh
canvas-export build --config ./project.json
canvas-export build --config ./project.json --format png --style dark --no-latex
```

**Precedence: CLI overrides > per-figure fields > project fields > built-in defaults.** Unknown JSON fields are rejected rather than silently ignored.

| Project field | Meaning / default |
| --- | --- |
| `version` | Configuration version `1`; optional |
| `vault`, `connection` | Same target selectors as the CLI; no credential values |
| `formats` | Nonempty array of `pdf`, `svg`, `png`; default `["pdf"]` |
| `style` | `original`, `light` or `dark`; default `original` |
| `padding`, `scale` | Finite nonnegative padding / finite positive PNG scale; defaults `20`, `1.5` |
| `output_dir` | Output root; default `output` |
| `latest` | Latest-success link name; default `latest`; cannot be `builds` |
| `figures` | Required nonempty object; keys are output basenames, without extensions |
| `latex` | Optional TeX build configuration, described below |

Each figure requires `file` and may override `formats`, `style`, `padding`, `scale`. Optional `macro`, `panel_scope`, `panels` are only for the TeX wrapper. Basenames and `latest` use letters, digits, `_`, `-`, starting with a letter/digit; use ASCII figure basenames for TeX graphics.

Local configuration paths—including output, TeX inputs and a connection-file path—are relative to the JSON file's directory (absolute local paths also work). CLI `--out` and a CLI connection-file path are relative to the invocation's working directory. Canvas paths always remain vault-relative. Never put your private pairing file inside the public project just to make a relative path shorter.

## Optional LaTeX integration

[examples/export-with-latex.json](examples/export-with-latex.json) and the supplied [examples/paper.tex](examples/paper.tex) form a minimal example. Replace the vault/canvas placeholders, keep the JSON next to `paper.tex`, and run from a checkout:

```sh
canvas-export build --config examples/export-with-latex.json
```

This exports a native figure PDF, generates `canvas_graphics.tex` with `\ExampleGraphic`, and compiles `paper.tex` to `paper.pdf` in the staged build. **No logicalId anchor is required for this example.** Tectonic must be on `PATH` or executable at `~/.local/bin/tectonic`; its first compilation may download TeX dependencies. Extras PDF is still required to export the figure PDF.

To integrate another document:

```json
"latex": {
  "source": "paper.tex",
  "inputs": ["references.bib", {"source": "styles/custom.cls", "target": "custom.cls"}],
  "wrapper": "canvas_graphics.tex",
  "output": "paper.pdf"
}
```

This is a configuration fragment; declare only extra input files you actually have. The main source is copied using its basename; `output` must equal that basename with `.pdf`. `inputs` defaults to `[]` and accepts relative path strings or `{source,target}` objects. Targets must be safe relative paths; missing inputs, duplicate targets and collisions with generated artifacts fail. Only declared files are copied, not an entire document tree. `wrapper` defaults to `canvas_graphics.tex`.

A figure with `"macro": "ExampleGraphic"` must include `pdf` in its formats. In the main document, load `graphicx`, `overpic` with the `percent` option, and `hyperref` for linked panel references, then `\input{canvas_graphics.tex}`. Invoke `\ExampleGraphic` inside a `figure` or `figure*` environment as appropriate. Graphics use `\textwidth`; this is not an automatic single-column layout engine. Your document class retains figure numbering, captions and document typography.

### Optional panel headings and logicalId anchors

Ordinary hand-edited drawings can omit this entire mechanism. To place TeX-owned `(a)`, `(b)` headings without writing duplicate headings into the canvas, add fields to a figure:

```json
"macro": "ArchitectureGraphic",
"panel_scope": "Architecture",
"panels": [
  {"label": "fig:architecture_a", "title": "System organization", "anchor": "system_boundary", "dx": 0, "dy": -40}
]
```

- Each `anchor` must uniquely match an undeleted, unrotated element's `customData.agentDiagram.logicalId`. It is **not** a native element ID or a filename. This exporter does not create the metadata; use existing intentional anchors or omit panels.
- `dx`/`dy` are finite offsets in **canvas units** from the anchor's top-left corner: positive x is right, positive y is down; `dy: -40` puts the heading above the anchor. Positions are recomputed using the current source bounds and export padding, including negative canvas coordinates—not PNG pixels or PDF points.
- Move the anchor with its panel. Missing, duplicated or rotated anchors fail instead of reusing stale coordinates. The exporter does not infer panel membership; visually inspect the final PDF after rearranging/scaling content.
- Macro names and panel scopes contain English letters only and must be unique within the wrapper; labels must be unique and use ASCII letters/digits, `:`, `_`, `-`. Reserved helper macro names are rejected. Titles are escaped as plain text, not executed as TeX.
- Panel headings use sans-serif bold at 9 TeX pt, with per-figure panel letters and scoped hyperlink identities. They do not override the document's general fonts or sizes.
- `--no-latex` skips both wrapper and compilation, including when temporarily overriding formats to PNG-only.

## Outputs, source safety and limits

A successful batch produces a tree like this (only requested formats are present):

```text
exports/
  latest -> builds/<UTC-timestamp>/
  builds/<UTC-timestamp>/
    architecture.png
    architecture.svg
    architecture.pdf
    architecture.native.json
    architecture.exports.json
    build_manifest.json
    canvas_graphics.tex         # only with latex configured
    paper.pdf / build.log        # only with latex configured
```

- Each canvas is bound to a specific file/revision. Reads, pagination, exports and final checks must agree. Editing during a build causes failure rather than an automatic retry or a mixed-revision batch.
- The exporter calls native status/bind/query/summary/export/render routes, not create/apply scene mutations. The host may open the requested drawing or use a temporary export workbench; it does not redraw or overwrite the source scene.
- `latest` changes atomically only after all exports, optional TeX compilation and revision checks succeed. A real file/directory at that path is never overwritten. Failed staging directories (`.pending-*`) are retained for diagnosis; a late publication failure may retain a timestamped build instead. The previous latest-success link stays unchanged.
- Atomic publication requires **OS permission to create symlinks**. On Windows this may require Developer Mode or administrator privileges; Windows runtime support has not been verified. There is no copy-based publication fallback.
- `.native.json` is an element inspection snapshot, **not** a complete portable `.excalidraw.md` backup containing all embedded resources. The editable source remains in your vault.
- `.exports.json` records rendering/theme/revision, SHA256, bounds, padding, resource counts and actual scale/pixel metadata. The batch manifest records figure artifacts and an optional integrated PDF hash.
- Current Bridge PNG output is capped at a **1600-pixel longest side** and **4,000,000 total pixels**. Requested `--scale` is not guaranteed; inspect `requested_scale`, `actual_scale`, `pixel_width`, `pixel_height`, `scale_limited`. A large requested scale is not proof of high DPI.
- SVG/PDF retain native vector paths, but embedded images, HTML captures and some effects may remain raster. There is **no all-vector guarantee**.
- Missing resources, PDF permissions/dependencies, authentication, identity mismatch and offline hosts fail explicitly. There is no screenshot, Pillow or Matplotlib substitute PDF.
- Success is recorded as `exported_not_independently_reviewed`. Export does **not** grant or inherit an independent review PASS, scientific correctness, or publication-layout approval.
- Builds and diagnostic directories are not automatically pruned. Manage retention yourself. Host fonts/plugins, SSH setup, redesign, semantic review and document-template conversion are outside this tool's scope.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| No paired profiles | Finish companion setup on the intended graphical host; use the correct client's state directory or `--connection` private-file path. `vaults` does not pair or launch a host. |
| Ambiguous vault / wrong target | Use a returned connection ID. Both selectors must agree. Do not work around failure by copying tokens into a project. |
| Connection refused, timeout, authentication or identity error | Keep the Bridge/remote SSH tunnel running; use companion `status` and `doctor` from its repository. Repair pairing through its documented workflow; verify the intended host/vault. `--timeout` changes request timeouts, not pairing or authorization. |
| PDF export fails | Enable and authorize compatible Extras PDF on the host, or request `--format png svg`. Installing a client PDF library will not repair the host dependency. |
| Missing images/fonts or incomplete native resources | Restore the required assets/fonts on the Obsidian host and inspect the source there. The exporter does not replace missing content. |
| Revision changed | Stop editing, save the canvas and rerun. No automatic retry hides concurrent changes. |
| Tectonic missing / TeX failure | Install Tectonic or use `--no-latex`; check declared inputs and the retained `build.log` (if compilation started). First-use dependency downloads may require network access. |
| Symlink permission / existing latest path | Use an output location with symlink permission; move aside your own real file/directory at the selected latest path. Do not remove an unrelated directory blindly. |
| PNG too small / dark theme looks different | Check actual pixel/scale metadata and native theme behavior; `--scale` cannot override host caps, and themes are not style rewriting. |

## Development and contributions

From a checkout, run the standard-library tests:

```sh
python3 -m unittest discover -s tests -v
```

Tests use local HTTP fixtures and temporary directories rather than your Obsidian instance. They cover profile selection, authentication/redirect isolation, native resources, pagination/revision races, publication safety, configuration/path validation and TeX anchor geometry. They are not evidence of real-host rendering or a claim that CI is currently green. For host integration, export your own non-sensitive test drawing and inspect the actual results separately.

Contributions should preserve the stdlib-only runtime, source-preserving native export, explicit target selection and failure semantics. Include focused tests for behavior changes and update both READMEs when the public interface changes. Use [Conventional Commits](https://www.conventionalcommits.org/), for example `fix: reject ambiguous vault selection`, `feat: add export option`, or `docs: clarify host setup`. Do not commit private profiles, tokens, real vault exports or personal paths; sanitize diagnostic reports before opening an issue.

## License

[MIT](LICENSE) · Copyright (c) 2026 Bowen-0x00 contributors.

Independent companion tooling; not affiliated with Obsidian or upstream Excalidraw.
