"""智能路由：按 PDF 特征选择后端。

pymupdf 轻量探测（零额外依赖，每文件几十 ms），判断复杂度：
- Type3 字体 / 扫描件（文本层极薄）/ 含光栅图 → 视觉复杂 → mineru + precision
- 其余简单文本 → markitdown（免费快路径）

MinerU Agent 硬限制（≤20 页/≤10MB，见 docs/MinerU 文档解析接口文档.html TABLE 0/11）
由 MinerUConverter 在 api=auto 时叠加判定，本函数仅给复杂度倾向。
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

# MinerU Agent 轻量 API 硬限制（HTML 文档 TABLE 0/11）
AGENT_MAX_PAGES = 20
AGENT_MAX_MB = 10


def _probe(pdf_path: Path) -> tuple[int, bool, int, int] | None:
    """open 一次探测，返回 (pages, has_type3, raster_imgs, text_chars)；损坏/加密返回 None。"""
    try:
        doc = pymupdf.open(str(pdf_path))
        try:
            pages = len(doc)
            # Type3 字体检测：视觉渲染 PDF 标志。get_fonts 返回 (xref,ext,type,basename,name,enc)，type 在 idx2。
            has_type3 = any(
                (len(f) > 2 and f[2] == "Type3")
                for page in doc for f in page.get_fonts()
            )
            raster_imgs = sum(len(page.get_images(full=True)) for page in doc)
            text_chars = sum(len(page.get_text()) for page in doc)
        finally:
            doc.close()
    except Exception:
        return None
    return pages, has_type3, raster_imgs, text_chars


def _is_complex(pages: int, has_type3: bool, raster_imgs: int, text_chars: int) -> bool:
    """复杂度判定：Type3 / 含光栅图 / 文本层极薄(扫描) → True。"""
    is_scanned = pages > 0 and text_chars / pages < 50   # 文本层极薄 → 疑似扫描件
    return has_type3 or raster_imgs > 0 or is_scanned


def classify_pdf(pdf_path: Path) -> tuple[str, str]:
    """判复杂度，返回 (backend, mineru_api)。

    复杂 → ('mineru', 'precision')；简单 → ('markitdown', 'agent')。
    mineru_api 字段仅当 backend=mineru 时由 MinerUConverter 使用。
    损坏/加密/非 PDF → 降级 markitdown（由其后端统一标 error，不让 worker 崩）。
    """
    p = _probe(pdf_path)
    if p is None:
        return ("markitdown", "agent")
    return ("mineru", "precision") if _is_complex(*p) else ("markitdown", "agent")


def mineru_api_for(pdf_path: Path) -> str:
    """MinerUConverter 内部路由：复杂或超 Agent 硬限制 → precision，否则 agent。

    一次 _probe 完成（不再二次 open classify_pdf 已探测过的文件）。
    """
    p = _probe(pdf_path)
    if p is None:
        return "precision"   # 探测失败 → 安全升级 precision
    pages = p[0]
    if _is_complex(*p):
        return "precision"
    try:
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0   # stat 失败（罕见 TOCTOU）：按不超限放行，由服务端 Agent 10MB 限制兜底
    if pages > AGENT_MAX_PAGES or size_mb > AGENT_MAX_MB:
        return "precision"
    return "agent"
