"""lakebook 展开器测试：最小 tar fixtures 覆盖 uuid/level 双建树与异常路径。"""
import io
import json
import os
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


def test_expand_traversal_titles_sanitized(tmp_path):
    # mar #1 PoC 回归：两层 `..` TITLE + DOC pwn → 输出路径目录段被替换为 _，不越出输出根
    from xmd.runner import preprocess
    toc = [
        {"title": "..", "type": "TITLE", "url": "", "level": 0, "uuid": "t1"},
        {"title": "..", "type": "TITLE", "url": "", "level": 1, "uuid": "t2", "parent_uuid": "t1"},
        {"title": "pwn", "type": "DOC", "url": "d1", "level": 2, "uuid": "d1", "parent_uuid": "t2"},
    ]
    p = tmp_path / "book.lakebook"
    make_lakebook(p, [{"url": "d1", "doc": DOC}], toc)
    tasks = preprocess(_expand(p), tmp_path / "out")
    # 清理发生在 build_output_path：目录段 `..` → `_`，末段补 .md
    assert [str(t.output_md) for t in tasks] == [str(tmp_path / "out" / "book" / "_" / "_" / "pwn.md")]


def test_run_traversal_lakebook_stays_in_output(tmp_path):
    # mar #1 端到端：恶意 TOC 的全部输出文件 resolve 后位于 output_root 内，无外逸写
    from xmd.runner import run
    toc = [
        {"title": "..", "type": "TITLE", "url": "", "level": 0, "uuid": "t1"},
        {"title": "..", "type": "TITLE", "url": "", "level": 1, "uuid": "t2", "parent_uuid": "t1"},
        {"title": "pwn", "type": "DOC", "url": "d1", "level": 2, "uuid": "d1", "parent_uuid": "t2"},
    ]
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], toc)
    out = tmp_path / "out"
    s = run(src, out, jobs=1, min_chars=1)
    assert s["total"] == 1
    assert (out / "book" / "_" / "_" / "pwn.md").exists()
    assert not (tmp_path / "pwn.md").exists()   # 修复前穿越写到 out 外
    root = out.resolve()
    for f in out.rglob("*"):
        if f.is_file():
            assert f.resolve().is_relative_to(root)


def _outside_secret(name: str, tmp_base) -> Path:
    """在 repo_dir 上两级（展开 tmp 之外）放置越界目标文件，模拟归档外敏感 json。"""
    secret = tmp_base / f"{name}.json"
    secret.write_text(json.dumps({"doc": {"type": "Doc", "format": "lake",
                                          "body": "<p>机密</p>", "body_asl": ""}}),
                      encoding="utf-8")
    return secret


def test_expand_url_escape_skipped(tmp_path):
    # mar #3 PoC 回归：url 含 `..` 的 DOC 条目被跳过，不读取归档外文件，无异常外逸
    # 展开 tmp 为 <systmp>/xmd_lakebook_*/<repo_id>，url ../../<name> 指向 <systmp>/<name>
    import tempfile
    from pathlib import Path
    sys_tmp = Path(tempfile.gettempdir())
    secret = _outside_secret(f"secret_mar3_{os.getpid()}", sys_tmp)
    try:
        p = tmp_path / "b.lakebook"
        make_lakebook(p, [], [{"title": "逃", "type": "DOC",
                               "url": f"../../{secret.stem}", "level": 0}])
        assert _expand(p) == []   # 越界条目跳过（entries 为空），无异常
    finally:
        secret.unlink(missing_ok=True)


def test_expand_url_absolute_path_skipped(tmp_path):
    # mar #3：绝对路径 url 同样跳过（repo_dir / "/abs/x.json" 折叠为 /abs/x.json）
    outside = _outside_secret(f"abs_mar3_{os.getpid()}", tmp_path)
    try:
        p = tmp_path / "b.lakebook"
        make_lakebook(p, [], [{"title": "逃", "type": "DOC",
                               "url": str(outside.with_suffix("")), "level": 0}])
        assert _expand(p) == []
    finally:
        outside.unlink(missing_ok=True)


def test_expand_tmpdir_mkdtemp_under_base(tmp_path, lb):
    # mar #11+#16：tmp 由 mkdtemp 独占创建（0700），位于调用方指定基准目录
    base = tmp_path / "base"
    base.mkdir()
    entries, tmp = expand_lakebook(lb, tmp_base=base)
    import shutil
    try:
        assert tmp.parent == base
        assert tmp.name.startswith("xmd_lakebook_")
        assert tmp.stat().st_mode & 0o777 == 0o700   # mkdtemp 独占语义
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_expand_fifo_member_rejected(tmp_path):
    # mar #11：设备/FIFO 成员拒绝提取
    p = tmp_path / "dev.lakebook"
    with tarfile.open(p, "w") as tf:
        ti = tarfile.TarInfo("123/fifo")
        ti.type = tarfile.FIFOTYPE
        tf.addfile(ti)
    with pytest.raises(ExpandError, match="设备"):
        expand_lakebook(p)


def test_run_tmpdir_on_output_disk_and_cleaned(tmp_path, monkeypatch):
    # mar #16：runner 把展开 tmp 基准目录指定为输出盘 .xmd-tmp；run 结束无残留
    import tempfile
    from pathlib import Path
    import xmd.expanders as expmod
    from xmd.runner import run
    seen = {}
    real = expmod.expand_lakebook

    def spy(archive, **kw):
        seen["tmp_base"] = kw.get("tmp_base")
        return real(archive, **kw)

    monkeypatch.setattr(expmod, "expand_lakebook", spy)
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}],
                  [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"}])
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=5)
    assert seen["tmp_base"] == out / ".xmd-tmp"   # 落输出盘而非系统 tmpfs
    assert not (out / ".xmd-tmp").exists()        # run 结束清理基准目录
    assert not any(Path(tempfile.gettempdir()).glob("xmd_lakebook_*"))


def test_expand_single_corrupt_doc_skipped(tmp_path):
    # mar #4：单个损坏 doc json 跳过（与文件缺失同语义），完好文档照常展开/转换
    import yaml as _yaml
    from xmd.runner import run
    toc = [{"title": "好文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"},
           {"title": "坏文档", "type": "DOC", "url": "d2", "level": 0, "uuid": "d2"}]
    meta_inner = {"book": {"name": "测试库",
                           "tocYml": _yaml.safe_dump(toc, allow_unicode=True)}}
    p = tmp_path / "book.lakebook"
    with tarfile.open(p, "w") as tf:
        entries = [
            ("123/$meta.json", json.dumps({"meta": json.dumps(meta_inner)})),
            ("123/d1.json", json.dumps({"doc": DOC})),
            ("123/d2.json", "{corrupted"),   # 损坏 json：不应拖垮整本书
        ]
        for name, data in entries:
            b = data.encode("utf-8")
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tf.addfile(ti, io.BytesIO(b))
    entries = _expand(p)
    assert [e.meta["url"] for e in entries] == ["d1"]   # 仅完好文档成为任务
    # 端到端：批量 status 无整书 error，完好文档成功落盘
    out = tmp_path / "out"
    s = run(tmp_path, out, jobs=1, min_chars=1)
    assert s["error"] == 0 and s["ok"] == 1
    assert (out / "book" / "好文档.md").exists()


def test_extract_tar_single_pass_cleans_partial(tmp_path):
    # mar #17：单遍解压下，恶意成员位于好成员之后时，半解压状态须清理
    from xmd.expanders.lakebook import _extract_tar
    p = tmp_path / "evil.lakebook"
    with tarfile.open(p, "w") as tf:
        b = b"hello"
        ti = tarfile.TarInfo("good.txt")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
        ti2 = tarfile.TarInfo("../../escape.txt")
        ti2.size = len(b)
        tf.addfile(ti2, io.BytesIO(b))
    target = tmp_path / "target"
    with pytest.raises(ExpandError):
        _extract_tar(p, target)
    assert not target.exists() or not any(target.iterdir())   # 无半解压残留
