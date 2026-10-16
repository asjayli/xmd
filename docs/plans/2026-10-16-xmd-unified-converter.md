# xmd 统一文件转 Markdown 工程 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 youdao-note-convert（散文件 PDF 族转换）与 LakebookConverter（语雀 .lakebook 容器转换）合并为统一的"任意源 → Markdown"批量转换工程 xmd。

**Architecture:** 统一任务流水线：walker 扫描分类 → expander 展开容器（.lakebook → N 个虚拟任务）→ preprocess（镜像目录 + 确定性去重）→ 进程池并行按 category 路由到后端 → 统一报告（convert.log / need-review.csv / summary.json）。

**Tech Stack:** Python ≥3.11（本机 3.14.5）、markitdown、pymupdf、markdownify、beautifulsoup4、pyyaml、requests、pytest；setuptools src 布局。

**Spec:** `docs/specs/2026-10-16-xmd-unified-converter-design.md`（本计划从 spec 展开，执行者须同时阅读两者）

## Global Constraints

- Python ≥ 3.11；venv 位于 `.venv`，测试命令统一 `.venv/bin/pytest -q`
- **Git 提交信息不加 Co-Authored-By**（用户规则，覆盖默认归属行为）
- **迁移时保留源文件的块注释与行内注释**，只改需要改的部分，不做全文件重写
- 源仓库只读：`/data/repository/YoudaoNoteData/youdao-note-convert` 与 `/data/repository/yuque/LakebookConverter` 不做任何修改
- shell 中破坏性命令单独执行；如需删除文件用 `srm`（绝对路径 + `--exec`），不用 `rm`
- 每任务遵循 红→绿→提交；任务内测试全绿才进入下一任务
- 通用迁移重命名配方（各任务引用，以下简称"重命名配方"）：
  ```bash
  # 第一步：包名整体替换
  grep -rl 'youdao_note_convert' <目标文件...> | xargs sed -i 's/youdao_note_convert/xmd/g'
  # 第二步：converter 模块拆分修正：ConvertError/ConvertResult/Converter → xmd.model；
  #         MarkdownConverter → xmd.backends.markitdown_backend；
  #         auto_converter/mineru_converter/pdf_inspector_converter → xmd.backends.auto/mineru/pdf_inspector。
  #         grep 检出残留 import 后逐文件手工修正。
  ```
- 源 → 目标模块映射表（迁移任务统一遵循）：

  | 源模块（youdao_note_convert.*） | 目标模块（xmd.*） |
  |---|---|
  | classifier / walker / writer / normalizer / router / image_extractor / runner / logging_setup | 同名 `xmd.*` |
  | converter 的 ConvertError / ConvertResult / Converter / Result / ResolvedTask / FileEntry / Category | `xmd.model`（ResolvedTask 更名 **Task**） |
  | converter 的 MarkdownConverter | `xmd.backends.markitdown_backend` |
  | auto_converter.AutoConverter | `xmd.backends.auto` |
  | mineru_converter.MinerUConverter | `xmd.backends.mineru` |
  | pdf_inspector_converter.PdfInspectorConverter | `xmd.backends.pdf_inspector` |

- LakebookConverter 源模块映射：`lakebook.utils.extract_tar/sanitize_file_name/pretty_md` → 拆入 `xmd/expanders/lakebook.py`（extract_tar）与 `xmd/writer.py`（pretty_md）；`lakebook.metadata` → `xmd/expanders/lakebook.py`；`lakebook.doc_converter` → `xmd/backends/lake_doc.py`；`lakebook.sheet_converter` → `xmd/backends/lake_sheet.py`；`lakebook.converter`（TOC 建树）→ `xmd/expanders/lakebook.py`
- 源工程路径缩写：`$YD = /data/repository/YoudaoNoteData/youdao-note-convert`，`$LB = /data/repository/yuque/LakebookConverter`

---

### Task 1: 工程骨架与 pyproject

**Files:**
- Create: `pyproject.toml`、`src/xmd/__init__.py`、`src/xmd/__main__.py`、`tests/conftest.py`、`tests/fixtures/`（复制）、`tests/test_smoke.py`

**Interfaces:**
- Produces: 包 `xmd`（版本 0.1.0）、可安装工程、fixtures 路径 fixture（后续所有测试依赖）

- [ ] **Step 1: 写 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "xmd"
version = "0.1.0"
description = "任意源（散文件/有道云笔记导出/语雀 .lakebook）→ Markdown 批量转换"
requires-python = ">=3.11"
dependencies = [
  "markitdown>=0.1.7",
  "openpyxl>=3.1",
  "python-pptx>=0.6.23",
  "python-docx>=1.1",
  "pymupdf>=1.24",
  "pandas>=2",             # markitdown 的 xlsx/xls converter 依赖
  "requests>=2.28",        # MinerU 在线 API + 语雀图片下载
  "markdownify>=1.2",      # 语雀 HTML → Markdown
  "beautifulsoup4>=4.12",  # 语雀 HTML 解析（LaTeX/图片）
  "pyyaml>=6",             # 语雀 TOC 解析
]

[project.optional-dependencies]
dev = ["pytest>=8"]
pdf-inspector = ["pdf-inspector"]   # 可选轻量纯文本后端

[project.scripts]
xmd = "xmd.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 写包骨架**

`src/xmd/__init__.py`：
```python
"""xmd：任意源 → Markdown 批量转换（散文件 + 容器归档统一任务模型）。"""
__version__ = "0.1.0"
```

`src/xmd/__main__.py`：
```python
from xmd.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 复制测试基座并写冒烟测试**

```bash
mkdir -p tests
cp -r $YD/tests/fixtures tests/fixtures
cp $YD/tests/conftest.py tests/conftest.py
```

`tests/test_smoke.py`：
```python
def test_package_importable():
    import xmd

    assert xmd.__version__ == "0.1.0"
```

- [ ] **Step 4: 建 venv 安装并跑测试**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```
Expected: 1 passed（test_smoke）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests
git commit -m "feat: xmd 工程骨架（pyproject/包结构/测试基座）"
```

---

### Task 2: model.py（统一数据模型）+ classifier.py

**Files:**
- Create: `src/xmd/model.py`、`src/xmd/classifier.py`
- Test: `tests/test_model.py`、`tests/test_classifier.py`（由 `$YD/tests/test_classifier.py` 迁移）

**Interfaces:**
- Produces: `Category`（含 LAKEBOOK/LAKE_DOC/LAKE_SHEET）、`ConvertError`、`ConvertResult(body, image_refs, handled_images, handled_output)`、`Converter` 协议 `convert(source, assets_dir, task)`、`FileEntry(rel_path, abs_path, category, mtime=None, meta={})`、`Task(entry, output_md, assets_dir, collision)`、`Result(rel_path, status, chars, images, error)`、`classify(path) -> Category`

- [ ] **Step 1: 写失败测试**

`tests/test_model.py`（新写）：
```python
from pathlib import Path

from xmd.model import Category, ConvertResult, FileEntry, Task


def test_convert_result_defaults():
    r = ConvertResult(body="x")
    assert r.image_refs == []
    assert r.handled_images is False
    assert r.handled_output is False


def test_file_entry_optional_fields_default():
    e = FileEntry(Path("a.pdf"), Path("/a.pdf"), Category.PDF)
    assert e.mtime is None
    assert e.meta == {}


def test_task_holds_entry_and_paths():
    e = FileEntry(Path("a.pdf"), Path("/a.pdf"), Category.PDF)
    t = Task(e, Path("/o/a.md"), Path("/o/a.assets"), False)
    assert t.entry is e and t.collision is False
```

`tests/test_classifier.py`：复制 `$YD/tests/test_classifier.py`，套用重命名配方；追加：
```python
def test_classify_lakebook(tmp_path):
    from xmd.classifier import Category, classify
    assert classify(tmp_path / "b.lakebook") is Category.LAKEBOOK
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_model.py tests/test_classifier.py -q`
Expected: FAIL（`No module named 'xmd.model'`）

- [ ] **Step 3: 实现**

`src/xmd/model.py`：
```python
"""统一数据模型：分类、条目、任务、结果与后端协议。

FileEntry 由 walker（散文件）与 expander（容器展开的虚拟任务）产出；
Task 由 runner.preprocess 解析输出路径后产出（原 youdao ResolvedTask 更名）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class Category(StrEnum):
    NOTE_PDF = "note_pdf"      # .note.pdf / .clip.pdf（有道笔记正文 + 网页剪藏）
    PDF = "pdf"                # .pdf（附件）
    DOC = "doc"                # .docx/.xlsx/.pptx
    MD = "md"                  # .md
    LAKEBOOK = "lakebook"      # .lakebook 容器（walker 产出，展开后消失）
    LAKE_DOC = "lake_doc"      # 展开后：语雀普通文档（虚拟任务）
    LAKE_SHEET = "lake_sheet"  # 展开后：语雀表格文档（虚拟任务）
    SKIP = "skip"              # .ppt(老二进制)/.mp3/.rar/.zip/其他


class ConvertError(Exception):
    """转换失败。错误信息含 MINERU_DAILY_LIMIT 标记时表 MinerU 每日额度耗尽（runner 即停）。"""


@dataclass
class ConvertResult:
    body: str
    image_refs: list[str] = field(default_factory=list)
    handled_images: bool = False   # True=后端已产出图片；False=runner 需 PDF 补抽
    handled_output: bool = False   # True=后端已自行落盘完整输出（lake_sheet），runner 跳过写盘与质量判定


@dataclass(frozen=True)
class FileEntry:
    """walker/expander 产出的待转换条目。

    散文件：rel/abs 指向源文件，mtime=None（process_one 现场 stat）。
    虚拟任务（lake_doc/lake_sheet）：abs 指向 tmp 内 doc json，mtime=归档 mtime，
    meta 携带 {title, url, download_image, sheet_format}。
    """
    rel_path: Path
    abs_path: Path
    category: Category
    mtime: float | None = None
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Task:
    """preprocess 解析后的执行任务（输出路径已含冲突去重结果）。"""
    entry: FileEntry
    output_md: Path
    assets_dir: Path
    collision: bool


@dataclass
class Result:
    rel_path: str
    status: str   # ok|skipped|error|need_review|copied|collision|empty|crash
    chars: int
    images: int
    error: str | None


class Converter(Protocol):
    """可插拔转换后端协议。task 供 lake_sheet 等需自行落盘的后端取输出路径。"""
    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult: ...
```

`src/xmd/classifier.py`（源 `$YD/src/youdao_note_convert/classifier.py` 整体迁移，追加 LAKEBOOK 分支）：
```python
"""按扩展名分类源文件。"""
from __future__ import annotations

from pathlib import Path

from xmd.model import Category

_DOC_EXTS = {".docx", ".xlsx", ".pptx"}
_SKIP_EXTS = {".ppt", ".mp3", ".wav", ".rar", ".zip", ".7z"}


def classify(path: Path) -> Category:
    name = path.name.lower()
    if name.endswith(".note.pdf") or name.endswith(".clip.pdf"):
        return Category.NOTE_PDF
    ext = path.suffix.lower()
    if ext == ".pdf":
        return Category.PDF
    if ext == ".lakebook":
        return Category.LAKEBOOK
    if ext in _DOC_EXTS:
        return Category.DOC
    if ext == ".md":
        return Category.MD
    return Category.SKIP
```
（`_SKIP_EXTS` 保留定义；源工程 classify 同样未直接引用它做判定，维持原状以保留注释与后续扩展。）

- [ ] **Step 4: 运行测试通过**

Run: `.venv/bin/pytest tests/test_model.py tests/test_classifier.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/xmd/model.py src/xmd/classifier.py tests/test_model.py tests/test_classifier.py
git commit -m "feat: 统一数据模型与分类器（含 lakebook 类别）"
```

---

### Task 3: normalizer + logging_setup 平移

**Files:**
- Create: `src/xmd/normalizer.py`、`src/xmd/logging_setup.py`
- Test: `tests/test_normalizer.py`（迁移）

**Interfaces:**
- Produces: `normalize(text: str) -> str`（CJK 归一）、`silence_pdfminer()`

- [ ] **Step 1: 迁移测试**

```bash
cp $YD/tests/test_normalizer.py tests/test_normalizer.py
```
套用重命名配方（仅 import 行变化）。

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/pytest tests/test_normalizer.py -q` → FAIL（无 xmd.normalizer）

- [ ] **Step 3: 逐字复制实现**

```bash
cp $YD/src/youdao_note_convert/normalizer.py src/xmd/normalizer.py
cp $YD/src/youdao_note_convert/logging_setup.py src/xmd/logging_setup.py
```
两个文件无 youdao_note_convert 内部 import，无需改动。

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest -q` → 全部 PASS
```bash
git add src/xmd/normalizer.py src/xmd/logging_setup.py tests/test_normalizer.py
git commit -m "feat: 迁移 CJK 归一与日志静音模块"
```

---

### Task 4: writer.py（两套 sanitize 合一 + 虚拟任务输出路径 + SKIP 保留原名）

**Files:**
- Create: `src/xmd/writer.py`
- Test: `tests/test_writer.py`（由 `$YD/tests/test_writer.py` 改写）

**Interfaces:**
- Consumes: `xmd.model.FileEntry/Category`
- Produces: `sanitize_filename(name)`（并集非法字符，空格保留）、`output_ext(entry) -> str`、`build_output_path(entry, output_root) -> Path`、`assets_dir_for(md) -> Path`、`write_markdown(md, title, body, image_refs)`、`copy_skip(src, dst)`、`pretty_md(text) -> str`（迁自 lakebook.utils）

- [ ] **Step 1: 改写测试（含新增用例）**

`tests/test_writer.py` 全文：
```python
from pathlib import Path

from xmd.model import Category, FileEntry
from xmd.writer import (
    assets_dir_for,
    build_output_path,
    copy_skip,
    output_ext,
    pretty_md,
    sanitize_filename,
    write_markdown,
)


def _e(rel: str, cat: Category, meta: dict | None = None) -> FileEntry:
    return FileEntry(Path(rel), Path("/src") / rel, cat, meta=meta or {})


def test_sanitize_halfwidth_illegal():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_fullwidth_illegal():
    assert sanitize_filename("a：b？c＊d") == "a_b_c_d"


def test_sanitize_brackets_to_underscore():
    # 设计文档 D1：括号/花括号（半角+全角）→ _，防 md 图片链接在首个 ) 处截断
    assert sanitize_filename("报告(2024)[1]{a}（b）") == "报告_2024__1__a__b_"


def test_sanitize_keeps_chinese_and_space():
    assert sanitize_filename("TCP 三次握手.txt") == "TCP 三次握手.txt"


def test_build_output_note_pdf_strips_both_ext():
    assert build_output_path(_e("子目录/笔记.note.pdf", Category.NOTE_PDF), Path("/out")) \
        == Path("/out/子目录/笔记.md")


def test_build_output_clip_pdf_strips_both_ext():
    assert build_output_path(_e("a/x.clip.pdf", Category.NOTE_PDF), Path("/out")) == Path("/out/a/x.md")


def test_build_output_plain_pdf():
    assert build_output_path(_e("a/x.pdf", Category.PDF), Path("/out")) == Path("/out/a/x.md")


def test_build_output_docx():
    assert build_output_path(_e("a/x.docx", Category.DOC), Path("/out")) == Path("/out/a/x.md")


def test_build_output_skip_preserves_name():
    # 修正源工程缺陷：SKIP 原样复制须保留原名与扩展（源工程误落为 .md 名）
    assert build_output_path(_e("a/b.mp3", Category.SKIP), Path("/out")) == Path("/out/a/b.mp3")


def test_build_output_lake_doc_virtual_tree():
    e = _e("书/章/React", Category.LAKE_DOC, {"sheet_format": "csv"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/章/React.md")


def test_build_output_lake_sheet_csv():
    e = _e("书/数据表", Category.LAKE_SHEET, {"sheet_format": "csv"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/数据表.csv")


def test_build_output_lake_sheet_sheet_plus_is_md():
    e = _e("书/数据表", Category.LAKE_SHEET, {"sheet_format": "sheet"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/数据表.md")


def test_output_ext_matrix():
    assert output_ext(_e("a.pdf", Category.PDF)) == ".md"
    assert output_ext(_e("s", Category.LAKE_SHEET, {"sheet_format": "csv"})) == ".csv"
    assert output_ext(_e("s", Category.LAKE_SHEET, {"sheet_format": "sheet"})) == ".md"
    assert output_ext(_e("s", Category.LAKE_DOC)) == ".md"


def test_assets_dir_sibling():
    assert assets_dir_for(Path("/out/子目录/笔记.md")) == Path("/out/子目录/笔记.assets")


def test_write_markdown_no_images(tmp_path):
    md = tmp_path / "n.md"
    write_markdown(md, "标题", "正文", [])
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# 标题\n\n")
    assert "正文" in text
    assert "笔记配图" not in text


def test_write_markdown_with_images(tmp_path):
    md = tmp_path / "n.md"
    refs = ["./n.assets/img_001.png", "./n.assets/img_002.jpg"]
    write_markdown(md, "T", "B", refs)
    text = md.read_text(encoding="utf-8")
    assert "## 笔记配图" in text
    assert "![img_001](./n.assets/img_001.png)" in text


def test_copy_skip(tmp_path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"xxx")
    dst = tmp_path / "out" / "a.mp3"
    copy_skip(src, dst)
    assert dst.read_bytes() == b"xxx"


def test_pretty_md_strips_trailing_and_blank_runs():
    assert pretty_md("a  \n\n\n\nb\n") == "a\n\nb"
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/pytest tests/test_writer.py -q` → FAIL

- [ ] **Step 3: 实现 `src/xmd/writer.py`**

```python
"""输出路径计算、文件名清理、md 落盘与 Markdown 美化。

文件名清理为两源并集（设计文档 D1）：\\ / : * ? " < > | 与半/全角括号花括号
→ _，空格保留（空格在各主流文件系统合法，Obsidian 友好）。
pretty_md 迁自 LakebookConverter utils（语雀 HTML→MD 输出的统一美化）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from xmd.model import Category, FileEntry

# 源工程并集：youdao 半/全角基础集 ∪ lakebook 括号花括号集（后者不含空格项）
_ILLEGAL = set('\\/:*?"<>|()[]{}') | set("＼／：＊？＂＜＞｜（）［］｛｝")


def sanitize_filename(name: str) -> str:
    return "".join("_" if c in _ILLEGAL else c for c in name)


def output_ext(entry: FileEntry) -> str:
    """输出扩展名：表格 csv 格式 → .csv，其余 → .md。"""
    if entry.category is Category.LAKE_SHEET and entry.meta.get("sheet_format") == "csv":
        return ".csv"
    return ".md"


def build_output_path(entry: FileEntry, output_root: Path) -> Path:
    """计算输出路径：镜像目录 + 清理文件名。

    散文件：剥离源后缀（.note.pdf/.clip.pdf 双扩展整体剥离）→ 补输出扩展名；
    SKIP：保留原文件名与扩展（原样复制）；虚拟任务（lake_*）：rel_path 即输出树
    （末段为标题），补输出扩展名。
    """
    if entry.category is Category.SKIP:
        parts = [sanitize_filename(p) for p in entry.rel_path.parent.parts]
        return output_root.joinpath(*parts) / sanitize_filename(entry.rel_path.name)
    ext = output_ext(entry)
    if entry.category in (Category.LAKE_DOC, Category.LAKE_SHEET):
        parts = [sanitize_filename(p) for p in entry.rel_path.parts]
        return output_root.joinpath(*parts[:-1]) / f"{parts[-1]}{ext}"
    name = entry.rel_path.name
    low = name.lower()
    if low.endswith(".note.pdf"):
        stem = name[: -len(".note.pdf")]
    elif low.endswith(".clip.pdf"):
        stem = name[: -len(".clip.pdf")]
    else:
        stem = entry.rel_path.stem
    parts = [sanitize_filename(p) for p in entry.rel_path.parent.parts]
    return output_root.joinpath(*parts) / f"{sanitize_filename(stem)}{ext}"


def assets_dir_for(output_md: Path) -> Path:
    """配图目录 = md 同级 f"{stem}.assets"；按需创建。"""
    return output_md.parent / f"{output_md.stem}.assets"


def write_markdown(output_md: Path, title: str, body: str, image_refs: list[str]) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"# {title}".strip(), "", body.strip()]
    if image_refs:
        parts += ["", "## 笔记配图", ""]
        for ref in image_refs:
            alt = Path(ref).stem
            parts.append(f"![{alt}]({ref})")
    output_md.write_text("\n".join(parts) + "\n", encoding="utf-8")


def copy_skip(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def pretty_md(text: str) -> str:
    """美化 Markdown：去行尾空白、压缩连续空行（迁自 lakebook.utils）。"""
    lines = [line.rstrip() for line in text.split("\n")]
    output = "\n".join(lines)
    for _ in range(50):
        output = output.replace("\n\n\n", "\n\n")
        if "\n\n\n" not in output:
            break
    return output
```

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_writer.py -q` → PASS
```bash
git add src/xmd/writer.py tests/test_writer.py
git commit -m "feat: 合并两套文件名清理与输出路径（虚拟任务/表格扩展名/SKIP 保名）"
```

---

### Task 5: walker.py（scan_input 支持文件输入）

**Files:**
- Create: `src/xmd/walker.py`
- Test: `tests/test_walker.py`（由 `$YD/tests/test_walker.py` 迁移 + 追加）

**Interfaces:**
- Consumes: `xmd.classifier.classify`、`xmd.model.FileEntry`
- Produces: `WalkResult(files: list[FileEntry], dirs: list[Path])`、`walk(source_root) -> WalkResult`、`scan_input(path) -> WalkResult`（文件或目录）

- [ ] **Step 1: 迁移测试并追加用例**

```bash
cp $YD/tests/test_walker.py tests/test_walker.py
```
套用重命名配方，追加：
```python
from xmd.classifier import Category
from xmd.walker import scan_input


def test_scan_input_single_file(tmp_path):
    p = tmp_path / "a.note.pdf"
    p.write_bytes(b"x")
    res = scan_input(p)
    assert len(res.files) == 1
    assert res.files[0].rel_path == Path("a.note.pdf")
    assert res.files[0].category is Category.NOTE_PDF
    assert res.dirs == []


def test_scan_input_lakebook_file(tmp_path):
    p = tmp_path / "b.lakebook"
    p.write_bytes(b"x")
    res = scan_input(p)
    assert res.files[0].category is Category.LAKEBOOK
```

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_walker.py -q` → FAIL

- [ ] **Step 3: 实现**

`src/xmd/walker.py`（源 walker 逐字迁移 + import 改 + 追加 scan_input）：
```python
"""递归遍历源目录，返回文件清单 + 全部目录（含空目录）。

scan_input 支持单文件输入（CLI 混合输入语义：文件 rel=文件名，目录 rel=相对根）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xmd.classifier import Category, classify
from xmd.model import FileEntry


@dataclass(frozen=True)
class WalkResult:
    files: list[FileEntry]
    dirs: list[Path]   # 相对 source_root，含空目录


def _hidden(part: str) -> bool:
    return part.startswith(".") and part not in (".", "")


def walk(source_root: Path) -> WalkResult:
    source_root = Path(source_root)
    files: list[FileEntry] = []
    dirs: list[Path] = []
    for p in sorted(source_root.rglob("*")):
        rel = p.relative_to(source_root)
        if any(_hidden(part) for part in rel.parts):
            continue
        if p.is_dir():
            dirs.append(rel)
        elif p.is_file():
            files.append(FileEntry(rel, p, classify(p)))
    return WalkResult(files, dirs)


def scan_input(path: Path) -> WalkResult:
    """单个输入（文件或目录）→ WalkResult；文件输入 rel=文件名。"""
    path = Path(path)
    if path.is_file():
        return WalkResult([FileEntry(Path(path.name), path, classify(path))], [])
    return walk(path)
```

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_walker.py -q` → PASS
```bash
git add src/xmd/walker.py tests/test_walker.py
git commit -m "feat: walker 迁移并支持单文件输入扫描"
```

---

### Task 6: router + image_extractor 平移

**Files:**
- Create: `src/xmd/router.py`、`src/xmd/image_extractor.py`
- Test: `tests/test_router.py`、`tests/test_image_extractor.py`（迁移）

**Interfaces:**
- Produces: `classify_pdf(path) -> tuple[str, str]`、`mineru_api_for(path) -> str`、`AGENT_MAX_PAGES/AGENT_MAX_MB`、`extract_images(pdf_path, assets_dir, min_size=16, force=False) -> list[ExtractedImage]`、`ImageError`、`ExtractedImage(rel_ref, page)`

- [ ] **Step 1: 迁移测试**

```bash
cp $YD/tests/test_router.py $YD/tests/test_image_extractor.py tests/
```
套用重命名配方。

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_router.py tests/test_image_extractor.py -q` → FAIL

- [ ] **Step 3: 复制实现并改 import**

```bash
cp $YD/src/youdao_note_convert/router.py src/xmd/router.py
cp $YD/src/youdao_note_convert/image_extractor.py src/xmd/image_extractor.py
```
两个文件均无 youdao_note_convert 内部 import（router 仅依赖 pymupdf；image_extractor 仅 pymupdf），无需改动。

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest -q` → 全部 PASS
```bash
git add src/xmd/router.py src/xmd/image_extractor.py tests/test_router.py tests/test_image_extractor.py
git commit -m "feat: 迁移 PDF 复杂度路由与抽图模块"
```

---

### Task 7: backends —— markitdown / pdf_inspector / mineru / auto

**Files:**
- Create: `src/xmd/backends/__init__.py`、`src/xmd/backends/markitdown_backend.py`、`src/xmd/backends/pdf_inspector.py`、`src/xmd/backends/mineru.py`、`src/xmd/backends/auto.py`
- Test: `tests/test_converter.py`（更名自 test_converter，迁移改写）、`tests/test_pdf_inspector_converter.py`、`tests/test_mineru_converter.py`、`tests/test_auto_converter.py`（迁移）

**Interfaces:**
- Consumes: `xmd.model.ConvertError/ConvertResult/Converter/Task`、`xmd.normalizer.normalize`、`xmd.router.mineru_api_for/classify_pdf`
- Produces: 四个后端类，`convert(abs_path, assets_dir, task=None) -> ConvertResult`（第三参可选——lake 后端才需要；旧 2 参调用兼容）

- [ ] **Step 1: 迁移测试并适配**

```bash
cp $YD/tests/test_converter.py tests/test_converter.py
cp $YD/tests/test_pdf_inspector_converter.py tests/test_pdf_inspector_converter.py
cp $YD/tests/test_mineru_converter.py tests/test_mineru_converter.py
cp $YD/tests/test_auto_converter.py tests/test_auto_converter.py
```
套用重命名配方后，再做以下精确修正：
- `tests/test_converter.py`：`from xmd.converter import ...` → `from xmd.backends.markitdown_backend import MarkdownConverter` + `from xmd.model import ConvertError, ConvertResult`
- `tests/test_auto_converter.py`：monkeypatch 目标 `xmd.auto_converter.*` → `xmd.backends.auto.*`；`from xmd.auto_converter import AutoConverter` → `from xmd.backends.auto import AutoConverter`
- `tests/test_mineru_converter.py`：`xmd.mineru_converter` → `xmd.backends.mineru`

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_converter.py tests/test_pdf_inspector_converter.py tests/test_mineru_converter.py tests/test_auto_converter.py -q` → FAIL

- [ ] **Step 3: 实现四个后端 + 包骨架**

`src/xmd/backends/__init__.py`：
```python
"""可插拔转换后端集合。

- PDF 族（markitdown / pdf-inspector / mineru / auto）：由 runner._build_converter
  按 ctx.backend 实例化（worker 单例）。
- 语雀族（lake_doc / lake_sheet）：runner._converter_for 按任务类别惰性创建
  （Task 11/12 引入，见 runner 集成任务）。
"""
```

`src/xmd/backends/markitdown_backend.py`（源 `$YD/src/youdao_note_convert/converter.py` 的 MarkdownConverter 部分迁移；模块 docstring 说明协议位置）：
```python
"""markitdown 文本提取后端（默认）。

ConvertError/ConvertResult/Converter 协议定义在 xmd.model（自源工程 converter.py
拆分：协议入 model，实现分置各后端模块）。
"""
from __future__ import annotations

from pathlib import Path

from markitdown import MarkItDown

from xmd.logging_setup import silence_pdfminer
from xmd.model import ConvertError, ConvertResult, Task
from xmd.normalizer import normalize


class MarkdownConverter:
    """markitdown 文本提取后端。不产图，handled_images=False。"""

    def __init__(self) -> None:
        silence_pdfminer()
        self._md = MarkItDown()

    def convert(self, abs_path: Path, assets_dir: Path,
                task: Task | None = None) -> ConvertResult:
        try:
            result = self._md.convert(str(abs_path))
        except Exception as e:  # markitdown 各类异常统一包装
            raise ConvertError(f"{type(e).__name__}: {e}") from e
        text = result.text_content or ""
        return ConvertResult(body=normalize(text), handled_images=False)
```

`src/xmd/backends/pdf_inspector.py`：`cp $YD/src/youdao_note_convert/pdf_inspector_converter.py src/xmd/backends/pdf_inspector.py`，将模块内两处 import 改为：
```python
from xmd.model import ConvertError, ConvertResult, Task
from xmd.normalizer import normalize
```
convert 签名改为 `def convert(self, abs_path: Path, assets_dir: Path, task: Task | None = None) -> ConvertResult:`

`src/xmd/backends/mineru.py`：`cp $YD/src/youdao_note_convert/mineru_converter.py src/xmd/backends/mineru.py`，import 改为：
```python
from xmd.model import ConvertError, ConvertResult, Task
from xmd.normalizer import normalize
from xmd.router import mineru_api_for
```
convert 签名改为 `def convert(self, abs_path: Path, assets_dir: Path, task: Task | None = None) -> ConvertResult:`（其余逐字保留，含全部注释与错误码分级逻辑）。

`src/xmd/backends/auto.py`（源 auto_converter.py 迁移）：
```python
"""auto 后端：per-file 智能路由（推荐质量场景）。

按 router.classify_pdf 探测复杂度：复杂（Type3/扫描/含光栅图）→ MinerU，简单 → markitdown。
MinerUConverter 内部再按 mineru_api_for 选 agent（免费）/precision（收费）。
质量优先 + 默认免费 + 复杂自动切收费。
"""
from __future__ import annotations

from pathlib import Path

from xmd.backends.markitdown_backend import MarkdownConverter
from xmd.backends.mineru import MinerUConverter
from xmd.model import ConvertResult, Task
from xmd.router import classify_pdf


class AutoConverter:
    def __init__(self, mineru_opts: dict | None = None) -> None:
        self._md = MarkdownConverter()
        self._mineru = MinerUConverter(**(mineru_opts or {}))   # api=auto 内部再路由

    def convert(self, abs_path: Path, assets_dir: Path,
                task: Task | None = None) -> ConvertResult:
        backend, _ = classify_pdf(abs_path)
        if backend == "mineru":
            return self._mineru.convert(abs_path, assets_dir)
        return self._md.convert(abs_path, assets_dir)
```

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_converter.py tests/test_pdf_inspector_converter.py tests/test_mineru_converter.py tests/test_auto_converter.py -q` → PASS
```bash
git add src/xmd/backends tests/test_converter.py tests/test_pdf_inspector_converter.py tests/test_mineru_converter.py tests/test_auto_converter.py
git commit -m "feat: 迁移 PDF 族四个转换后端（markitdown/pdf-inspector/mineru/auto）"
```

---

### Task 8: runner.py 迁移与模型适配

**Files:**
- Create: `src/xmd/runner.py`
- Test: `tests/test_runner.py`（由 `$YD/tests/test_runner.py` 迁移改写）、`tests/test_integration.py`（迁移）

**Interfaces:**
- Consumes: Task 2-7 全部产物
- Produces: `Ctx(force, min_chars, max_pdf_mb=20, backend='markitdown', backend_opts=None, no_image=False)`、`Result`（re-export 自 xmd.model）、`Task`（re-export）、`preprocess(files, output_root) -> list[Task]`、`process_one(task) -> Result`、`run(source, output, jobs=4, force=False, min_chars=50, max_pdf_mb=20, backend='markitdown', backend_opts=None, only=None, no_image=False, convert_sheets=True, sheet_format='csv') -> dict`

- [ ] **Step 1: 迁移测试并适配**

```bash
cp $YD/tests/test_runner.py tests/test_runner.py
cp $YD/tests/test_integration.py tests/test_integration.py
```
套用重命名配方后精确修正：
- import 块：`from xmd.classifier import Category`、`from xmd.model import ConvertResult, Task`（原 ResolvedTask→Task）、`from xmd.runner import Ctx, Result, _is_daily_limit, _worker_init, preprocess, process_one`（run 单独 import 保持原位置）、`from xmd.walker import FileEntry`
- 文件内所有 `ResolvedTask(` → `Task(`
- `test_process_one_empty_body_marks_empty` 中 monkeypatch 目标 `xmd.runner._get_converter` 不变；假 convert lambda 改为 `lambda self, p, a, t=None: ConvertResult(body="\xa0\n")`（新协议 3 参）
- `run(src, out, jobs=1, min_chars=10)` 调用不变（单 Path 输入兼容）

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_runner.py tests/test_integration.py -q` → FAIL

- [ ] **Step 3: 实现 `src/xmd/runner.py`**

以 `$YD/src/youdao_note_convert/runner.py` 为基线（保留全部注释），应用以下修改：

```python
"""批量调度：冲突解析、worker 单例、单文件流水线。

编排（run/_dispatch）在 Phase 7 追加。
后端可插拔：Ctx.backend 选 markitdown|pdf-inspector|mineru|auto。
MinerU 额度即停：_dispatch 识别 MINERU_DAILY_LIMIT 后停止提交剩余（贯彻不用优先额度）。
容器展开（.lakebook）由 Task 13 集成：expanders 在主进程展开为虚拟 FileEntry。
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path

from xmd.backends.auto import AutoConverter
from xmd.backends.markitdown_backend import MarkdownConverter
from xmd.backends.mineru import MinerUConverter
from xmd.backends.pdf_inspector import PdfInspectorConverter
from xmd.classifier import Category
from xmd.image_extractor import ImageError, extract_images
from xmd.model import (
    ConvertError,
    Converter,
    FileEntry,
    Result,
    Task,
)
from xmd.writer import assets_dir_for, build_output_path, copy_skip, write_markdown

# Result/Task 自 model 导入并 re-export，保持 runner 对外稳定接口
__all__ = ["Ctx", "Result", "Task", "preprocess", "process_one", "run"]


@dataclass(frozen=True)
class Ctx:
    force: bool
    min_chars: int
    max_pdf_mb: int = 20
    backend: str = "markitdown"          # markitdown|pdf-inspector|mineru|auto
    backend_opts: dict | None = None     # mineru/auto: {token,api,model,language,rate_per_min,...}
    no_image: bool = False               # True=PDF 不补抽图（语雀下载开关在任务 meta）


def preprocess(files: list[FileEntry], output_root: Path) -> list[Task]:
    """镜像路径计算 + 冲突去重：同 output 且来源不同 → 加 __<category>[__N] 后缀。"""
    used: dict[Path, Path] = {}   # output -> 源 abs_path
    tasks: list[Task] = []
    for e in files:
        out = build_output_path(e, output_root)
        ext = out.suffix   # .md / .csv / 原样复制文件的后缀
        collision = False
        if out in used and used[out] != e.abs_path:
            collision = True
            base = out.with_suffix("")  # /out/子/同名
            candidate = base.parent / f"{base.name}__{e.category.value}{ext}"
            n = 2
            while candidate in used:
                candidate = base.parent / f"{base.name}__{e.category.value}__{n}{ext}"
                n += 1
            out = candidate
        used[out] = e.abs_path
        tasks.append(Task(e, out, assets_dir_for(out), collision))
    return tasks


# worker 全局单例（经 _worker_init 建立；_get_converter 供单测惰性创建）
_WORKER_CTX: Ctx | None = None
_WORKER_CONV: Converter | None = None


def _build_converter(ctx: Ctx) -> Converter:
    """按 ctx.backend 实例化后端（延迟 import 避免循环/可选依赖）。"""
    if ctx.backend == "auto":
        return AutoConverter(ctx.backend_opts)
    if ctx.backend == "mineru":
        return MinerUConverter(**(ctx.backend_opts or {}))
    if ctx.backend == "pdf-inspector":
        return PdfInspectorConverter()
    return MarkdownConverter()


def _get_converter() -> Converter:
    global _WORKER_CONV
    if _WORKER_CONV is None:
        assert _WORKER_CTX is not None, "worker 未初始化"
        _WORKER_CONV = _build_converter(_WORKER_CTX)
    return _WORKER_CONV


def _worker_init(ctx: Ctx) -> None:
    global _WORKER_CTX, _WORKER_CONV
    _WORKER_CTX = ctx
    _WORKER_CONV = _build_converter(ctx)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def _is_pdf(category: Category) -> bool:
    return category in (Category.NOTE_PDF, Category.PDF)


def _size_mb(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def process_one(task: Task) -> Result:
    """单文件完整流水线（worker 进程内）。ctx 取 worker 全局。"""
    assert _WORKER_CTX is not None, "worker 未初始化"
    ctx = _WORKER_CTX
    rel = str(task.entry.rel_path)
    entry = task.entry

    # 续传：虚拟任务（lake_*）用归档 mtime，散文件现场 stat
    if entry.mtime is not None:
        src_mtime = entry.mtime
    else:
        src_mtime = entry.abs_path.stat().st_mtime
    if (not ctx.force
            and task.output_md.exists()
            and task.output_md.stat().st_mtime >= src_mtime):
        return Result(rel, "skipped", 0, 0, None)

    if entry.category is Category.SKIP:
        try:
            copy_skip(entry.abs_path, task.output_md)
            return Result(rel, "copied", 0, 0, None)
        except Exception as e:
            return Result(rel, "error", 0, 0, str(e))

    title = task.output_md.stem
    try:
        cres = _get_converter().convert(entry.abs_path, task.assets_dir, task)
    except ConvertError as e:
        return Result(rel, "error", 0, 0, str(e))

    # 后端已自行落盘完整输出（lake_sheet csv/sheet-plus）→ 跳过写盘与质量判定
    if cres.handled_output:
        status = "collision" if task.collision else "ok"
        return Result(rel, status, 0, 0, None)

    body = cres.body
    image_refs = list(cres.image_refs)
    if (not cres.handled_images) and _is_pdf(entry.category) \
            and not ctx.no_image \
            and _size_mb(entry.abs_path) <= ctx.max_pdf_mb:
        try:
            imgs = extract_images(entry.abs_path, task.assets_dir, force=ctx.force)
            image_refs += [im.rel_ref for im in imgs]
        except ImageError:
            pass  # 降级：仅文本

    write_markdown(task.output_md, title, body, image_refs)

    stripped = body.strip()
    if stripped == "":
        return Result(rel, "empty", 0, len(image_refs), None)
    status = "ok"
    if len(stripped) < ctx.min_chars and not image_refs:
        status = "need_review"
    if task.collision and status == "ok":
        status = "collision"
    return Result(rel, status, len(stripped), len(image_refs), None)
```

`_is_daily_limit / _append_log / _write_need_review / _summarize / _dispatch` 五个函数逐字保留源工程实现（仅模块内引用不变）。`run()` 修改为：

```python
def run(source, output: Path, jobs: int = 4,
        force: bool = False, min_chars: int = 50, max_pdf_mb: int = 20,
        backend: str = "markitdown", backend_opts: dict | None = None,
        only: set[str] | None = None, no_image: bool = False,
        convert_sheets: bool = True, sheet_format: str = "csv") -> dict:
    """source 支持单 Path 或 Path 列表（混合文件/目录输入）。

    容器展开集成由 Task 13 加入：当前实现遍历输入、镜像目录、preprocess、
    dispatch、报告（与源工程 run 行为一致，LAKEBOOK 条目暂按 SKIP 之外逻辑
    走 markitdown，Task 13 接管）。
    """
    inputs = list(source) if isinstance(source, (list, tuple)) else [source]
    inputs = [Path(i) for i in inputs]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "convert.log").write_text("", encoding="utf-8")  # 清空本轮日志

    from xmd.walker import scan_input
    walked_files: list[FileEntry] = []
    dirs: list[Path] = []
    for inp in inputs:
        w = scan_input(inp)
        walked_files += w.files
        dirs += w.dirs
    for d in dirs:  # 镜像全部目录（含空目录）
        (output / d).mkdir(parents=True, exist_ok=True)

    tasks = preprocess(walked_files, output)
    if only is not None:   # --retry-review：仅处理指定 rel_path 子集
        tasks = [t for t in tasks if str(t.entry.rel_path) in only]
    ctx = Ctx(force=force, min_chars=min_chars, max_pdf_mb=max_pdf_mb,
              backend=backend, backend_opts=backend_opts, no_image=no_image)
    start = time.perf_counter()
    results = _dispatch(tasks, ctx, jobs, output)
    duration = time.perf_counter() - start

    _write_need_review(output, results)
    summary = _summarize(results, duration)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
```
（注：上面 run 中 dirs 的初始化写作 `dirs: list[Path] = []` 常规形式，实现时去掉演示性占位循环，直接三段循环：scan 累加 files/dirs → mkdir dirs → preprocess。）

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest -q` → 全部 PASS（此时 test_runner/test_integration 绿）
```bash
git add src/xmd/runner.py tests/test_runner.py tests/test_integration.py
git commit -m "feat: 迁移统一编排 runner（Task 模型/handled_output/no_image/SKIP 保名）"
```

---

### Task 9: cli.py（阶段 1：混合输入 + 全量参数）

**Files:**
- Create: `src/xmd/cli.py`
- Test: `tests/test_cli.py`（由 `$YD/tests/test_cli.py` 迁移改写）

**Interfaces:**
- Consumes: `xmd.runner.run`、`xmd.walker.scan_input`
- Produces: `main(argv: list[str] | None = None) -> int`（console script `xmd`；返回码 0/2/3 语义同源工程）

- [ ] **Step 1: 迁移测试并适配**

```bash
cp $YD/tests/test_cli.py tests/test_cli.py
```
套用重命名配方后精确修正（全局替换规则）：
- `["--input", str(src), "--output", str(out),` → `[str(src), "-o", str(out),`（所有用例）
- `["--input", str(tmp_path / "nope"), "--output", ...]` → `[str(tmp_path / "nope"), "-o", ...]`
- monkeypatch 目标 `"xmd.cli.run"` 不变；fake_run 首参改名 `inputs`（签名 `def fake_run(inputs, output, **kwargs)`），断言不变
- 追加混合输入与容器选项用例：
```python
def test_cli_no_image_no_sheet_passed(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured.update(kwargs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    main([str(src), "-o", str(tmp_path / "o"),
          "--no-image", "--no-sheet", "--sheet-format", "sheet"])
    assert captured["no_image"] is True
    assert captured["convert_sheets"] is False
    assert captured["sheet_format"] == "sheet"


def test_cli_mixed_file_and_dir_inputs(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured["inputs"] = list(inputs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    main([str(src), str(tcp_pdf), "-o", str(tmp_path / "o")])
    assert captured["inputs"] == [src, tcp_pdf]
```

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_cli.py -q` → FAIL（No module named xmd.cli）

- [ ] **Step 3: 实现 `src/xmd/cli.py`**

以 `$YD/src/youdao_note_convert/cli.py` 为基线保留注释与 retry-review 全部逻辑（need-review.csv 读取、缺 CSV/空记录 rc=0、missing 源提示、异构 CSV 滤 None），修改：
- 参数定义：`--input/--output` → 位置参数 `inputs`（nargs="+")+ `-o/--output`
- 新增 `--no-image`、`--no-sheet`、`--sheet-format {csv,sheet}`（默认 csv）
- `run` 调用透传新参数；存在性校验改为逐 input 检查（任一不存在 → rc=3）
- retry-review 的源存在性预检遍历所有 inputs 的 scan_input

```python
"""argparse 入口：xmd <input...> -o <output>。

input 支持文件与目录混合（目录递归）；按扩展名自动路由转换类别。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xmd.runner import run


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xmd",
        description="任意源（散文件/有道云笔记导出/语雀 .lakebook）→ Markdown 批量转换",
    )
    p.add_argument("inputs", nargs="+", help="输入文件或目录（可混合多个）")
    p.add_argument("-o", "--output", required=True, help="Markdown 输出根目录")
    p.add_argument("--jobs", type=int, default=4, help="并发进程数（默认 4）")
    p.add_argument("--force", action="store_true", help="忽略续传，强制重转")
    p.add_argument("--min-chars", type=int, default=50, help="少于此且无图 → need-review")
    p.add_argument("--max-pdf-mb", type=int, default=20, help="超此大小 PDF 不抽图")
    p.add_argument("--retry-review", action="store_true",
                   help="仅重转上次 need-review.csv 记录的子集（隐含 --force；"
                        "缺 CSV 或无记录时直接退出 rc=0，不重转）")
    p.add_argument("--backend",
                   choices=["markitdown", "pdf-inspector", "mineru", "auto"],
                   default="markitdown", help="PDF 族转换后端（默认 markitdown）")
    p.add_argument("--no-image", action="store_true",
                   help="不落地图片：PDF 不抽图、语雀不下载（保留外链）")
    p.add_argument("--no-sheet", action="store_true", help="跳过语雀表格文档转换")
    p.add_argument("--sheet-format", choices=["csv", "sheet"], default="csv",
                   help="语雀表格输出格式（默认 csv；sheet=Obsidian Sheet Plus）")
    p.add_argument("--verbose", action="store_true", help="详细日志")
    # MinerU 在线 API（backend=mineru|auto 时生效；CLI Token 优先于 env MINERU_TOKEN）
    p.add_argument("--mineru-token", default=None,
                   help="MinerU Token（CLI 优先于 env MINERU_TOKEN；precision 必需；"
                        "建议用 env 避免落入 shell history）")
    p.add_argument("--mineru-api", choices=["auto", "precision", "agent"], default="auto",
                   help="MinerU API 档（auto 智能路由）")
    p.add_argument("--mineru-model", default="vlm", help="vlm|pipeline（仅 precision）")
    p.add_argument("--mineru-lang", default="ch", help="OCR 语言")
    p.add_argument("--mineru-poll-timeout", type=int, default=600, help="单任务轮询超时(秒)")
    p.add_argument("--mineru-max-pages", type=int, default=200,
                   help="Precision 单文件超此页数 skip（省额度）")
    p.add_argument("--mineru-rate", type=int, default=20, help="每分钟最多请求数（限流）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    inputs = [Path(x) for x in args.inputs]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        print(f"输入路径不存在: {', '.join(missing)}", file=sys.stderr)
        return 3
    out = Path(args.output)
    only = None
    if args.retry_review:   # 仅重转上次 need-review/empty/error/crash 子集（隐含 --force）
        nr = out / "need-review.csv"
        if not nr.exists():
            print("--retry-review: 无 need-review.csv，请先正常跑一遍生成", file=sys.stderr)
            return 0
        import csv as _csv
        with nr.open(encoding="utf-8-sig") as f:
            # row.get 滤掉短行 restval=None 与空串（异构/手工编辑 CSV 不 TypeError）
            only = {row["rel_path"] for row in _csv.DictReader(f) if row.get("rel_path")}
        if not only:
            print("--retry-review: need-review.csv 无记录，无需重转", file=sys.stderr)
            return 0
        from xmd.walker import scan_input
        exist = {str(e.rel_path) for i in inputs for e in scan_input(i).files}
        missing_src = sorted(only - exist)
        if missing_src:
            preview = "、".join(missing_src[:5])
            suffix = "…" if len(missing_src) > 5 else ""
            print(f"--retry-review: {len(missing_src)} 条记录源文件已不存在，忽略：{preview}{suffix}",
                  file=sys.stderr)
    backend_opts = None
    if args.backend in ("mineru", "auto"):
        backend_opts = {
            "token": args.mineru_token,
            "api": args.mineru_api,
            "model_version": args.mineru_model,
            "language": args.mineru_lang,
            "poll_timeout": args.mineru_poll_timeout,
            "max_pages": args.mineru_max_pages,
            "rate_per_min": args.mineru_rate,
        }
    try:
        summary = run(inputs, out, jobs=args.jobs,
                      force=args.force or args.retry_review,
                      min_chars=args.min_chars, max_pdf_mb=args.max_pdf_mb,
                      backend=args.backend, backend_opts=backend_opts, only=only,
                      no_image=args.no_image, convert_sheets=not args.no_sheet,
                      sheet_format=args.sheet_format)
    except Exception as e:  # 兜底
        print(f"运行失败: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest -q` → 全部 PASS
```bash
git add src/xmd/cli.py tests/test_cli.py
git commit -m "feat: 统一 CLI（混合输入/容器选项/MinerU 全参数）"
```

**阶段 1 完成标志：** youdao 侧能力全部在 xmd 跑绿（`pytest -q` 全绿，含 mineru/router/cli/integration）。

---

### Task 10: expanders/lakebook.py（容器展开器）

**Files:**
- Create: `src/xmd/expanders/__init__.py`、`src/xmd/expanders/lakebook.py`
- Test: `tests/test_lakebook_expander.py`（新写）

**Interfaces:**
- Consumes: `xmd.model.FileEntry/Category`
- Produces: `ExpandError`（xmd.expanders）、`expand_lakebook(archive: Path, *, download_image: bool = True, sheet_format: str = "csv") -> tuple[list[FileEntry], Path]`（返回虚拟条目 + tmp 目录，**调用方负责清理 tmp**）

- [ ] **Step 1: 写失败测试**

`tests/test_lakebook_expander.py`：
```python
"""lakebook 展开器测试：最小 tar fixtures 覆盖 uuid/level 双建树与异常路径。"""
import io
import json
import tarfile

import pytest
import yaml

from xmd.classifier import Category
from xmd.expanders import ExpandError, expand_lakebook


def make_lakebook(path, docs, toc, *, with_uuid=True, repo_id="123"):
    """构造最小 .lakebook tar：repo_id/$meta.json + <url>.json。

    docs: [{"url": "abc", "doc": {...}}]；toc: TOC 条目列表（dict）。
    """
    entries = []
    if not with_uuid:
        toc = [{k: v for k, v in t.items() if k not in ("uuid", "parent_uuid")} for t in toc]
    meta_inner = {"book": {"name": "测试库", "path": "https://y.com/u/test",
                           "tocYml": yaml.safe_dump(toc, allow_unicode=True)}}
    entries.append((f"{repo_id}/$meta.json", json.dumps({"meta": json.dumps(meta_inner)})))
    for d in docs:
        entries.append((f"{repo_id}/{d['url']}.json", json.dumps({"doc": d["doc"]})))
    with tarfile.open(path, "w") as tf:
        for name, data in entries:
            b = data.encode("utf-8")
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tf.addfile(ti, io.BytesIO(b))


DOC = {"type": "Doc", "format": "lake", "body": "<h1>T</h1>", "body_asl": ""}
SHEET = {"type": "Sheet", "format": "lakesheet", "body": "{}"}
TOC_UUID = [
    {"title": "第一章", "type": "TITLE", "url": "", "level": 0, "uuid": "t1"},
    {"title": "入门", "type": "DOC", "url": "d1", "level": 1, "uuid": "d1", "parent_uuid": "t1"},
    {"title": "数据表", "type": "DOC", "url": "s1", "level": 1, "uuid": "s1", "parent_uuid": "t1"},
]


@pytest.fixture
def lb(tmp_path):
    p = tmp_path / "mybook.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}, {"url": "s1", "doc": SHEET}], TOC_UUID)
    return p


def _expand(lb, **kw):
    entries, tmp = expand_lakebook(lb, **kw)
    import shutil
    try:
        return entries
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_expand_uuid_tree(tmp_path, lb):
    entries = _expand(lb)
    rels = [str(e.rel_path) for e in entries]
    assert rels == ["mybook/第一章/入门", "mybook/第一章/数据表"]
    cats = {str(e.rel_path): e.category for e in entries}
    assert cats["mybook/第一章/入门"] is Category.LAKE_DOC
    assert cats["mybook/第一章/数据表"] is Category.LAKE_SHEET


def test_expand_entry_meta_and_mtime(tmp_path, lb):
    entries = _expand(lb)
    e = entries[0]
    assert e.meta["title"] == "入门"
    assert e.meta["download_image"] is True
    assert e.meta["sheet_format"] == "csv"
    assert e.mtime == lb.stat().st_mtime
    assert (e.abs_path).exists()   # tmp 内 doc json


def test_expand_opts_propagate(tmp_path, lb):
    entries = _expand(lb, download_image=False, sheet_format="sheet")
    assert entries[0].meta["download_image"] is False
    assert entries[1].meta["sheet_format"] == "sheet"


def test_expand_level_fallback(tmp_path):
    p = tmp_path / "old.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}], TOC_UUID, with_uuid=False)
    entries = _expand(p)
    assert str(entries[0].rel_path) == "old/第一章/入门"


def test_expand_level_skip(tmp_path):
    # 跳级（0→2）多帧压栈对齐栈深，回退正确
    toc = [
        {"title": "A", "type": "TITLE", "url": "", "level": 0},
        {"title": "deep", "type": "DOC", "url": "d1", "level": 2},
        {"title": "B", "type": "DOC", "url": "d2", "level": 0},
    ]
    p = tmp_path / "skip.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}, {"url": "d2", "doc": DOC}], toc, with_uuid=False)
    entries = _expand(p)
    rels = [str(e.rel_path) for e in entries]
    assert rels == ["skip/A/+/deep", "skip/B"]   # 跳级空占位段折叠：见下注


def test_expand_corrupt_archive_raises(tmp_path):
    p = tmp_path / "bad.lakebook"
    p.write_text("not a tar")
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_symlink_member_rejected(tmp_path):
    p = tmp_path / "evil.lakebook"
    with tarfile.open(p, "w") as tf:
        ti = tarfile.TarInfo("123/lnk")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        tf.addfile(ti)
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_no_meta_raises(tmp_path):
    p = tmp_path / "nometa.lakebook"
    with tarfile.open(p, "w") as tf:
        b = b"{}"
        ti = tarfile.TarInfo("123/x.json"); ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_missing_doc_skipped(tmp_path):
    toc = [{"title": "T", "type": "DOC", "url": "gone", "level": 0}]
    p = tmp_path / "m.lakebook"
    make_lakebook(p, [], toc)
    assert _expand(p) == []
```

**注（test_expand_level_skip 断言）**：level 启发式对跳级用空串占位（源算法注释：中间缺失层级用空串占位，`os.path.join` 折叠空段）。`Path("skip", "A", "", "deep")` 在 POSIX 下为 `skip/A/deep`（空段折叠），因此断言应为 `["skip/A/deep", "skip/B"]`；实现时以实际 Path 语义修正断言（写测试时先跑一次确认空段行为，以 `str(e.rel_path)` 实际输出为准）。

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_lakebook_expander.py -q` → FAIL

- [ ] **Step 3: 实现**

`src/xmd/expanders/__init__.py`：
```python
"""容器展开器：容器归档 → 虚拟 FileEntry 列表（主进程执行）。

ExpandError 为全部展开器的统一异常；当前注册 .lakebook。
"""
from xmd.expanders.lakebook import ExpandError, expand_lakebook

__all__ = ["ExpandError", "expand_lakebook"]
```

`src/xmd/expanders/lakebook.py`（自 `$LB/lakebook/converter.py + metadata.py + utils.py` 重构，保留原算法注释）：
```python
"""语雀 .lakebook 容器展开：tar 安全解压 → $meta.json → TOC 建树 → 虚拟任务。

自 LakebookConverter 的 converter/metadata/utils 重构：展开器只产出
FileEntry（虚拟任务），不直接转换——转换由 backends/lake_doc|lake_sheet
在 worker 进程完成，从而共享 runner 的并行/续传/报告能力。

输出布局：<output>/<归档名去后缀>/<TOC 目录树>/<标题>（扩展名由 writer 按
category 决定；同名去重由 runner.preprocess 统一确定性后缀处理，设计文档 D5）。
"""
from __future__ import annotations

import json
import os
import random
import shutil
import tarfile
import tempfile
from pathlib import Path

import yaml

from xmd.classifier import Category
from xmd.model import FileEntry
from xmd.writer import sanitize_filename

# ── 语雀 TOC 条目 type 字段的可能值（迁自 lakebook.constants）─────────────────
TYPE_TITLE = "TITLE"   # 分组标题节点：仅用于在目录中显示层级，不对应实际文档
TYPE_DOC = "DOC"       # 普通富文本文档（HTML / Markdown 格式）
TYPE_SHEET = "Sheet"   # 表格文档（lakesheet 格式，类似 Excel）
META_JSON = "$meta.json"


class ExpandError(Exception):
    """容器展开失败（损坏/恶意归档、元数据缺失等）。"""


# ── tar 安全解压（迁自 lakebook.utils.extract_tar，校验逻辑逐字保留）──────────

def _extract_tar(tar_file: Path, target_dir: Path) -> None:
    """解压 tar 归档到目标目录。

    安全性：提取前逐一校验每个成员解析后的绝对路径必须落在 target_dir 之内
    （防止 `../` 或绝对路径形式的路径穿越），并拒绝符号链接 / 硬链接成员
    （防止通过链接指向归档外的敏感文件）。全部成员校验通过后才整体提取。
    """
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    base_dir = os.path.abspath(target_dir)

    with tarfile.open(tar_file) as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                raise ExpandError(f"拒绝提取可疑链接成员: {member.name}")
            member_path = os.path.abspath(os.path.join(base_dir, member.name))
            if os.path.commonpath([base_dir, member_path]) != base_dir:
                raise ExpandError(f"拒绝提取逃逸目标目录的成员: {member.name}")
        tar.extractall(target_dir)


# ── 元数据解析（迁自 lakebook.metadata.read_toc_and_book_info）────────────────

def _read_toc_and_book_info(repo_dir: Path) -> tuple[list, str]:
    """读取 $meta.json（双层 JSON + tocYml YAML），返回 (toc, book_name)。"""
    meta_file = json.loads((repo_dir / META_JSON).read_text(encoding="utf-8"))
    meta_str = meta_file.get("meta", "")
    if not isinstance(meta_str, str) or not meta_str.strip():
        raise ExpandError("$meta.json 缺少 meta 字段或该字段非字符串，无法解析知识库元数据")
    meta = json.loads(meta_str)
    book_info = meta.get("book", {})

    # TOC 以 YAML 字符串形式嵌在 tocYml 字段中；safe_load 关闭任意对象反序列化，
    # 空 TOC（返回 None）兜底为空列表
    toc_str = book_info.get("tocYml") or ""
    toc = yaml.safe_load(toc_str) or []

    book_name = (book_info.get("name") or "").strip()
    if not book_name:
        book_path = book_info.get("path") or ""
        if book_path:
            parts = book_path.rstrip("/").split("/")
            if parts:
                book_name = parts[-1]
    if not book_name:
        book_name = "未命名知识库"
    return toc, book_name


# ── 目录树还原（迁自 lakebook.converter，算法注释逐字保留）────────────────────

def _use_uuid_tree(toc: list) -> bool:
    """判断能否用 parent_uuid 精确还原目录树：
    要求所有带标题的 TITLE/DOC 条目都携带 uuid 字段。"""
    relevant = [
        it for it in toc
        if isinstance(it, dict)
        and it.get("type") in (TYPE_TITLE, TYPE_DOC)
        and str(it.get("title", "")).strip()
    ]
    return bool(relevant) and all(it.get("uuid") for it in relevant)


def _iter_doc_entries_by_uuid(toc: list):
    """用 parent_uuid 精确还原目录树，按深度优先顺序产出
    (祖先目录标题列表, 文档标题, url) 序列。（单遍遍历 + path_of 缓存，
    完整算法说明迁自源工程注释。）"""
    path_of: dict = {}
    for item in toc:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        uuid = item.get("uuid")
        parent_path = path_of.get(item.get("parent_uuid", ""), [])
        if item.get("type") == TYPE_DOC:
            url = str(item.get("url", ""))
            if url:
                yield parent_path, title, url
        if uuid:
            path_of[uuid] = parent_path + [title]


def _iter_doc_entries_by_level(toc: list):
    """用 level 字段启发式还原目录树（回退方案，缺少 uuid 的旧格式）。

    维护目录名栈，按相邻条目的 level 变化推入 / 弹出栈帧；跳级时按差值
    多帧压栈（空串占位，Path 拼接折叠空段）。"""
    last_level = 0
    last_title = ""
    path_stack: list = []
    for item in toc:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        current_level = item.get("level", 0)
        if current_level > last_level:
            diff = current_level - last_level
            path_stack = path_stack + [last_title] + [""] * (diff - 1)
        elif current_level < last_level:
            diff = min(last_level - current_level, len(path_stack))
            if diff:
                path_stack = path_stack[:-diff]
        if item.get("type") == TYPE_DOC:
            url = str(item.get("url", ""))
            if url:
                yield list(path_stack), title, url
        last_title = title
        last_level = current_level


# ── 展开主入口 ────────────────────────────────────────────────────────────────

def expand_lakebook(archive: Path, *, download_image: bool = True,
                    sheet_format: str = "csv") -> tuple[list[FileEntry], Path]:
    """展开单个 .lakebook → 虚拟 FileEntry 列表 + tmp 目录（调用方负责清理）。"""
    archive = Path(archive)
    tmp_dir = Path(tempfile.gettempdir()) / f"xmd_lakebook_{os.getpid()}_{random.randint(1000, 9999)}"
    try:
        _extract_tar(archive, tmp_dir)
        # tar 包内通常有一个根子目录，找到它作为 repo_dir
        repo_dir = next((Path(e.path) for e in os.scandir(tmp_dir) if e.is_dir()), None)
        if repo_dir is None:
            raise ExpandError("解压后未找到内容目录（格式无效）")
        toc, _book_name = _read_toc_and_book_info(repo_dir)

        book_dir = sanitize_filename(archive.name.removesuffix(".lakebook"))
        mtime = archive.stat().st_mtime
        entries: list[FileEntry] = []
        it = _iter_doc_entries_by_uuid(toc) if _use_uuid_tree(toc) else _iter_doc_entries_by_level(toc)
        for path_parts, title, url in it:
            raw = repo_dir / f"{url}.json"
            if not raw.exists():
                continue   # 原行为：文档文件缺失时警告并跳过该条目
            doc = json.loads(raw.read_text(encoding="utf-8")).get("doc", {})
            is_sheet = doc.get("type", "") == TYPE_SHEET or doc.get("format", "") == "lakesheet"
            cat = Category.LAKE_SHEET if is_sheet else Category.LAKE_DOC
            rel = Path(book_dir, *[p for p in path_parts if p], title)
            entries.append(FileEntry(
                rel, raw, cat, mtime,
                {"title": title, "url": url,
                 "download_image": download_image, "sheet_format": sheet_format}))
        return entries, tmp_dir
    except ExpandError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:   # 元数据损坏等 → 统一 ExpandError，tmp 兜底清理
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ExpandError(f"{type(e).__name__}: {e}") from e
```

**实现注意**：`rel = Path(book_dir, *[p for p in path_parts if p], title)` 滤掉空占位段（与源工程 `os.path.join` 折叠空段行为一致）；`_iter_doc_entries_by_level` 内空串占位保留（栈深对齐语义不变），仅最终拼 Path 时折叠。

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_lakebook_expander.py -q` → PASS（含跳级断言按实际 Path 语义确认）
```bash
git add src/xmd/expanders tests/test_lakebook_expander.py
git commit -m "feat: lakebook 容器展开器（tar 安全解压/TOC 双算法/虚拟任务）"
```

---

### Task 11: backends/lake_doc.py（语雀普通文档后端）

**Files:**
- Create: `src/xmd/backends/lake_doc.py`
- Test: `tests/test_lake_doc.py`（新写）

**Interfaces:**
- Consumes: `xmd.model.ConvertError/ConvertResult/FileEntry/Task`、`xmd.writer.pretty_md`
- Produces: `LakeDocBackend`（`convert(source, assets_dir, task) -> ConvertResult`）、`extract_latex_from_asl(body_asl) -> dict`、`replace_latex_images(html, latex_dict) -> str`、`html_to_markdown(html) -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_lake_doc.py`：
```python
"""lake_doc 后端测试：LaTeX 还原/代码块语言/图片提升/图片下载。"""
import json
import urllib.parse

import pytest
from bs4 import BeautifulSoup

from xmd.backends.lake_doc import (
    LakeDocBackend,
    extract_latex_from_asl,
    html_to_markdown,
    replace_latex_images,
)
from xmd.model import Category, FileEntry


def _card(src: str, code: str) -> str:
    val = "data:" + urllib.parse.quote(json.dumps({"src": src, "code": code}))
    return f'<card name="math" value="{val}"/>'


def _task(tmp_path, meta=None):
    return FileEntry(Path("b/标题"), tmp_path / "x.json", Category.LAKE_DOC,
                     meta={"title": "标题", "download_image": False, **(meta or {})})


def test_extract_latex_from_asl():
    asl = _card("https://cdn/1.png", "E=mc^2")
    d = extract_latex_from_asl(asl)
    assert d == {"https://cdn/1.png": "E=mc^2"}


def test_extract_latex_empty():
    assert extract_latex_from_asl("") == {}


def test_replace_latex_inline():
    d = {"u1": "E=mc^2"}
    html = "<span><img src=\"u1\"/></span>"
    out = replace_latex_images(html, d)
    assert "$E=mc^2$" in out
    assert "img" not in out


def test_replace_latex_block():
    d = {"u1": "\\frac{1}{2}\nmv^2"}
    html = '<p><img src="u1"/></p>'
    out = replace_latex_images(html, d)
    assert "$$" in out and "\\frac{1}{2}" in out


def test_html_to_markdown_basic():
    md = html_to_markdown("<h1>T</h1><p><strong>b</strong></p><ul><li>x</li></ul>")
    assert "# T" in md and "**b**" in md and "- x" in md


def test_code_language_from_data_language():
    html = ('<div data-lake-card="codeblock" data-language="bash"><pre class="cm-s-default">'
            '<code>ls -l</code></pre></div>')
    md = html_to_markdown(html)
    assert "```bash" in md


def test_table_cell_image_lifted():
    html = ('<table><tbody><tr><td>a</td>'
            '<td><img src="https://x/1.png"/></td></tr></tbody></table>')
    md = html_to_markdown(html)
    assert "![image](https://x/1.png)" in md or "](https://x/1.png)" in md


def _write_doc(tmp_path, doc: dict, name="x.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"doc": doc}), encoding="utf-8")
    return p


def test_backend_convert_basic(tmp_path):
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": "<h1>标题</h1><p>内容文字</p>", "body_asl": ""})
    r = LakeDocBackend().convert(src, tmp_path / "标题.assets", _task(tmp_path))
    assert r.handled_images is True
    assert "# 标题" in r.body and "内容文字" in r.body


def test_backend_keeps_external_images_when_no_download(tmp_path):
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    r = LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    assert "https://x/1.png" in r.body   # download_image=False → 保留外链


def test_backend_downloads_images_to_assets(tmp_path, monkeypatch):
    class FakeResp:
        content = b"PNGDATA"
        headers = {"Content-Type": "image/png"}

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", lambda url, timeout: FakeResp())
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    assets = tmp_path / "标题.assets"
    task = _task(tmp_path, {"download_image": True})
    r = LakeDocBackend().convert(src, assets, task)
    assert (assets / "img_001.png").read_bytes() == b"PNGDATA"
    assert f"./{assets.name}/img_001.png" in r.body


def test_backend_download_failure_notice(tmp_path, monkeypatch):
    def boom(url, timeout):
        raise RuntimeError("net down")

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", boom)
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    task = _task(tmp_path, {"download_image": True})
    r = LakeDocBackend().convert(src, tmp_path / "标题.assets", task)
    assert "[图片缺失" in r.body and "https://x/1.png" in r.body


def test_backend_latex_restored(tmp_path):
    src = _write_doc(tmp_path, {
        "type": "Doc", "format": "lake",
        "body": '<p><img src="u1"/></p>',
        "body_asl": _card("u1", "E=mc^2")})
    r = LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    assert "$E=mc^2$" in r.body
```

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_lake_doc.py -q` → FAIL

- [ ] **Step 3: 实现 `src/xmd/backends/lake_doc.py`**

以 `$LB/lakebook/doc_converter.py` 为基线迁移（`_extract_code_language/_lift_embedded_images/html_to_markdown/extract_latex_from_asl/replace_latex_images` 逐字保留含注释），删除 HAS_* 可选依赖降级分支（设计文档 D4），改造点：

```python
"""语雀普通文档后端：HTML → Markdown（LaTeX 还原 + 外链图片下载）。

自 LakebookConverter doc_converter 重构：
- 适配 Converter 协议：读取 doc json → 返回 body，不自行落盘 md（writer 统一写）
- 图片落点从 attachments/{title}_NNN 改为 assets_dir/img_NNN（设计文档 D2）
- 删除可选依赖降级路径（bs4/markdownify/requests 必装，设计文档 D4）
"""
from __future__ import annotations

import json
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert
from requests import get as http_get

from xmd.model import ConvertError, ConvertResult, Task
from xmd.writer import pretty_md

IMAGE_DOWNLOAD_TIMEOUT = 10
IMAGE_DOWNLOAD_MAX_ATTEMPTS = 3
IMAGE_DOWNLOAD_MAX_WORKERS = 8  # 图片并发下载线程数

DEFAULT_HEADING_STYLE = "ATX"

# 图片 Content-Type → 扩展名（迁自 lakebook.constants）
CONTENT_TYPE_TO_EXTENSION: dict[str, str] = {
    "image/gif":     ".gif",
    "image/jpeg":    ".jpg",
    "image/svg+xml": ".svg",
    "image/png":     ".png",
}
```

（`_NO_LANGUAGE/_extract_code_language/_BLOCKING_CELL/_lift_embedded_images/html_to_markdown/extract_latex_from_asl/replace_latex_images/_download_image_with_retry` 逐字迁移，仅：去掉 `HAS_BS4/HAS_MARKDOWNIFY` 分支——`html_to_markdown` 直接走 markdownify + `_lift_embedded_images`；`extract_latex_from_asl/replace_latex_images` 开头的 `if not HAS_BS4` 守卫删除。）

图片下载重写（替换原 `download_images_and_patch_html`，并发下载→串行写盘结构保留）：
```python
def download_images_to_assets(html: str, assets_dir: Path) -> str:
    """下载 HTML 中所有外链图片到 assets_dir（img_NNN.ext），src 改相对引用。

    失败（重试 IMAGE_DOWNLOAD_MAX_ATTEMPTS 次）→ 原位写 [图片缺失：原因] URL 文本。
    并发下载仅获取字节；写盘与 HTML 改写串行（编号/文件名稳定）。
    """
    bs = BeautifulSoup(html, "html.parser")
    img_tags = bs.find_all("img")
    tasks = [(no, image, image.get("src", ""))
             for no, image in enumerate(img_tags, start=1) if image.get("src")]
    if not tasks:
        return html
    assets_dir.mkdir(parents=True, exist_ok=True)

    # results[no] -> ("ok", content, ext) | ("fail", src, error)
    results: dict[int, tuple] = {}
    with ThreadPoolExecutor(max_workers=IMAGE_DOWNLOAD_MAX_WORKERS) as executor:
        future_to_no = {
            executor.submit(_download_image_with_retry, src): (no, src)
            for no, _image, src in tasks
        }
        for future in as_completed(future_to_no):
            no, src = future_to_no[future]
            try:
                resp = future.result()
                ext = CONTENT_TYPE_TO_EXTENSION.get(
                    resp.headers.get("Content-Type", ""), ".jpg")
                results[no] = ("ok", resp.content, ext)
            except Exception as e:
                results[no] = ("fail", src, e)

    prefix = f"./{assets_dir.name}/"
    for no, image, src in tasks:
        outcome = results.get(no)
        if outcome and outcome[0] == "ok":
            _, content, ext = outcome
            fname = f"img_{no:03d}{ext}"
            try:
                (assets_dir / fname).write_bytes(content)
                image["src"] = prefix + fname
                # 清理语雀默认的无意义图片 alt/title（恒为 "image"，无语义价值）
                if (image.get("alt") or "").strip() == "image":
                    image["alt"] = ""
                if (image.get("title") or "").strip() == "image":
                    del image["title"]
            except OSError:
                image.replace_with(bs.new_string(f"\n[图片缺失：写入失败] {src}\n"))
        else:
            reason = f"下载失败：{outcome[2]}" if outcome else "下载失败，请手动处理"
            image.replace_with(bs.new_string(f"\n[图片缺失：{reason}] {src}\n"))
    return str(bs)


class LakeDocBackend:
    """语雀普通文档 → Markdown 后端。"""

    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult:
        doc = json.loads(source.read_text(encoding="utf-8")).get("doc", {})
        # 用 `or ""` 兜底：键存在但值为 None 时，dict.get 的默认值不会生效
        body_asl = doc.get("body_asl") or ""
        latex_dict = extract_latex_from_asl(body_asl)
        # body 是完整的渲染 HTML；若 body 为空（极少数情况），回退到 body_asl
        html = doc.get("body") or body_asl
        if latex_dict:
            html = replace_latex_images(html, latex_dict)
        if task.entry.meta.get("download_image", True):
            html = download_images_to_assets(html, assets_dir)
        markdown_content = pretty_md(html_to_markdown(html))
        return ConvertResult(body=markdown_content, handled_images=True)
```
（`_download_image_with_retry` 迁移时去掉 print 重试提示——worker 进程内 print 无处可看；异常与退避逻辑逐字保留。）

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_lake_doc.py -q` → PASS
```bash
git add src/xmd/backends/lake_doc.py tests/test_lake_doc.py
git commit -m "feat: 语雀普通文档后端（LaTeX 还原/图片下载到 assets）"
```

---

### Task 12: backends/lake_sheet.py（语雀表格后端）

**Files:**
- Create: `src/xmd/backends/lake_sheet.py`
- Test: `tests/test_lake_sheet.py`（新写）

**Interfaces:**
- Consumes: `xmd.model.ConvertError/ConvertResult/Task`
- Produces: `LakeSheetBackend`（`convert(source, assets_dir, task) -> ConvertResult`，`handled_output=True`）、`parse_lakesheet(body) -> list[list[str]] | None`、`rows_to_sheet_plus_format(rows, title, file_path="") -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_lake_sheet.py`：
```python
"""lake_sheet 后端测试：解压/行列提取/字符串化/尾列裁剪/CSV/Sheet Plus。"""
import json
import zlib

from xmd.backends.lake_sheet import LakeSheetBackend, parse_lakesheet, rows_to_sheet_plus_format
from xmd.model import Category, FileEntry


def _body(data: dict) -> str:
    """构造 lakesheet body：JSON 壳 + zlib 压缩（latin-1 还原为字符串）。"""
    return json.dumps({"format": "lakesheet",
                       "sheet": zlib.compress(json.dumps(data).encode()).decode("latin-1")})


def _write_sheet(tmp_path, data, name="s.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"doc": {"type": "Sheet", "format": "lakesheet",
                                     "body": _body(data)}}), encoding="utf-8")
    return p


def _task(src, output, fmt="csv", title="表"):
    return FileEntry(Path("b/表"), src, Category.LAKE_SHEET,
                     meta={"title": title, "sheet_format": fmt})


DATA = {"data": {
    "0": {"0": {"v": "姓名"}, "1": {"v": "年龄"}},
    "1": {"0": {"v": "张三"}, "1": {"v": 28}},
    "2": {"0": {"v": "李四"}, "1": {"v": 0.0}},
}}


def test_parse_zlib_roundtrip():
    rows = parse_lakesheet(_body(DATA))
    assert rows == [["姓名", "年龄"], ["张三", "28"], ["李四", "0"]]   # 0.0 → "0"


def test_parse_plain_json_fallback():
    body = json.dumps({"format": "lakesheet", "sheet": json.dumps(DATA)})
    assert parse_lakesheet(body) == [["姓名", "年龄"], ["张三", "28"], ["李四", "0"]]


def test_parse_bool_and_none_and_dict_cell():
    data = {"data": {
        "0": {"0": {"v": "b"}, "1": {"v": "n"}, "2": {"v": "link"}},
        "1": {"0": {"v": True}, "1": {"v": None},
              "2": {"v": {"text": "点击", "url": "https://x"}}},
    }}
    rows = parse_lakesheet(_body(data))
    assert rows[1] == ["TRUE", "", "点击"]


def test_parse_trailing_empty_cols_trimmed():
    data = {"data": {"0": {"0": {"v": "a"}, "500": {"v": ""}}}}
    rows = parse_lakesheet(_body(data))
    assert rows == [["a"]]


def test_parse_bad_format_returns_none():
    assert parse_lakesheet(json.dumps({"format": "other"})) is None


def test_backend_csv(tmp_path):
    src = _write_sheet(tmp_path, DATA)
    out = tmp_path / "表.csv"
    task = _task(src, out, "csv")
    r = LakeSheetBackend().convert(src, tmp_path / "a.assets", task)
    assert r.handled_output is True and r.body == ""
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "姓名,年龄"
    assert lines[1] == "张三,28"


def test_backend_sheet_plus(tmp_path):
    src = _write_sheet(tmp_path, DATA)
    out = tmp_path / "表.md"
    task = _task(src, out, "sheet", title="数据表")
    LakeSheetBackend().convert(src, tmp_path / "a.assets", task)
    text = out.read_text(encoding="utf-8")
    assert "excel-pro-plugin: parsed" in text
    assert "```sheet" in text and "```multiSheet" in text
    j = json.loads(text.split("```sheet")[1].split("```")[0])
    assert j["name"] == "数据表"
    assert j["sheets"][j["sheetOrder"][0]]["cellData"]["0"]["0"]["v"] == "姓名"


def test_backend_empty_body_raises(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"doc": {"type": "Sheet", "body": ""}}), encoding="utf-8")
    import pytest
    from xmd.model import ConvertError
    with pytest.raises(ConvertError):
        LakeSheetBackend().convert(p, tmp_path / "a.assets",
                                   _task(p, tmp_path / "t.csv"))


def test_rows_to_sheet_plus_random_ids():
    md = rows_to_sheet_plus_format([["a", "b"], ["1", "2"]], "T", "")
    assert md.startswith("---")
```

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_lake_sheet.py -q` → FAIL

- [ ] **Step 3: 实现 `src/xmd/backends/lake_sheet.py`**

以 `$LB/lakebook/sheet_converter.py` 为基线：`parse_lakesheet/_decompress_sheet/_extract_rows_from_sheet_json/rows_to_sheet_plus_format/_make_cell_style` 逐字迁移（含"不做日期数值猜测转换"的注释块——防止回归），新增适配类：

```python
"""语雀表格文档后端：lakesheet → CSV / Obsidian Sheet Plus。

自 LakebookConverter sheet_converter 迁移：解析函数逐字保留；新增
LakeSheetBackend 适配 Converter 协议——后端自行落盘完整输出
（ConvertResult.handled_output=True，runner 跳过 write_markdown 与
empty/min_chars 判定，见设计文档 5.3）。
"""
from __future__ import annotations

import csv
import gzip
import json
import random
import string
import zlib
from pathlib import Path
from typing import List, Optional

from xmd.model import ConvertError, ConvertResult, Task

# —— 以下解析函数逐字迁自 sheet_converter（parse_lakesheet 内 print 改为
#    静默返回 None，失败信息由 ConvertError 在 Backend 层统一报告）——
# parse_lakesheet / _decompress_sheet / _extract_rows_from_sheet_json /
# rows_to_sheet_plus_format / _make_cell_style


class LakeSheetBackend:
    """语雀表格 → CSV / Sheet Plus 后端（自行落盘）。"""

    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult:
        body = json.loads(source.read_text(encoding="utf-8")).get("doc", {}).get("body", "")
        if not body:
            raise ConvertError("表格文档 body 为空")
        rows = parse_lakesheet(body)
        if not rows:
            raise ConvertError("表格数据解析失败或为空")
        out = task.output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        if task.entry.meta.get("sheet_format", "csv") == "sheet":
            content = rows_to_sheet_plus_format(rows, task.entry.meta.get("title", ""), str(out))
            out.write_text(content, encoding="utf-8")
        else:
            # 默认格式为 CSV：原值原样输出（无样式、无日期猜测转换）
            with out.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerows(rows)
        return ConvertResult(body="", handled_images=True, handled_output=True)
```

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest tests/test_lake_sheet.py -q` → PASS
```bash
git add src/xmd/backends/lake_sheet.py tests/test_lake_sheet.py
git commit -m "feat: 语雀表格后端（CSV/Sheet Plus，handled_output 自行落盘）"
```

---

### Task 13: runner 集成展开器（容器展开 + 表格过滤 + tmp 清理 + 按类别路由）

**Files:**
- Modify: `src/xmd/runner.py`
- Test: `tests/test_runner_expand.py`（新写）

**Interfaces:**
- Consumes: Task 10/11/12 产物（`expand_lakebook/ExpandError`、`LakeDocBackend/LakeSheetBackend`）
- Produces: `run()` 的 LAKEBOOK 条目展开行为、`_converter_for(category) -> Converter`（worker 内按类别路由）

- [ ] **Step 1: 写失败测试**

`tests/test_runner_expand.py`（fixtures 构造复用 `tests/test_lakebook_expander.py` 的 `make_lakebook`，提取到 `tests/conftest.py`）：

先在 `tests/conftest.py` 追加（保留原 fixtures）：
```python
import io
import json
import tarfile

import yaml


def make_lakebook(path, docs, toc, *, with_uuid=True, repo_id="123"):
    """构造最小 .lakebook tar（expander/runner 测试共用）。"""
    if not with_uuid:
        toc = [{k: v for k, v in t.items() if k not in ("uuid", "parent_uuid")} for t in toc]
    meta_inner = {"book": {"name": "测试库", "path": "https://y.com/u/test",
                           "tocYml": yaml.safe_dump(toc, allow_unicode=True)}}
    entries = [(f"{repo_id}/$meta.json", json.dumps({"meta": json.dumps(meta_inner)}))]
    for d in docs:
        entries.append((f"{repo_id}/{d['url']}.json", json.dumps({"doc": d["doc"]})))
    with tarfile.open(path, "w") as tf:
        for name, data in entries:
            b = data.encode("utf-8")
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tf.addfile(ti, io.BytesIO(b))
```
（`tests/test_lakebook_expander.py` 中的同名本地函数改为 `from tests.conftest import make_lakebook`？——pytest conftest 中的普通函数不可 import；改法：把 make_lakebook 放 conftest 并在 expander 测试中通过 `from conftest import make_lakebook`（pytest rootdir 在 tests 上级时可用）或在两个测试文件内各自定义。**采用**：在 conftest.py 定义，测试文件用 `from conftest import make_lakebook`。）

`tests/test_runner_expand.py`：
```python
import shutil

from conftest import make_lakebook

from xmd.runner import run

DOC = {"type": "Doc", "format": "lake", "body": "<h1>标题</h1><p>内容文字</p>", "body_asl": ""}
SHEET = {"type": "Sheet", "format": "lakesheet",
         "body": '{"format":"lakesheet","sheet":"x"}'}   # 解析失败亦无妨：仅验路由
TOC = [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"},
       {"title": "表", "type": "DOC", "url": "s1", "level": 0, "uuid": "s1"}]


def _sheet_body():
    import json, zlib
    data = {"data": {"0": {"0": {"v": "a"}, "1": {"v": "b"}}}}
    return json.dumps({"format": "lakesheet",
                       "sheet": zlib.compress(json.dumps(data).encode()).decode("latin-1")})


def test_run_mixed_pdf_and_lakebook(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(tcp_pdf, src / "t.note.pdf")
    make_lakebook(src / "book.lakebook",
                  [{"url": "d1", "doc": DOC}, {"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  TOC)
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=5)
    assert (out / "t.md").exists()
    assert (out / "book" / "文档.md").exists()
    assert (out / "book" / "表.csv").exists()
    assert s["ok"] == 3


def test_run_no_sheet_filters_sheet_tasks(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook",
                  [{"url": "d1", "doc": DOC},
                   {"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  TOC)
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=5, convert_sheets=False)
    assert (out / "book" / "文档.md").exists()
    assert not (out / "book" / "表.csv").exists()
    assert s["total"] == 1 and s["ok"] == 1


def test_run_sheet_plus_format(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook",
                  [{"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  [TOC[1]])
    out = tmp_path / "out"
    run(src, out, jobs=1, sheet_format="sheet")
    md = out / "book" / "表.md"
    assert md.exists()
    assert "excel-pro-plugin" in md.read_text(encoding="utf-8")


def test_run_corrupt_lakebook_recorded_error(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.lakebook").write_text("not a tar")
    out = tmp_path / "out"
    s = run(src, out, jobs=1)
    assert s["error"] == 1
    assert "bad.lakebook" in (out / "convert.log").read_text(encoding="utf-8")


def test_run_resume_lakebook_by_archive_mtime(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], [TOC[0]])
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=5)
    s2 = run(src, out, jobs=1, min_chars=5)
    assert s2["skipped"] == s2["total"] == 1


def test_run_tmpdir_cleaned(tmp_path):
    import tempfile
    from pathlib import Path
    before = set(Path(tempfile.gettempdir()).glob("xmd_lakebook_*"))
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], [TOC[0]])
    run(src, tmp_path / "out", jobs=1, min_chars=5)
    after = set(Path(tempfile.gettempdir()).glob("xmd_lakebook_*"))
    assert after == before   # 无新增残留
```

- [ ] **Step 2: 确认失败** → Run: `.venv/bin/pytest tests/test_runner_expand.py -q` → FAIL

- [ ] **Step 3: 修改 `src/xmd/runner.py`**

新增（置于 `process_one` 之前）：
```python
# lake 族后端 worker 单例（惰性创建；PDF 族仍走 _get_converter 的 ctx.backend）
_WORKER_LAKE: dict[str, Converter] = {}


def _converter_for(category: Category) -> Converter:
    """按任务类别选后端：lake 族按需惰性单例；其余（PDF 族）按 ctx.backend。"""
    if category is Category.LAKE_DOC:
        if "doc" not in _WORKER_LAKE:
            from xmd.backends.lake_doc import LakeDocBackend
            _WORKER_LAKE["doc"] = LakeDocBackend()
        return _WORKER_LAKE["doc"]
    if category is Category.LAKE_SHEET:
        if "sheet" not in _WORKER_LAKE:
            from xmd.backends.lake_sheet import LakeSheetBackend
            _WORKER_LAKE["sheet"] = LakeSheetBackend()
        return _WORKER_LAKE["sheet"]
    return _get_converter()
```

`process_one` 中 `cres = _get_converter().convert(...)` 改为：
```python
        cres = _converter_for(entry.category).convert(entry.abs_path, task.assets_dir, task)
```

新增展开函数（置于 `run` 之前）：
```python
def _expand_inputs(files: list[FileEntry], *, no_image: bool, convert_sheets: bool,
                   sheet_format: str) -> tuple[list[FileEntry], list[Path], list[Result]]:
    """展开容器条目（.lakebook）→ 虚拟 FileEntry。

    返回 (待转条目, 待清理 tmp 目录, 展开失败结果)。展开在主进程串行执行
    （tar 解压 IO 型）；损坏/恶意归档记 error 结果，不中断批量。
    """
    from xmd.expanders import ExpandError, expand_lakebook   # 延迟 import
    entries: list[FileEntry] = []
    tmp_dirs: list[Path] = []
    errors: list[Result] = []
    for e in files:
        if e.category is not Category.LAKEBOOK:
            entries.append(e)
            continue
        try:
            sub, tmp = expand_lakebook(e.abs_path,
                                       download_image=not no_image,
                                       sheet_format=sheet_format)
        except ExpandError as err:
            errors.append(Result(str(e.rel_path), "error", 0, 0, str(err)))
            continue
        tmp_dirs.append(tmp)
        if convert_sheets:
            entries.extend(sub)
        else:   # --no-sheet：跳过表格文档（不出文件不计结果）
            entries.extend(x for x in sub if x.category is not Category.LAKE_SHEET)
    return entries, tmp_dirs, errors
```

`run()` 修改（在 scan 累加与 preprocess 之间插入展开；dispatch 纳入 try/finally 清理 tmp；expand_errors 并入结果）：
```python
    # —— 原：for inp in inputs: scan 累加 walked_files/dirs；mkdir dirs ——
    entries, tmp_dirs, expand_errors = _expand_inputs(
        walked_files, no_image=no_image,
        convert_sheets=convert_sheets, sheet_format=sheet_format)

    tasks = preprocess(entries, output)
    if only is not None:
        tasks = [t for t in tasks if str(t.entry.rel_path) in only]
    ctx = Ctx(force=force, min_chars=min_chars, max_pdf_mb=max_pdf_mb,
              backend=backend, backend_opts=backend_opts, no_image=no_image)
    start = time.perf_counter()
    try:
        results = _dispatch(tasks, ctx, jobs, output)
    finally:
        # 展开产生的 tmp 目录统一清理（dispatch 内 BrokenProcessPool 重启也不外逸）
        for t in tmp_dirs:
            shutil.rmtree(t, ignore_errors=True)
    duration = time.perf_counter() - start

    for r in expand_errors:   # 展开失败并入结果与日志
        _append_log(output, r)
    results = expand_errors + results
    _write_need_review(output, results)
    ...  # 报告三件套照旧
```
（文件顶部补 `import shutil`。）

- [ ] **Step 4: 通过后提交**

Run: `.venv/bin/pytest -q` → 全部 PASS
```bash
git add src/xmd/runner.py tests/conftest.py tests/test_runner_expand.py tests/test_lakebook_expander.py
git commit -m "feat: runner 集成容器展开（并行/续传/报告能力覆盖语雀任务）"
```

---

### Task 14: 端到端集成测试与 console script 验证

**Files:**
- Test: `tests/test_e2e.py`（新写）

**Interfaces:**
- Consumes: Task 9 的 `xmd.cli.main`、Task 13 的 runner 展开
- Produces: 混合输入端到端验证（CLI → 输出树 → 报告三件套 → 续传）

- [ ] **Step 1: 写测试（对 CLI main 全链路）**

`tests/test_e2e.py`：
```python
"""端到端：CLI 混合输入（散文件 + lakebook）→ 输出树/报告/续传。"""
import json
import shutil

from conftest import make_lakebook

from xmd.cli import main

DOC = {"type": "Doc", "format": "lake",
       "body": "<h1>标题</h1><p>内容文字足够长</p>", "body_asl": ""}
TOC = [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"}]


def test_cli_mixed_inputs_end_to_end(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "附件").mkdir()
    shutil.copy(tcp_pdf, src / "附件" / "t.note.pdf")
    (src / "附件" / "a.mp3").write_bytes(b"audio")
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], TOC)

    out = tmp_path / "out"
    rc = main([str(src), str(tcp_pdf), "-o", str(out),
               "--jobs", "1", "--min-chars", "5"])
    assert rc == 0
    # 散文件目录镜像 + SKIP 保名
    assert (out / "附件" / "t.md").exists()
    assert (out / "附件" / "a.mp3").read_bytes() == b"audio"
    # 单文件输入（rel=文件名 → 输出根）
    assert (out / "tcp-handshake.md").exists()
    # 容器展开树
    assert (out / "book" / "文档.md").exists()
    # 报告三件套
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["total"] >= 4
    assert (out / "convert.log").exists() and (out / "need-review.csv").exists()


def test_cli_resume_second_run_all_skipped(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(tcp_pdf, src / "t.note.pdf")
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], TOC)
    out = tmp_path / "out"
    main([str(src), "-o", str(out), "--jobs", "1", "--min-chars", "5"])
    rc = main([str(src), "-o", str(out), "--jobs", "1", "--min-chars", "5"])
    assert rc == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["skipped"] == s["total"]
    assert s["ok"] == 0
```

- [ ] **Step 2: 运行（应直接 PASS——Task 9/13 已实现；若失败按 systematic-debugging 处理）**

Run: `.venv/bin/pytest tests/test_e2e.py -q` → PASS

- [ ] **Step 3: console script 冒烟**

```bash
.venv/bin/pip install -e . -q
.venv/bin/xmd --help | head -5
```
Expected: 打印 usage: xmd ...

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: 混合输入端到端集成测试（CLI→输出树→报告→续传）"
```

---

### Task 15: 文档与收尾

**Files:**
- Create: `README.md`（重写）、`docs/lakebook-format.md`、`docs/MinerU 文档解析接口文档.html`
- Modify: `.gitignore`（确认覆盖 .venv/ 等）

**Interfaces:**
- Consumes: 全部已实现能力

- [ ] **Step 1: 迁移参考文档**

```bash
cp "$YD/docs/MinerU 文档解析接口文档.html" "docs/MinerU 文档解析接口文档.html"
```
`docs/lakebook-format.md`：提取 `$LB/README.md` 第 5–10 节（项目结构→常见问题）为独立文档，文首加一行说明：
```markdown
# .lakebook 格式深度解析（迁移自 LakebookConverter README）
> 模块路径已并入 xmd（expanders/lakebook.py、backends/lake_doc.py、backends/lake_sheet.py）；下文 lakebook.* 路径为源工程视角，仅作格式参考。
```

- [ ] **Step 2: 重写 README.md**

```markdown
# xmd

任意源 → Markdown 批量转换：散文件目录（有道云笔记导出等）与容器归档（语雀
.lakebook）统一为一种任务模型，共享并行、断点续传与质量报告。

## 支持的输入

| 类别 | 扩展名 | 转换方式 |
|---|---|---|
| 有道笔记 | .note.pdf / .clip.pdf | 后端可插拔（下表） |
| PDF 附件 | .pdf | 同上 |
| Office | .docx/.xlsx/.pptx | markitdown |
| 语雀知识库 | .lakebook | 展开为虚拟任务：Doc→md（LaTeX 还原/图片下载）、Sheet→csv 或 Obsidian Sheet Plus |
| Markdown | .md | 转换（归一） |
| 其他 | .mp3/.rar/... | 原样复制（保留原名） |

## 转换后端（PDF 族，--backend）

| 后端 | 定位 | 成本 | 图片 |
|---|---|---|---|
| markitdown（默认） | 文本提取 | 免费/本地/快 | extract_images 补 |
| pdf-inspector | 纯 Rust 轻量纯文本 | 免费/本地/快 | extract_images 补 |
| mineru | 在线 API 视觉结构恢复 | 在线额度 | Precision zip 自带 |
| auto | 智能路由（pymupdf 探测 Type3/扫描/光栅图） | 默认免费 | 按路由 |

## 安装与用法

（Python ≥3.11）
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

```bash
# 目录批量（镜像目录树，含空目录）
xmd <导出目录> -o <输出目录> [--jobs 4]

# 混合输入（文件与目录任意组合）
xmd a.lakebook b.pdf <目录> -o out/

# 智能路由 + 语雀表格转 Sheet Plus + 不下载图片
xmd <目录> -o out/ --backend auto --sheet-format sheet --no-image
export MINERU_TOKEN=<token>   # backend=mineru|auto 的复杂文件需要

# 续传与重试
xmd <目录> -o out/ --force | --retry-review
```

## 输出布局

```
<output>/
  ├── <镜像源目录树>/
  │     ├── 笔记A.md
  │     ├── 笔记A.assets/img_001.png     # 配图（PDF 抽取 / 语雀下载）
  │     └── 表格B.csv                     # 语雀表格（--sheet-format csv）
  ├── <lakebook名>/<TOC目录树>/文档.md     # 容器展开
  ├── convert.log / need-review.csv / summary.json
```

## 状态分类（summary.json）
ok · skipped（续传跳过）· error · need_review · copied · collision · empty · crash

## 已知限制
- markitdown 对 Type3 视觉 PDF 只出平铺文本 → 用 --backend auto 或 mineru 恢复结构
- MinerU 每日免费额度有限：额度即停 + 跨天续传（--retry-review）
- 不转音频、不解压普通压缩包：原样复制
- 跳过隐藏文件（. 开头）

## 开发
```bash
.venv/bin/pytest -q
```

设计文档：docs/specs/2026-08-16-xmd-unified-converter-design.md（注：实际文件名以仓库为准）
格式参考：docs/lakebook-format.md；MinerU API：docs/MinerU 文档解析接口文档.html
```

（注：README 中设计文档链接写实际文件名 `2026-10-16-xmd-unified-converter-design.md`。）

- [ ] **Step 3: 全量回归 + gitignore 核查**

```bash
.venv/bin/pytest -q          # 全绿
git status --short           # 无意外未跟踪文件（.venv 应被忽略）
cat .gitignore | grep -E "venv|pycache|egg"   # 确认覆盖
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs
git commit -m "docs: README 与参考文档（lakebook 格式解析/MinerU API）"
```

---

## 计划自审记录（执行者无需处理，已核实）

1. **Spec 覆盖**：spec §3 包结构 → Task 1/2/4/5/7/10/11/12；§5.1-5.6 → Task 2/4/5/7/8/9/10/11/12/13；§6 D1-D6 → D1=Task4、D2=Task11、D3=Task11（image_refs=[]）、D4=Task1+11、D5=Task8(preprocess)、D6=Task9；§7 错误处理 → Task 10/11/12/13；§8 测试 → 各任务内；§9 阶段 → Task 1-9 / 10-13 / 14-15。
2. **类型一致性**：`ConvertResult.handled_output`（Task 2 定义，Task 8 runner 消费，Task 12 产出）；`FileEntry.meta["sheet_format"]`（Task 10 产出，Task 4 writer/Task 12 backend 消费）；`expand_lakebook(archive, *, download_image, sheet_format) -> (entries, tmp)`（Task 10 定义，Task 13 消费）。
3. **已知留白（有意）**：test_expand_level_skip 的跳级断言以实际 Path 空段语义为准（Task 10 注记——Path 拼接对空串段的折叠行为需实测确认后固化断言）。
