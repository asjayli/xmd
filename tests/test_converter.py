import pytest

from xmd.backends.markitdown_backend import MarkdownConverter
from xmd.model import ConvertError, ConvertResult
from pathlib import Path


def _task(path, tmp_path):
    """构造最小 Task（mar #32 后协议 task 必填）。"""
    from xmd.classifier import Category
    from xmd.model import FileEntry, Task
    e = FileEntry(Path(path.name), path, Category.NOTE_PDF)
    return Task(e, tmp_path / "out.md", tmp_path / "out.assets", False)



def test_convert_note_pdf_returns_text(tcp_pdf, tmp_path):
    c = MarkdownConverter()
    r = c.convert(tcp_pdf, tmp_path / "x.assets", _task(tcp_pdf, tmp_path))
    assert isinstance(r, ConvertResult)
    assert isinstance(r.body, str)
    # 注：len/关键词断言绑定 markitdown 提取行为——升级 markitdown 时为预期
    # 复核点；工程不变量（状态/落盘）另见 test_runner.test_pdf_fixtures_status_invariants
    assert len(r.body) > 100
    assert "TCP" in r.body or "握手" in r.body
    assert r.handled_images is False
    assert r.image_refs == []


def test_convert_normalized_has_no_kangxi(tcp_pdf, tmp_path):
    c = MarkdownConverter()
    r = c.convert(tcp_pdf, tmp_path / "x.assets", _task(tcp_pdf, tmp_path))
    assert not any(0x2F00 <= ord(ch) <= 0x2FDF for ch in r.body)


def test_convert_missing_file_raises(tmp_path):
    c = MarkdownConverter()
    with pytest.raises(ConvertError):
        c.convert(tmp_path / "nope.note.pdf", tmp_path / "x.assets", _task(tmp_path / "nope.note.pdf", tmp_path))
