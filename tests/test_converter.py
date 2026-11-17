import pytest

from xmd.backends.markitdown_backend import MarkdownConverter
from xmd.model import ConvertError, ConvertResult


def test_convert_note_pdf_returns_text(tcp_pdf, tmp_path):
    c = MarkdownConverter()
    r = c.convert(tcp_pdf, tmp_path / "x.assets")
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
    r = c.convert(tcp_pdf, tmp_path / "x.assets")
    assert not any(0x2F00 <= ord(ch) <= 0x2FDF for ch in r.body)


def test_convert_missing_file_raises(tmp_path):
    c = MarkdownConverter()
    with pytest.raises(ConvertError):
        c.convert(tmp_path / "nope.note.pdf", tmp_path / "x.assets")
