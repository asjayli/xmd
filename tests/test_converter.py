import pytest

from xmd.backends.markitdown_backend import MarkdownConverter
from xmd.model import ConvertError, ConvertResult


def test_convert_note_pdf_returns_text(tcp_pdf, tmp_path):
    c = MarkdownConverter()
    r = c.convert(tcp_pdf, tmp_path / "x.assets")
    assert isinstance(r, ConvertResult)
    assert isinstance(r.body, str)
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
