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
