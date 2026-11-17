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
    cleaned = "".join("_" if c in _ILLEGAL else c for c in name)
    # 纯点段（. / .. / ...）在路径拼接中求值为当前/上级目录，构成目录穿越
    # （mar #1），整段替换为 _；含非点字符的合法名（如 a..b）不受影响
    if cleaned and set(cleaned) == {"."}:
        return "_"
    return cleaned


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
        out = output_root.joinpath(*parts[:-1]) / f"{parts[-1]}{ext}"
        # 防御纵深（mar #1）：lake 分支的路径段完全来自不可信 TOC，即使上游
        # 清理失效也拒绝越界输出（resolve 后必须落在输出根之下）
        if not out.resolve().is_relative_to(output_root.resolve()):
            raise ValueError(f"输出路径越界: {out}")
        return out
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
    return output.rstrip("\n")
