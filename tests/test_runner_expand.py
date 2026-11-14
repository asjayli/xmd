"""runner 容器展开集成：混合批量、--no-sheet 过滤、损坏归档、tmp 清理、归档 mtime 续传。"""
import shutil

from conftest import make_lakebook

from xmd.runner import run

DOC = {"type": "Doc", "format": "lake", "body": "<h1>标题</h1><p>内容文字</p>", "body_asl": ""}
TOC = [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"},
       {"title": "表", "type": "DOC", "url": "s1", "level": 0, "uuid": "s1"}]


def _sheet_body():
    import json, zlib
    data = {"data": {"0": {"0": {"v": "a"}, "1": {"v": "b"}}}}
    return json.dumps({"format": "lakesheet",
                       "sheet": zlib.compress(json.dumps(data).encode()).decode("latin-1")})


def test_run_mixed_pdf_and_lakebook(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(tcp_pdf, src / "t.note.pdf")
    make_lakebook(src / "book.lakebook",
                  [{"url": "d1", "doc": DOC}, {"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  TOC)
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=5)
    assert (out / "t.md").exists()
    assert (out / "book" / "文档.md").exists()
    assert (out / "book" / "表.csv").exists()
    assert s["ok"] == 3


def test_run_no_sheet_filters_sheet_tasks(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook",
                  [{"url": "d1", "doc": DOC},
                   {"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  TOC)
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=5, convert_sheets=False)
    assert (out / "book" / "文档.md").exists()
    assert not (out / "book" / "表.csv").exists()
    assert s["total"] == 1 and s["ok"] == 1


def test_run_sheet_plus_format(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook",
                  [{"url": "s1", "doc": {"type": "Sheet", "format": "lakesheet", "body": _sheet_body()}}],
                  [TOC[1]])
    out = tmp_path / "out"
    run(src, out, jobs=1, sheet_format="sheet")
    md = out / "book" / "表.md"
    assert md.exists()
    assert "excel-pro-plugin" in md.read_text(encoding="utf-8")


def test_run_corrupt_lakebook_recorded_error(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.lakebook").write_text("not a tar")
    out = tmp_path / "out"
    s = run(src, out, jobs=1)
    assert s["error"] == 1
    assert "bad.lakebook" in (out / "convert.log").read_text(encoding="utf-8")


def test_run_resume_lakebook_by_archive_mtime(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], [TOC[0]])
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=5)
    s2 = run(src, out, jobs=1, min_chars=5)
    assert s2["skipped"] == s2["total"] == 1


def test_run_tmpdir_cleaned(tmp_path):
    import tempfile
    from pathlib import Path
    before = set(Path(tempfile.gettempdir()).glob("xmd_lakebook_*"))
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], [TOC[0]])
    run(src, tmp_path / "out", jobs=1, min_chars=5)
    after = set(Path(tempfile.gettempdir()).glob("xmd_lakebook_*"))
    assert after == before   # 无新增残留
