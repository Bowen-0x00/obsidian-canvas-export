# Obsidian Canvas Export

**[English](README.md) · [简体中文](README.zh-CN.md)**

将手工编辑后的 Obsidian Excalidraw **实时画布导出为 PNG、SVG 和 PDF**，不重写源场景。既可用独立 CLI 导出单图，也可用 JSON 配置批量导出，并可选集成 LaTeX 文档与基于锚点的子图标题。

版本 **1.0.0** · Python **3.10+** · 运行时仅依赖标准库 · **MIT**

无需 AI 会话、MCP 客户端、绘图生成器、浏览器自动化，也不切换全局默认 vault。**必须已有配对且正在运行的 Obsidian 原生 Bridge**：这不是离线 `.excalidraw.md` 转换器。

## 1. 准备 Obsidian 宿主

导出器与图形渲染宿主需要分别安装：

1. 在目标 Obsidian Desktop vault 中安装并启用 [Obsidian Excalidraw-ymjr](https://github.com/Bowen-0x00/obsidian-excalidraw-plugin-ymjr)。**仅安装上游原版 Excalidraw 并不足够。**
2. 按配套项目的[快速开始](https://github.com/Bowen-0x00/obsidian-excalidraw-agent-skill#quick-start)及[连接、状态目录与远程设置指南](https://github.com/Bowen-0x00/obsidian-excalidraw-agent-skill/blob/main/skills/obsidian-excalidraw/references/agent-setup.md)完成设置。本导出器的兼容基线为 Bridge **0.13.8**、配套 launcher **0.10.8**；升级时请遵循配套项目的当前说明。
3. 保持 Obsidian 打开、目标 vault 已配对且 Bridge 正在运行。安装本导出器**不会**安装或升级宿主插件、配对 vault、授予权限或启动 Obsidian。

首次设置时，在**图形宿主的配套项目仓库目录**运行以下命令，不是在本导出器仓库中运行：

```sh
uv sync --frozen
uv run --frozen python launcher.py connect
uv run --frozen python launcher.py status
uv run --frozen python launcher.py doctor
```

必要时用 `connect --vault-name "VAULT_ID_OR_UNIQUE_NAME"` 选择实际返回的 vault。未自动启动时，在 Obsidian 中执行 `Agent-Drawing/mcp/Start-Agent-Drawing`，然后再次检查 `status`/`doctor`。`launched:false` 不表示 Bridge 已启动。配套项目有自己的 Python/uv 要求，与本导出器的 Python 3.10+ 要求分开。

远程客户端应遵循配套项目的宿主侧配对、部署与 SSH loopback 隧道流程，并保持隧道运行。远程客户端使用本机已有的私有配对记录，而不是扫描宿主文件系统，也不要对桌面 vault 路径执行远程 `connect`。

**PDF 还要求宿主已启用并授权 Excalidraw Extras PDF 组件。** PNG/SVG 不需要 Extras PDF。可选 LaTeX 构建需要客户端安装 [Tectonic](https://tectonic-typesetting.github.io/)；仅导出图片不需要 TeX。

## 2. 安装导出器

直接从公开 GitHub 仓库安装；以下命令**不假设已在 PyPI 发布**。Git 安装方式需要 Git 和 Python 3.10+。任选一种即可。

### pipx——推荐

先安装 [pipx](https://pipx.pypa.io/stable/installation/)，然后运行：

```sh
pipx install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --version
```

### uv tool

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后运行：

```sh
uv tool install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --help
```

如果 shell 找不到命令，请完成安装工具的 PATH 设置（`pipx ensurepath` 或 `uv tool update-shell`），然后重新打开 shell。

### Python 虚拟环境

不使用 pipx 或 uv 的 POSIX shell 示例：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/Bowen-0x00/obsidian-canvas-export.git'
canvas-export --help
```

Windows 请使用虚拟环境的 `Scripts` 目录及对应激活命令。Windows 运行行为尚未验证；另见下文的符号链接权限要求。

### 从 checkout 直接运行

此方式也可获得示例 JSON 与 TeX 文件：

```sh
git clone https://github.com/Bowen-0x00/obsidian-canvas-export.git
cd obsidian-canvas-export
python3 -m canvas_export --help
./bin/canvas-export --help
```

checkout 入口无需安装 Python 包。开发时可在虚拟环境中执行 `python -m pip install -e .` 进行可编辑安装。`canvas-export`、`python -m canvas_export` 和 `bin/canvas-export` 三个入口提供相同 CLI。

## 3. 第一次导出

先列出客户端的配对记录，再选择自己的 vault。以下 `Research` 与画布路径均为**示例**，请换成自己的值。

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

尚未设置 Extras PDF 时，先导出 PNG/SVG；宿主准备好后，再向 `--format` 加入 `pdf`。**省略 `--format` 时默认导出 PDF。** 建议先保存画布，导出及可选编译期间不要继续编辑：工具读取宿主的实时场景，不是客户端旧 JSON 副本。

成功后在 `exports/latest/` 查看产物。`latest` 是指向带时间戳构建目录的符号链接，不是原地覆盖的目录。

### 命令与参数

| 命令 | 用途 |
| --- | --- |
| `canvas-export vaults [--json] [--state-dir PATH]` | 列出本地配对记录，不含凭据；不检查宿主是否在线 |
| `canvas-export styles [--json]` | 解释三种原生导出主题；无需连接宿主 |
| `canvas-export export --canvas PATH ...` | 导出一个或多个显式指定的 vault 相对画布路径 |
| `canvas-export build --config project.json ...` | 批量导出 JSON 项目，并可选编译 TeX 文档 |
| `canvas-export --version` / `--help` | 显示版本或帮助；各子命令也支持 `--help` |

`export` 与 `build` 共用以下参数：

| 参数 | 含义／默认值 |
| --- | --- |
| `--vault NAME_OR_ID` | 按唯一名称、ID 或配对记录中的宿主 vault 路径选择目标 |
| `--connection ID_OR_PATH` | 按连接 ID 或现有私有配对 JSON 文件选择目标，仅本次生效 |
| `--state-dir PATH` | 可重复；替代默认配对记录发现目录 |
| `--format pdf svg png` | 一种或多种格式；可重复；自动去重；默认 `pdf` |
| `--style original\|light\|dark` | 原生临时导出主题；默认 `original` |
| `--padding NUMBER` | 非负画布单位留白；默认 `20` |
| `--scale NUMBER` | 正数 PNG 请求缩放；默认 `1.5`；宿主像素上限可能使其降低 |
| `--out PATH` | 客户端输出根目录；默认 `output` |
| `--latest NAME` | 最新成功符号链接名称；默认 `latest`；不能为 `builds` |
| `--timeout SECONDS` | 每次原生 HTTP 请求的正数超时秒数；默认 `180` |
| `--json` | stdout 输出可机读的成功结果；进度与错误写入 stderr |

`export` 可重复 `--canvas` 导出同一选定 vault 中的多图。路径使用 `/`，始终是 **vault 相对路径**，不是客户端路径或宿主绝对路径；绝对路径和 `..` 会被拒绝。`--name` 仅允许用于单图。否则根据文件名生成 basename，将标点与空格转换为 `_`，保留字母和数字，包括非 ASCII 字母。重名会报错，请分别指定名称导出，或改用批量配置。`build` 必须提供 `--config`；`--no-latex` 同时跳过 wrapper 生成与 TeX 编译。

### 私有配对记录与目标选择

```sh
canvas-export vaults --json
canvas-export export \
  --connection CONNECTION_ID_FROM_VAULTS \
  --canvas 'Drawings/My Figure.excalidraw.md' --format png --out ./exports

# 配套项目使用自定义私有状态目录时：
canvas-export vaults --state-dir ~/.config/canvas-bridge-state
canvas-export export \
  --state-dir ~/.config/canvas-bridge-state --vault Research \
  --canvas 'Drawings/My Figure.excalidraw.md' --format png
```

只有一个配对候选时可省略选择参数。有多个候选，包括同名 vault 时，必须明确选择。`--connection` 与 `--vault` 同时给出时必须匹配。未知目标不会退回其他 vault，选择也不会改写配套项目全局的 `connection.json`。

默认仅从以下目录读取 `connection.json` 与 `connections/*.json`：

- 当前平台的 `ObsidianExcalidrawAgent` 默认数据目录（Linux：`${XDG_DATA_HOME:-~/.local/share}/obsidian-excalidraw-agent`；macOS：`~/Library/Application Support/ObsidianExcalidrawAgent`；Windows：`%LOCALAPPDATA%/ObsidianExcalidrawAgent`）。
- `~/.local/share/obsidian-excalidraw-agent-remote/state`。
- 已设置的 `EXCALIDRAW_AGENT_STATE_DIR`，与默认目录一同查找。

显式 `--state-dir` 会替代上述发现根目录。工具不递归扫描 vault、不执行配对，也不读取其他机器的注册目录。`vaults` 列出的是本地配对记录，并不保证宿主在线；导出时会鉴权并核对 host/vault 身份。

配对文件必须保持私密：不要把 bearer token 放进项目 JSON，也不要提交状态目录。连接仅允许 loopback HTTP，禁用代理与重定向。JSON 结果不含 bearer token 或 context token，但配对元数据、画布快照、manifest 和日志仍可能暴露画布内容或本地路径；分享前请检查。

### 主题不是重新设计

| 样式 | 行为 |
| --- | --- |
| `original` | 保留源画布主题与原生属性 |
| `light` | 在临时导出工作区请求宿主的原生浅色主题 |
| `dark` | 在临时导出工作区请求宿主的原生深色主题 |

这些**不是**论文／幻灯片模板、字体替换、线宽预设或布局转换。浅深主题转换及显式图元颜色的处理遵循宿主原生行为。不会重写源主题、文字、坐标或图形。需要不同设计时，请在 Obsidian 中编辑画布。

## 批量配置

以 [examples/export.json](examples/export.json) 为模板，替换 vault／画布占位值。例如，将以下内容保存为 `project.json`：

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

**优先级：CLI 覆盖 > 单图字段 > 项目字段 > 内置默认值。** 未知 JSON 字段会报错，不会悄悄忽略。

| 项目字段 | 含义／默认值 |
| --- | --- |
| `version` | 配置版本 `1`，可省略 |
| `vault`, `connection` | 与 CLI 相同的目标选择器；不放凭据值 |
| `formats` | `pdf`、`svg`、`png` 的非空数组；默认 `["pdf"]` |
| `style` | `original`、`light` 或 `dark`；默认 `original` |
| `padding`, `scale` | 有限非负留白／有限正数 PNG 缩放；默认 `20`、`1.5` |
| `output_dir` | 输出根目录；默认 `output` |
| `latest` | 最新成功链接名称；默认 `latest`；不能为 `builds` |
| `figures` | 必须为非空对象；key 是不含扩展名的输出 basename |
| `latex` | 可选 TeX 构建配置，见下文 |

每图必须提供 `file`，可覆盖 `formats`、`style`、`padding`、`scale`。可选 `macro`、`panel_scope`、`panels` 仅用于 TeX wrapper。basename 与 `latest` 使用字母、数字、`_`、`-`，以字母或数字开头；TeX 图文件请使用 ASCII basename。

配置中的本地路径，包括输出、TeX 输入和连接文件路径，均相对 JSON 所在目录（也可用本地绝对路径）。CLI `--out` 与 CLI 连接文件路径相对调用时的工作目录。画布路径始终相对 vault。不要为了缩短相对路径而把私有配对文件放进公开项目。

## 可选 LaTeX 集成

[examples/export-with-latex.json](examples/export-with-latex.json) 与随附的 [examples/paper.tex](examples/paper.tex) 构成最小示例。替换 vault／画布占位值，让 JSON 与 `paper.tex` 保持同目录，然后在 checkout 中运行：

```sh
canvas-export build --config examples/export-with-latex.json
```

这会导出原生图 PDF，生成含 `\ExampleGraphic` 的 `canvas_graphics.tex`，并在独立构建暂存目录中将 `paper.tex` 编译为 `paper.pdf`。**此示例不需要 logicalId 锚点。** Tectonic 必须在 `PATH` 中，或位于可执行的 `~/.local/bin/tectonic`；首次编译可能下载 TeX 依赖。导出图 PDF 仍然要求 Extras PDF。

集成其他文档时可参考：

```json
"latex": {
  "source": "paper.tex",
  "inputs": ["references.bib", {"source": "styles/custom.cls", "target": "custom.cls"}],
  "wrapper": "canvas_graphics.tex",
  "output": "paper.pdf"
}
```

这是配置片段；只声明自己确实拥有的额外输入文件。主文件以原 basename 复制；`output` 必须等于该 basename 换成 `.pdf`。`inputs` 默认为 `[]`，接受相对路径字符串或 `{source,target}` 对象。目标必须是安全相对路径；缺少文件、目标重复或与生成文件冲突都会报错。只复制显式声明的文件，不会复制整棵文档目录。`wrapper` 默认为 `canvas_graphics.tex`。

设置 `"macro": "ExampleGraphic"` 的图必须在 formats 中包含 `pdf`。主文档加载 `graphicx`、带 `percent` 选项的 `overpic`，以及用于面板超链接的 `hyperref`，然后 `\input{canvas_graphics.tex}`。按文档需要在 `figure` 或 `figure*` 环境调用 `\ExampleGraphic`。图宽为 `\textwidth`；这不是自动单栏排版引擎。Figure 编号、caption 与文档排版仍由文档类管理。

### 可选子图标题与 logicalId 锚点

普通手绘图完全可以不用此机制。若要在 TeX 中添加 `(a)`、`(b)` 标题，而不向画布重复写入标题，可为图添加：

```json
"macro": "ArchitectureGraphic",
"panel_scope": "Architecture",
"panels": [
  {"label": "fig:architecture_a", "title": "System organization", "anchor": "system_boundary", "dx": 0, "dy": -40}
]
```

- 每个 `anchor` 必须唯一匹配某个未删除、未旋转图元的 `customData.agentDiagram.logicalId`，**不是**原生 element ID 或文件名。本导出器不创建这些元数据；请使用已有且有意设置的锚点，或省略 panels。
- `dx`／`dy` 是相对锚点左上角的有限**画布单位**偏移：x 正方向向右，y 正方向向下；`dy: -40` 将标题放在锚点上方。定位使用本次源场景边界与导出留白重新计算，支持负坐标，不依赖 PNG 像素或 PDF point。
- 移动子图时应一起移动锚点。缺失、重复或旋转锚点会报错，不沿用旧坐标。导出器不推断子图归属，重排或缩放内容后仍需目视最终 PDF。
- 宏名与面板 scope 只能包含英文字母，且在 wrapper 内唯一；label 也必须唯一，仅用 ASCII 字母／数字、`:`、`_`、`-`。保留的辅助宏名会被拒绝。标题作为普通文字转义，不执行其中的 TeX。
- 子图标题使用 9 TeX pt 的无衬线粗体，字母编号按图计数，超链接身份按 scope 区分；不覆盖文档整体字体和字号。
- `--no-latex` 同时跳过 wrapper 和编译，适用于临时将格式覆盖为 PNG-only 的情况。

## 输出、源安全与限制

成功批次的目录类似如下（仅生成请求的格式）：

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
    canvas_graphics.tex         # 仅配置 latex 时
    paper.pdf / build.log        # 仅配置 latex 时
```

- 每幅画布固定文件与 revision；读取、分页、导出及最终核验必须一致。构建中编辑会导致失败，不会自动重试或混合不同 revision。
- 工具调用原生 status/bind/query/summary/export/render 路由，不执行 create/apply 场景修改。宿主可能打开指定画布或使用临时导出工作区，但不会重画或覆盖源场景。
- 全部导出、可选 TeX 编译与 revision 检查成功后，才会原子更新 `latest`。不会覆盖该位置已有的真实文件／目录。失败暂存目录（`.pending-*`）保留用于诊断；发布末期失败可能保留带时间戳的构建目录。上一次成功链接不变。
- 原子发布要求**操作系统允许创建符号链接**。Windows 可能需要开发者模式或管理员权限；Windows 运行支持尚未验证。工具没有通过复制来替代符号链接的降级方案。
- `.native.json` 是图元检查快照，**不是包含全部嵌入资源的完整可移植 `.excalidraw.md` 备份**。可编辑真源仍在 vault 中。
- `.exports.json` 记录渲染方式、主题、revision、SHA256、边界、留白、资源计数及实际缩放／像素元数据。批次 manifest 记录图产物与可选集成 PDF 的哈希。
- 当前 Bridge PNG 最长边限制为 **1600 像素**，总像素限制为 **4,000,000**。`--scale` 请求值不保证实现；请检查 `requested_scale`、`actual_scale`、`pixel_width`、`pixel_height`、`scale_limited`。请求高缩放不等于已得到高 DPI。
- SVG/PDF 保留原生矢量路径，但嵌入图片、HTML 捕获与部分效果仍可能是位图，**不保证全矢量**。
- 资源缺失、PDF 权限／依赖缺失、鉴权失败、身份不匹配或宿主离线均明确报错；不会使用截图、Pillow 或 Matplotlib 制作替代 PDF。
- 成功状态为 `exported_not_independently_reviewed`。导出成功**不授予或继承**独立审查 PASS、科学正确性或论文排版验收结论。
- 构建与诊断目录不自动清理，请自行管理保留策略。宿主字体／插件、SSH 设置、重新设计、语义审查及文档模板转换不在工具范围内。

## 故障排查

| 现象 | 检查方向 |
| --- | --- |
| 没有配对记录 | 在目标图形宿主完成配套设置；选择正确的客户端状态目录或 `--connection` 私有文件路径。`vaults` 不执行配对或启动宿主。 |
| vault 歧义／选错目标 | 使用实际返回的连接 ID。两个选择器必须匹配，不要通过复制 token 到项目来绕过失败。 |
| 拒绝连接、超时、鉴权或身份错误 | 保持 Bridge／远程 SSH 隧道运行；在配套仓库运行 `status` 和 `doctor`。按其文档修复配对并核对 host/vault。`--timeout` 仅修改请求超时，不能修复配对或授权。 |
| PDF 导出失败 | 在宿主启用并授权兼容的 Extras PDF，或改用 `--format png svg`。安装客户端 PDF 库不能修复宿主依赖。 |
| 图片／字体缺失或原生资源不完整 | 在 Obsidian 宿主恢复资源／字体，并在源画布检查。导出器不替换缺失内容。 |
| revision 变化 | 停止编辑、保存画布后重试；不会通过自动重试掩盖并发编辑。 |
| 缺少 Tectonic／TeX 编译失败 | 安装 Tectonic 或使用 `--no-latex`；检查声明的输入及保留的 `build.log`（如已开始编译）。首次下载依赖可能需要网络。 |
| 符号链接权限不足／latest 路径已存在 | 使用允许符号链接的输出位置；自行移走目标链接位置属于你的真实文件／目录，不要盲目删除无关目录。 |
| PNG 太小／深色主题效果不同 | 查看实际像素与缩放元数据及原生主题行为；`--scale` 无法突破宿主上限，主题也不是样式重写。 |

## 开发与贡献

在 checkout 中运行标准库测试：

```sh
python3 -m unittest discover -s tests -v
```

测试使用本地 HTTP fixture 与临时目录，不连接你的 Obsidian。覆盖配对选择、鉴权／重定向隔离、原生资源、分页／revision 竞争、发布安全、配置／路径校验与 TeX 锚点几何。这不是实时宿主渲染证据，也不表示当前 CI 已通过。宿主集成请另用自己的非敏感测试画布实际导出并检查结果。

贡献应保持运行时仅用标准库、原生导出不修改源场景、显式目标选择及明确失败语义。行为变更请加入针对性测试；公开接口变化时同步更新两份 README。提交采用 [Conventional Commits](https://www.conventionalcommits.org/)，例如 `fix: reject ambiguous vault selection`、`feat: add export option`、`docs: clarify host setup`。不要提交私有配对记录、token、真实 vault 导出或个人路径；提交 issue 前先清理诊断信息。

## 许可证

[MIT](LICENSE) · Copyright (c) 2026 Bowen-0x00 contributors.

独立配套工具，与 Obsidian 或上游 Excalidraw 无隶属关系。
