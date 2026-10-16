"""pdf-inspector 后端：纯 Rust 轻量纯文本 PDF 解析（<200ms，零模型）。

进程内调用（pip 预编译 wheel）。对 Type3 视觉 PDF 会判定乱码不输出（仅对真文本型 PDF 有效），
故默认不走此后端；仅 --backend pdf-inspector 显式选用，或未来混合 PDF 场景的纯文本快路径。
延迟 import（可选依赖），缺失时抛 ConvertError（逐文件标 error，不让 worker 崩）。
不抽图 → handled_images=False，由 runner 统一补图。
"""
from __future__ import annotations

from pathlib import Path

from xmd.model import ConvertError, ConvertResult, Task
from xmd.normalizer import normalize


class PdfInspectorConverter:
    def convert(self, abs_path: Path, assets_dir: Path, task: Task | None = None) -> ConvertResult:
        try:
            import pdf_inspector   # 延迟 import（可选依赖）
        except ImportError as e:
            raise ConvertError("pdf-inspector 未安装：pip install pdf-inspector") from e
        try:
            res = pdf_inspector.process_pdf(str(abs_path))
        except Exception as e:
            raise ConvertError(f"{type(e).__name__}: {e}") from e
        md = getattr(res, "markdown", "") or ""
        return ConvertResult(body=normalize(md), handled_images=False)
