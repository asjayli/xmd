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
