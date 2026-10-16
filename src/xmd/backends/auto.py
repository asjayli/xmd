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
