from xmd.backends.auto import AutoConverter
from xmd.model import ConvertResult


def test_routes_complex_to_mineru(tmp_path, monkeypatch):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr("xmd.backends.auto.classify_pdf",
                        lambda p: ("mineru", "precision"))

    class FakeMineru:
        def __init__(self, **k):
            pass

        def convert(self, p, a):
            return ConvertResult(body="from mineru", handled_images=True)

    class FakeMD:
        def __init__(self):
            pass

    monkeypatch.setattr("xmd.backends.auto.MinerUConverter", FakeMineru)
    monkeypatch.setattr("xmd.backends.auto.MarkdownConverter", FakeMD)

    r = AutoConverter().convert(pdf, tmp_path / "x.assets")
    assert r.body == "from mineru"
    assert r.handled_images is True


def test_routes_simple_to_markitdown(tmp_path, monkeypatch):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr("xmd.backends.auto.classify_pdf",
                        lambda p: ("markitdown", "agent"))

    class FakeMineru:
        def __init__(self, **k):
            pass

    class FakeMD:
        def __init__(self):
            pass

        def convert(self, p, a):
            return ConvertResult(body="from md", handled_images=False)

    monkeypatch.setattr("xmd.backends.auto.MinerUConverter", FakeMineru)
    monkeypatch.setattr("xmd.backends.auto.MarkdownConverter", FakeMD)

    r = AutoConverter().convert(pdf, tmp_path / "x.assets")
    assert r.body == "from md"
    assert r.handled_images is False


def test_auto_probes_pdf_once(tmp_path, monkeypatch):
    # mar #14：auto→mineru 链路同一 PDF 只探测一次（classify_pdf 与
    # mineru_api_for 的 _probe 结果经进程内 memo 共享）
    import xmd.router as rmod
    from xmd.model import ConvertError
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    calls = {"n": 0}

    def counting(p):
        calls["n"] += 1
        return (2, True, 0, 5000)   # 复杂（Type3）→ auto 路由 mineru

    monkeypatch.setattr(rmod, "_probe", counting)
    conv = AutoConverter(mineru_opts={"token": "t"})
    # 复杂路径进 MinerU：_resolve_api→mineru_api_for 复用探测；随后页数探测
    # 失败（伪 PDF）抛 ConvertError——探测计数在此之前已完成
    import pytest
    with pytest.raises(ConvertError):
        conv.convert(pdf, tmp_path / "x.assets")
    assert calls["n"] == 1   # 修复前 classify_pdf + mineru_api_for 各探测一次 = 2
