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
