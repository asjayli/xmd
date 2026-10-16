from pathlib import Path

from xmd.classifier import Category, classify


def test_note_pdf():
    assert classify(Path("笔记/abc.note.pdf")) is Category.NOTE_PDF


def test_clip_pdf_is_note_pdf():
    assert classify(Path("剪藏/x.clip.pdf")) is Category.NOTE_PDF


def test_plain_pdf():
    assert classify(Path("a/附件.pdf")) is Category.PDF


def test_doc_types():
    assert classify(Path("a.docx")) is Category.DOC
    assert classify(Path("b.xlsx")) is Category.DOC
    assert classify(Path("c.pptx")) is Category.DOC


def test_md():
    assert classify(Path("a.md")) is Category.MD


def test_old_ppt_is_skip():
    assert classify(Path("老.ppt")) is Category.SKIP


def test_media_archive_skip():
    assert classify(Path("a.mp3")) is Category.SKIP
    assert classify(Path("b.rar")) is Category.SKIP
    assert classify(Path("c.zip")) is Category.SKIP


def test_unknown_is_skip():
    assert classify(Path("a.xyz")) is Category.SKIP


def test_note_pdf_takes_priority_over_pdf():
    # 双扩展名优先匹配
    assert classify(Path("abc.note.pdf")) is Category.NOTE_PDF


def test_classify_lakebook(tmp_path):
    from xmd.classifier import Category, classify
    assert classify(tmp_path / "b.lakebook") is Category.LAKEBOOK
