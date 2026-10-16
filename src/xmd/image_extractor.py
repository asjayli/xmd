"""用 pymupdf 提取 PDF 内嵌图。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf


class ImageError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedImage:
    rel_ref: str
    page: int


def extract_images(
    pdf_path: Path,
    assets_dir: Path,
    min_size: int = 16,
    force: bool = False,
) -> list[ExtractedImage]:
    if force and assets_dir.exists():
        shutil.rmtree(assets_dir, ignore_errors=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        raise ImageError(f"{type(e).__name__}: {e}") from e
    seen_xref: set[int] = set()
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xref:
                    continue
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                w, h = info.get("width", 0), info.get("height", 0)
                if w < min_size or h < min_size:
                    continue
                seen_xref.add(xref)
                ext = info.get("ext", "png")
                idx = len(results) + 1
                fname = f"img_{idx:03d}.{ext}"
                (assets_dir / fname).write_bytes(info["image"])
                results.append(ExtractedImage(f"./{assets_dir.name}/{fname}", page_idx))
    finally:
        doc.close()
    return results
