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

    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult:
        try:
            result = self._md.convert(str(source))
        except Exception as e:  # markitdown 各类异常统一包装
            raise ConvertError(f"{type(e).__name__}: {e}") from e
        text = result.text_content or ""
        return ConvertResult(body=normalize(text), handled_images=False)
