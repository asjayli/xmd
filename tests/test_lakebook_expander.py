"""lakebook 展开器测试：最小 tar fixtures 覆盖 uuid/level 双建树与异常路径。"""
import io
import tarfile

import pytest

from conftest import make_lakebook
from xmd.classifier import Category
from xmd.expanders import ExpandError, expand_lakebook


DOC = {"type": "Doc", "format": "lake", "body": "<h1>T</h1>", "body_asl": ""}
SHEET = {"type": "Sheet", "format": "lakesheet", "body": "{}"}
TOC_UUID = [
    {"title": "第一章", "type": "TITLE", "url": "", "level": 0, "uuid": "t1"},
    {"title": "入门", "type": "DOC", "url": "d1", "level": 1, "uuid": "d1", "parent_uuid": "t1"},
    {"title": "数据表", "type": "DOC", "url": "s1", "level": 1, "uuid": "s1", "parent_uuid": "t1"},
]


@pytest.fixture
def lb(tmp_path):
    p = tmp_path / "mybook.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}, {"url": "s1", "doc": SHEET}], TOC_UUID)
    return p


def _expand(lb, **kw):
    entries, tmp = expand_lakebook(lb, **kw)
    import shutil
    try:
        return entries
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_expand_uuid_tree(tmp_path, lb):
    entries = _expand(lb)
    rels = [str(e.rel_path) for e in entries]
    assert rels == ["mybook/第一章/入门", "mybook/第一章/数据表"]
    cats = {str(e.rel_path): e.category for e in entries}
    assert cats["mybook/第一章/入门"] is Category.LAKE_DOC
    assert cats["mybook/第一章/数据表"] is Category.LAKE_SHEET


def test_expand_entry_meta_and_mtime(tmp_path, lb):
    # 直接展开（不经 _expand 助手）：断言 abs_path 存活需在 tmp 清理前进行
    import shutil
    entries, tmp = expand_lakebook(lb)
    try:
        e = entries[0]
        assert e.meta["title"] == "入门"
        assert e.meta["download_image"] is True
        assert e.meta["sheet_format"] == "csv"
        assert e.mtime == lb.stat().st_mtime
        assert (e.abs_path).exists()   # tmp 内 doc json
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_expand_opts_propagate(tmp_path, lb):
    entries = _expand(lb, download_image=False, sheet_format="sheet")
    assert entries[0].meta["download_image"] is False
    assert entries[1].meta["sheet_format"] == "sheet"


def test_expand_level_fallback(tmp_path):
    p = tmp_path / "old.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}], TOC_UUID, with_uuid=False)
    entries = _expand(p)
    assert str(entries[0].rel_path) == "old/第一章/入门"


def test_expand_level_skip(tmp_path):
    # 跳级（0→2）多帧压栈对齐栈深，回退正确
    toc = [
        {"title": "A", "type": "TITLE", "url": "", "level": 0},
        {"title": "deep", "type": "DOC", "url": "d1", "level": 2},
        {"title": "B", "type": "DOC", "url": "d2", "level": 0},
    ]
    p = tmp_path / "skip.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}, {"url": "d2", "doc": DOC}], toc, with_uuid=False)
    entries = _expand(p)
    rels = [str(e.rel_path) for e in entries]
    assert rels == ["skip/A/deep", "skip/B"]   # 跳级空占位段折叠：Path 空段折叠为 skip/A/deep


def test_expand_corrupt_archive_raises(tmp_path):
    p = tmp_path / "bad.lakebook"
    p.write_text("not a tar")
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_symlink_member_rejected(tmp_path):
    p = tmp_path / "evil.lakebook"
    with tarfile.open(p, "w") as tf:
        ti = tarfile.TarInfo("123/lnk")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        tf.addfile(ti)
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_no_meta_raises(tmp_path):
    p = tmp_path / "nometa.lakebook"
    with tarfile.open(p, "w") as tf:
        b = b"{}"
        ti = tarfile.TarInfo("123/x.json"); ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    with pytest.raises(ExpandError):
        expand_lakebook(p)


def test_expand_missing_doc_skipped(tmp_path):
    toc = [{"title": "T", "type": "DOC", "url": "gone", "level": 0}]
    p = tmp_path / "m.lakebook"
    make_lakebook(p, [], toc)
    assert _expand(p) == []
