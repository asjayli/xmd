from pathlib import Path

from xmd.model import Category, FileEntry
from xmd.writer import (
    assets_dir_for,
    build_output_path,
    copy_skip,
    output_ext,
    pretty_md,
    sanitize_filename,
    write_markdown,
)


def _e(rel: str, cat: Category, meta: dict | None = None) -> FileEntry:
    return FileEntry(Path(rel), Path("/src") / rel, cat, meta=meta or {})


def test_sanitize_halfwidth_illegal():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_fullwidth_illegal():
    assert sanitize_filename("a：b？c＊d") == "a_b_c_d"


def test_sanitize_brackets_to_underscore():
    # 设计文档 D1：括号/花括号（半角+全角）→ _，防 md 图片链接在首个 ) 处截断
    assert sanitize_filename("报告(2024)[1]{a}（b）") == "报告_2024__1__a__b_"


def test_sanitize_keeps_chinese_and_space():
    assert sanitize_filename("TCP 三次握手.txt") == "TCP 三次握手.txt"


def test_build_output_note_pdf_strips_both_ext():
    assert build_output_path(_e("子目录/笔记.note.pdf", Category.NOTE_PDF), Path("/out")) \
        == Path("/out/子目录/笔记.md")


def test_build_output_clip_pdf_strips_both_ext():
    assert build_output_path(_e("a/x.clip.pdf", Category.NOTE_PDF), Path("/out")) == Path("/out/a/x.md")


def test_build_output_plain_pdf():
    assert build_output_path(_e("a/x.pdf", Category.PDF), Path("/out")) == Path("/out/a/x.md")


def test_build_output_docx():
    assert build_output_path(_e("a/x.docx", Category.DOC), Path("/out")) == Path("/out/a/x.md")


def test_build_output_skip_preserves_name():
    # 修正源工程缺陷：SKIP 原样复制须保留原名与扩展（源工程误落为 .md 名）
    assert build_output_path(_e("a/b.mp3", Category.SKIP), Path("/out")) == Path("/out/a/b.mp3")


def test_build_output_lake_doc_virtual_tree():
    e = _e("书/章/React", Category.LAKE_DOC, {"sheet_format": "csv"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/章/React.md")


def test_build_output_lake_sheet_csv():
    e = _e("书/数据表", Category.LAKE_SHEET, {"sheet_format": "csv"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/数据表.csv")


def test_build_output_lake_sheet_sheet_plus_is_md():
    e = _e("书/数据表", Category.LAKE_SHEET, {"sheet_format": "sheet"})
    assert build_output_path(e, Path("/out")) == Path("/out/书/数据表.md")


def test_output_ext_matrix():
    assert output_ext(_e("a.pdf", Category.PDF)) == ".md"
    assert output_ext(_e("s", Category.LAKE_SHEET, {"sheet_format": "csv"})) == ".csv"
    assert output_ext(_e("s", Category.LAKE_SHEET, {"sheet_format": "sheet"})) == ".md"
    assert output_ext(_e("s", Category.LAKE_DOC)) == ".md"


def test_assets_dir_sibling():
    assert assets_dir_for(Path("/out/子目录/笔记.md")) == Path("/out/子目录/笔记.assets")


def test_write_markdown_no_images(tmp_path):
    md = tmp_path / "n.md"
    write_markdown(md, "标题", "正文", [])
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# 标题\n\n")
    assert "正文" in text
    assert "笔记配图" not in text


def test_write_markdown_with_images(tmp_path):
    md = tmp_path / "n.md"
    refs = ["./n.assets/img_001.png", "./n.assets/img_002.jpg"]
    write_markdown(md, "T", "B", refs)
    text = md.read_text(encoding="utf-8")
    assert "## 笔记配图" in text
    assert "![img_001](./n.assets/img_001.png)" in text


def test_copy_skip(tmp_path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"xxx")
    dst = tmp_path / "out" / "a.mp3"
    copy_skip(src, dst)
    assert dst.read_bytes() == b"xxx"


def test_pretty_md_strips_trailing_and_blank_runs():
    assert pretty_md("a  \n\n\n\nb\n") == "a\n\nb"
