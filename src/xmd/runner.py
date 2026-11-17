"""批量调度：冲突解析、worker 单例、单文件流水线与 run 编排。

后端可插拔：Ctx.backend 选 markitdown|pdf-inspector|mineru|auto。
MinerU 额度即停：_dispatch 识别 MINERU_DAILY_LIMIT 后停止提交剩余（贯彻不用优先额度）。
容器展开（.lakebook）：expanders 在主进程展开为虚拟 FileEntry，随批共享并行/续传/报告。
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
from xmd.writer import assets_dir_for, build_output_path, copy_skip, csv_safe, write_markdown

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
    """按 ctx.backend 实例化后端（模块顶层已 import，无循环依赖）。"""
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
            and task.output_path.exists()
            and task.output_path.stat().st_mtime >= src_mtime):
        return Result(rel, "skipped", 0, 0, None)

    if entry.category is Category.SKIP:
        try:
            copy_skip(entry.abs_path, task.output_path)
            return Result(rel, "copied", 0, 0, None)
        except Exception as e:
            return Result(rel, "error", 0, 0, str(e))

    title = task.output_path.stem
    try:
        cres = _converter_for(entry.category).convert(entry.abs_path, task.assets_dir, task)
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

    write_markdown(task.output_path, title, body, image_refs)

    stripped = body.strip()
    if stripped == "":
        return Result(rel, "empty", 0, len(image_refs), None)
    status = "ok"
    if len(stripped) < ctx.min_chars and not image_refs:
        status = "need_review"
    if task.collision and status == "ok":
        status = "collision"
    return Result(rel, status, len(stripped), len(image_refs), None)


# ---- 编排 ----

# MinerU 每日免费额度耗尽标记（见 xmd.backends.mineru.DAILY_LIMIT_MARK）
_DAILY_LIMIT_MARK = "MINERU_DAILY_LIMIT"


def _is_daily_limit(r: Result) -> bool:
    """检测 Result 是否为 MinerU 每日额度耗尽（触发 _dispatch 停止提交剩余）。"""
    return bool(r.error and _DAILY_LIMIT_MARK in r.error)


def _append_log(output_root: Path, r: Result) -> None:
    with (output_root / "convert.log").open("a", encoding="utf-8") as f:
        f.write(f"{r.rel_path} | {r.status} | {r.chars} | {r.images} | {r.error or ''}\n")


def _write_need_review(output_root: Path, results: list[Result]) -> None:
    rows = [r for r in results if r.status in ("need_review", "empty", "error", "crash")]
    with (output_root / "need-review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rel_path", "chars", "status"])
        for r in rows:
            # rel_path 不可信（lakebook TOC 标题）：公式注入防御与 lake_sheet CSV 同修（mar #2）
            w.writerow([csv_safe(r.rel_path), r.chars, r.status])


def _write_need_review_merged(output_root: Path, results: list[Result], only: set[str]) -> None:
    """retry 子集模式（mar #5）：合并旧 need-review.csv。

    本轮未触及（rel_path 不在 only）的历史行原样逐字节保留；触及行以本轮
    结果替换——已修复（ok/skipped/copied/collision）则移出清单，仍需复核
    则更新行。旧文件缺失/损坏时退化为全量重写。
    """
    csv_path = output_root / "need-review.csv"
    old_lines: list[str] = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            lines = f.read().splitlines()
        for line in lines[1:]:   # 跳过表头
            try:
                first = next(csv.reader([line]))[0]
            except (StopIteration, csv.Error, IndexError):
                continue   # 异构行（空行/损坏）丢弃
            if first not in only:
                old_lines.append(line)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rel_path", "chars", "status"])
        for line in old_lines:   # 未触及历史行逐字节回写
            f.write(line + "\n")
        for r in results:
            if r.rel_path in only and r.status in ("need_review", "empty", "error", "crash"):
                w.writerow([csv_safe(r.rel_path), r.chars, r.status])


def _summarize(results: list[Result], duration: float) -> dict:
    s = {"total": len(results), "ok": 0, "skipped": 0, "error": 0,
         "need_review": 0, "copied": 0, "collision": 0, "empty": 0,
         "crash": 0, "images_total": 0, "duration_sec": round(duration, 2)}
    for r in results:
        if r.status in s:
            s[r.status] += 1
        s["images_total"] += r.images
    return s


def _dispatch(tasks: list[Task], ctx: Ctx, jobs: int, output_root: Path) -> list[Result]:
    results: list[Result] = []
    done_keys: set[str] = set()
    pending = list(tasks)
    daily_stop = False
    while pending:
        try:
            with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init,
                                     initargs=(ctx,)) as pool:
                fut_map = {pool.submit(process_one, t): t for t in pending}
                for fut in as_completed(fut_map):
                    t = fut_map[fut]
                    rel = str(t.entry.rel_path)
                    if daily_stop:
                        # 额度上限后：已跑完的取真实结果（不覆盖成 need_review）；
                        # 未跑/被取消的标 need_review 待续传
                        if fut.cancelled():
                            r = Result(rel, "need_review", 0, 0, "额度上限跳过，待续传")
                        else:
                            try:
                                r = fut.result()
                            except Exception as e:
                                r = Result(rel, "crash", 0, 0, f"{type(e).__name__}: {e}")
                        results.append(r)
                        _append_log(output_root, r)
                        done_keys.add(rel)
                        continue
                    try:
                        r = fut.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as e:
                        r = Result(rel, "crash", 0, 0, f"{type(e).__name__}: {e}")
                    results.append(r)
                    _append_log(output_root, r)
                    done_keys.add(rel)
                    if _is_daily_limit(r):
                        # 触达 MinerU 每日免费上限 → 停止提交剩余，避免无效消耗
                        daily_stop = True
                        for f2 in fut_map:
                            if f2 is not fut and not f2.done():
                                f2.cancel()
        except BrokenProcessPool:
            if daily_stop:
                # 当前控制流下不可达（daily_stop 分支内 except Exception 已把 BPP 记为
                # crash 不外逸），纯防御：若将来此路径可达，补记剩余未记录的防丢失
                for t in pending:
                    rel = str(t.entry.rel_path)
                    if rel not in done_keys:
                        r = Result(rel, "need_review", 0, 0, "额度上限跳过，待续传")
                        results.append(r)
                        _append_log(output_root, r)
                        done_keys.add(rel)
                break
            remaining = [t for t in pending if str(t.entry.rel_path) not in done_keys]
            if not remaining:
                break
            crash_r = Result(str(remaining[0].entry.rel_path), "crash", 0, 0,
                             "BrokenProcessPool")
            results.append(crash_r)
            _append_log(output_root, crash_r)
            pending = remaining[1:]
            continue
        break
    return results


def _expand_inputs(files: list[FileEntry], *, no_image: bool, convert_sheets: bool,
                   sheet_format: str, tmp_base: Path) -> tuple[list[FileEntry], list[Path], list[Result]]:
    """展开容器条目（.lakebook）→ 虚拟 FileEntry。

    返回 (待转条目, 待清理 tmp 目录, 展开失败结果)。展开在主进程串行执行
    （tar 解压 IO 型）；损坏/恶意归档记 error 结果，不中断批量。
    tmp_base：展开 tmp 基准目录（输出盘 .xmd-tmp，mar #16；存在容器条目时才创建）。
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
            tmp_base.mkdir(parents=True, exist_ok=True)
            sub, tmp = expand_lakebook(e.abs_path,
                                       download_image=not no_image,
                                       sheet_format=sheet_format,
                                       tmp_base=tmp_base)
        except ExpandError as err:
            errors.append(Result(str(e.rel_path), "error", 0, 0, str(err)))
            continue
        tmp_dirs.append(tmp)
        if convert_sheets:
            entries.extend(sub)
        else:   # --no-sheet：跳过表格文档（不出文件不计结果）
            entries.extend(x for x in sub if x.category is not Category.LAKE_SHEET)
    return entries, tmp_dirs, errors


def run(source, output: Path, jobs: int = 4,
        force: bool = False, min_chars: int = 50, max_pdf_mb: int = 20,
        backend: str = "markitdown", backend_opts: dict | None = None,
        only: set[str] | None = None, no_image: bool = False,
        convert_sheets: bool = True, sheet_format: str = "csv") -> dict:
    """source 支持单 Path 或 Path 列表（混合文件/目录输入）。

    遍历输入 → 镜像目录 → 主进程展开容器（.lakebook）→ preprocess →
    dispatch → 报告；展开失败记 error 结果不中断批量，展开 tmp 目录在
    dispatch 结束后统一清理。
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
    # 重叠输入去重（mar #12）：目录与其子文件同时作为输入时，同一源文件
    # 只保留首次出现的条目（目录 walk 的 rel 带镜像结构，优先），避免
    # 双份转换/同路径并发写/统计与计费翻倍
    seen_paths: set[Path] = set()
    deduped: list[FileEntry] = []
    for e in walked_files:
        try:
            key = e.abs_path.resolve()
        except OSError:
            key = e.abs_path   # 解析失败（如已删除）：按原路径去重
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduped.append(e)
    walked_files = deduped

    entries, tmp_dirs, expand_errors = _expand_inputs(
        walked_files, no_image=no_image,
        convert_sheets=convert_sheets, sheet_format=sheet_format,
        tmp_base=output / ".xmd-tmp")

    tasks = preprocess(entries, output)
    if only is not None:   # --retry-review：仅处理指定 rel_path 子集
        tasks = [t for t in tasks if str(t.entry.rel_path) in only]
    ctx_opts = backend_opts
    if backend in ("mineru", "auto") and backend_opts and backend_opts.get("rate_per_min"):
        # mar #15：rate_per_min 为全局速率语义 → 每 worker 按配额均分限流
        # （每 worker 独立 _throttle，不拆分则实际速率放大 jobs 倍）
        ctx_opts = dict(backend_opts)
        ctx_opts["rate_per_min"] = max(1, ctx_opts["rate_per_min"] // jobs)
    ctx = Ctx(force=force, min_chars=min_chars, max_pdf_mb=max_pdf_mb,
              backend=backend, backend_opts=ctx_opts, no_image=no_image)
    start = time.perf_counter()
    try:
        results = _dispatch(tasks, ctx, jobs, output)
    finally:
        # 展开产生的 tmp 目录统一清理（dispatch 内 BrokenProcessPool 重启也不外逸）；
        # 基准目录 .xmd-tmp 一并移除（隐藏目录本身也不留在输出树，mar #16）
        for t in tmp_dirs:
            shutil.rmtree(t, ignore_errors=True)
        shutil.rmtree(output / ".xmd-tmp", ignore_errors=True)
    duration = time.perf_counter() - start

    for r in expand_errors:   # 展开失败并入结果与日志
        _append_log(output, r)
    results = expand_errors + results
    if only is not None:   # retry 子集模式：保留未触及历史行（mar #5）
        _write_need_review_merged(output, results, only)
    else:
        _write_need_review(output, results)
    summary = _summarize(results, duration)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
