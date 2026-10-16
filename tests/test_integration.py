import shutil
from pathlib import Path

from xmd.runner import run


def test_pipeline_tcp_with_images(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "技术").mkdir()
    shutil.copy(tcp_pdf, src / "技术" / "tcp.note.pdf")
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=10)
    md = out / "技术" / "tcp.md"
    assert md.exists()
    text = md.read_text(encoding="utf-8")
    assert "## 笔记配图" in text
    assert "./tcp.assets/" in text
    assert not any(0x2F00 <= ord(c) <= 0x2FDF for c in text)
    assets = out / "技术" / "tcp.assets"
    assert assets.is_dir() and any(assets.iterdir())


def test_collision_no_overwrite(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x").mkdir()
    shutil.copy(tcp_pdf, src / "x" / "同名.note.pdf")
    shutil.copy(tcp_pdf, src / "x" / "同名.pdf")
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=10)
    produced = list((out / "x").glob("*.md"))
    assert len(produced) == 2


def test_empty_dirs_mirrored(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "空1").mkdir()
    (src / "a" / "空2").mkdir(parents=True)
    out = tmp_path / "out"
    run(src, out, jobs=1)
    assert (out / "空1").is_dir()
    assert (out / "a" / "空2").is_dir()


def test_summary_counts_consistent(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=10)
    assert s["total"] == 1
    assert sum(s[k] for k in
               ("ok", "skipped", "error", "need_review", "copied", "collision", "empty", "crash")
               ) == s["total"]
