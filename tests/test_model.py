from pathlib import Path

from xmd.model import Category, ConvertResult, FileEntry, Task


def test_convert_result_defaults():
    r = ConvertResult(body="x")
    assert r.image_refs == []
    assert r.handled_images is False
    assert r.handled_output is False


def test_file_entry_optional_fields_default():
    e = FileEntry(Path("a.pdf"), Path("/a.pdf"), Category.PDF)
    assert e.mtime is None
    assert e.meta == {}


def test_task_holds_entry_and_paths():
    e = FileEntry(Path("a.pdf"), Path("/a.pdf"), Category.PDF)
    t = Task(e, Path("/o/a.md"), Path("/o/a.assets"), False)
    assert t.entry is e and t.collision is False
