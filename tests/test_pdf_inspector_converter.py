import sys
import types

import pytest

from xmd.model import ConvertError, ConvertResult
from xmd.backends.pdf_inspector import PdfInspectorConverter


def _install_fake_pi(monkeypatch, markdown):
    mod = types.ModuleType("pdf_inspector")

    class _Result:
        pass

    def process_pdf(path):
        r = _Result()
        r.markdown = markdown
        return r

    mod.process_pdf = process_pdf
    monkeypatch.setitem(sys.modules, "pdf_inspector", mod)


def test_convert_returns_markdown(tmp_path, monkeypatch):
    _install_fake_pi(monkeypatch, "# 标题\n正文内容")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    r = PdfInspectorConverter().convert(pdf, tmp_path / "x.assets")
    assert isinstance(r, ConvertResult)
    assert "标题" in r.body
    assert r.handled_images is False


def test_convert_empty_markdown(tmp_path, monkeypatch):
    _install_fake_pi(monkeypatch, "")   # Type3 会返回空
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    r = PdfInspectorConverter().convert(pdf, tmp_path / "x.assets")
    assert r.body == ""
    assert r.handled_images is False


def test_convert_missing_module_raises(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pdf_inspector":
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(ConvertError):
        PdfInspectorConverter().convert(pdf, tmp_path / "x.assets")


def test_convert_process_error_raises(tmp_path, monkeypatch):
    mod = types.ModuleType("pdf_inspector")

    def boom(path):
        raise RuntimeError("parse failed")

    mod.process_pdf = boom
    monkeypatch.setitem(sys.modules, "pdf_inspector", mod)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(ConvertError):
        PdfInspectorConverter().convert(pdf, tmp_path / "x.assets")
