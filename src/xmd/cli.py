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
