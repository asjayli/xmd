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
