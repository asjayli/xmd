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
    meta 携带 {title, download_image, sheet_format}（mar #28：url 无消费方已删）。
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
    output_path: Path
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
