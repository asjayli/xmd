from pathlib import Path

from xmd.classifier import Category
from xmd.walker import scan_input, walk


def _make(root: Path):
    (root / "笔记本A").mkdir()
    (root / "笔记本A" / "x.note.pdf").write_bytes(b"")
    (root / "空笔记本B").mkdir()                      # 空目录
    (root / "附件" / "deep").mkdir(parents=True)
    (root / "附件" / "deep" / "y.pdf").write_bytes(b"")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("")


def test_walk_returns_files_and_dirs(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make(root)
    res = walk(root)
    rels = [f.rel_path.name for f in res.files]
    assert "x.note.pdf" in rels and "y.pdf" in rels


def test_walk_keeps_empty_dirs(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make(root)
    res = walk(root)
    dir_str = [str(d) for d in res.dirs]
    assert any("空笔记本B" in s for s in dir_str)


def test_walk_skips_hidden_dirs(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make(root)
    res = walk(root)
    assert all(".git" not in f.rel_path.parts for f in res.files)
    assert all(".git" not in d.parts for d in res.dirs)


def test_walk_classifies(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make(root)
    res = walk(root)
    cat = {f.rel_path.name: f.category for f in res.files}
    assert cat["x.note.pdf"] is Category.NOTE_PDF
    assert cat["y.pdf"] is Category.PDF


def test_walk_sorted(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    for n in ["c.note.pdf", "a.note.pdf", "b.note.pdf"]:
        (root / n).write_bytes(b"")
    res = walk(root)
    names = [f.rel_path.name for f in res.files]
    assert names == sorted(names)


def test_scan_input_single_file(tmp_path):
    p = tmp_path / "a.note.pdf"
    p.write_bytes(b"x")
    res = scan_input(p)
    assert len(res.files) == 1
    assert res.files[0].rel_path == Path("a.note.pdf")
    assert res.files[0].category is Category.NOTE_PDF
    assert res.dirs == []


def test_scan_input_lakebook_file(tmp_path):
    p = tmp_path / "b.lakebook"
    p.write_bytes(b"x")
    res = scan_input(p)
    assert res.files[0].category is Category.LAKEBOOK
