"""lake_doc 后端测试：LaTeX 还原/代码块语言/图片提升/图片下载。"""
import json
import urllib.parse
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """mar #22：重试退避的 time.sleep 全部打桩（原文件真睡 3s+，现 <1s）。"""
    monkeypatch.setattr("xmd.backends.lake_doc.time.sleep", lambda s: None)

from xmd.backends.lake_doc import (
    LakeDocBackend,
    extract_latex_from_asl,
    html_to_markdown,
    replace_latex_images,
)
from xmd.model import Category, ConvertError, FileEntry, Task


def _card(src: str, code: str) -> str:
    val = "data:" + urllib.parse.quote(json.dumps({"src": src, "code": code}))
    return f'<card name="math" value="{val}"/>'


def _task(tmp_path, meta=None):
    """构造 lake_doc 任务（后端协议读 task.entry.meta）。"""
    entry = FileEntry(Path("b/标题"), tmp_path / "x.json", Category.LAKE_DOC,
                      meta={"title": "标题", "download_image": False, **(meta or {})})
    return Task(entry, tmp_path / "标题.md", tmp_path / "标题.assets", False)


def test_extract_latex_from_asl():
    asl = _card("https://cdn/1.png", "E=mc^2")
    d = extract_latex_from_asl(asl)
    assert d == {"https://cdn/1.png": "E=mc^2"}


def test_extract_latex_empty():
    assert extract_latex_from_asl("") == {}


def test_replace_latex_inline():
    d = {"u1": "E=mc^2"}
    html = "<span><img src=\"u1\"/></span>"
    out = replace_latex_images(html, d)
    assert "$E=mc^2$" in out
    assert "img" not in out


def test_replace_latex_block():
    d = {"u1": "\\frac{1}{2}\nmv^2"}
    html = '<p><img src="u1"/></p>'
    out = replace_latex_images(html, d)
    assert "$$" in out and "\\frac{1}{2}" in out


def test_html_to_markdown_basic():
    md = html_to_markdown("<h1>T</h1><p><strong>b</strong></p><ul><li>x</li></ul>")
    assert "# T" in md and "**b**" in md and "- x" in md


def test_code_language_from_data_language():
    html = ('<div data-lake-card="codeblock" data-language="bash"><pre class="cm-s-default">'
            '<code>ls -l</code></pre></div>')
    md = html_to_markdown(html)
    assert "```bash" in md


def test_table_cell_image_lifted():
    html = ('<table><tbody><tr><td>a</td>'
            '<td><img src="https://x/1.png"/></td></tr></tbody></table>')
    md = html_to_markdown(html)
    assert "![image](https://x/1.png)" in md or "](https://x/1.png)" in md


def _write_doc(tmp_path, doc: dict, name="x.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"doc": doc}), encoding="utf-8")
    return p


def test_backend_convert_basic(tmp_path):
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": "<h1>标题</h1><p>内容文字</p>", "body_asl": ""})
    r = LakeDocBackend().convert(src, tmp_path / "标题.assets", _task(tmp_path))
    assert r.handled_images is True
    assert "# 标题" in r.body and "内容文字" in r.body


def test_backend_keeps_external_images_when_no_download(tmp_path):
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    r = LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    assert "https://x/1.png" in r.body   # download_image=False → 保留外链


def test_backend_downloads_images_to_assets(tmp_path, monkeypatch):
    class FakeResp:
        content = b"PNGDATA"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", lambda url, timeout: FakeResp())
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    assets = tmp_path / "标题.assets"
    task = _task(tmp_path, {"download_image": True})
    r = LakeDocBackend().convert(src, assets, task)
    assert (assets / "img_001.png").read_bytes() == b"PNGDATA"
    assert f"./{assets.name}/img_001.png" in r.body


def test_backend_download_failure_notice(tmp_path, monkeypatch):
    def boom(url, timeout):
        raise RuntimeError("net down")

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", boom)
    src = _write_doc(tmp_path, {"type": "Doc", "format": "lake",
                                "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""})
    task = _task(tmp_path, {"download_image": True})
    r = LakeDocBackend().convert(src, tmp_path / "标题.assets", task)
    assert "[图片缺失" in r.body and "https://x/1.png" in r.body


def test_backend_latex_restored(tmp_path):
    src = _write_doc(tmp_path, {
        "type": "Doc", "format": "lake",
        "body": '<p><img src="u1"/></p>',
        "body_asl": _card("u1", "E=mc^2")})
    r = LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    assert "E=mc^2" in r.body and "$$" in r.body


def test_backend_corrupt_json_raises_convert_error(tmp_path):
    src = tmp_path / "x.json"
    src.write_text("{corrupted", encoding="utf-8")
    with pytest.raises(ConvertError):
        LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))


@pytest.mark.parametrize("src", [
    "http://127.0.0.1:1/x.png",        # 环回
    "http://169.254.169.254/latest/meta-data",   # 链路本地（云元数据）
    "http://10.0.0.1/x.png",           # 私网 A
    "http://192.168.1.1/x.png",        # 私网 C
    "http://[::1]/x.png",              # IPv6 环回
    "file:///etc/passwd",              # 非 http(s) 协议
    "ftp://x/1.png",
])
def test_backend_blocks_intranet_image_src(tmp_path, monkeypatch, src):
    # mar #9：环回/私网/链路本地/非法协议的 img src 不发起网络请求，正文给缺失提示
    def must_not_call(url, timeout):
        raise AssertionError(f"不应发起请求: {url}")

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", must_not_call)
    doc = {"type": "Doc", "format": "lake", "body": f'<p><img src="{src}"/></p>', "body_asl": ""}
    src_file = _write_doc(tmp_path, doc)
    task = _task(tmp_path, {"download_image": True})
    r = LakeDocBackend().convert(src_file, tmp_path / "标题.assets", task)
    assert "[图片缺失" in r.body and src in r.body
    assert "禁止" in r.body


def test_backend_public_image_still_downloads(tmp_path, monkeypatch):
    # mar #9 回归：https 公网地址不受 SSRF 校验影响（正常下载路径）
    class FakeResp:
        content = b"PNG"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", lambda url, timeout: FakeResp())
    doc = {"type": "Doc", "format": "lake", "body": '<p><img src="https://x/1.png"/></p>',
           "body_asl": ""}
    src_file = _write_doc(tmp_path, doc)
    assets = tmp_path / "标题.assets"
    r = LakeDocBackend().convert(src_file, assets, _task(tmp_path, {"download_image": True}))
    assert (assets / "img_001.png").read_bytes() == b"PNG"


def test_backend_body_parsed_at_most_twice(tmp_path, monkeypatch):
    # mar #6：含图片+公式文档的 body 解析次数 ≤2（latex 迁移函数 1 次 + 主 soup 1 次；
    # body_asl 是独立输入不计入——与 mar #6 原始口径一致）
    import xmd.backends.lake_doc as mod
    calls: list = []
    real = mod.BeautifulSoup

    class Counting(real):
        def __init__(self, html, *a, **k):
            calls.append(html if isinstance(html, str) else "<soup>")
            super().__init__(html, *a, **k)

    monkeypatch.setattr(mod, "BeautifulSoup", Counting)
    doc = {"type": "Doc", "format": "lake",
           "body": '<p>正文标记Xy7 <img src="u1"/><img src="https://x/1.png"/></p>',
           "body_asl": _card("u1", "E=mc^2")}
    src = _write_doc(tmp_path, doc)
    r = LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    assert "E=mc^2" in r.body   # 行为不变：公式还原正常
    body_parses = [h for h in calls if isinstance(h, str) and "正文标记Xy7" in h]
    assert len(body_parses) == 2


def test_backend_image_doc_single_body_parse(tmp_path, monkeypatch):
    # mar #6：纯图片文档 body 只解析 1 次（下载/提升复用同一棵树）
    import xmd.backends.lake_doc as mod
    calls: list = []
    real = mod.BeautifulSoup

    class Counting(real):
        def __init__(self, html, *a, **k):
            calls.append(html if isinstance(html, str) else "<soup>")
            super().__init__(html, *a, **k)

    monkeypatch.setattr(mod, "BeautifulSoup", Counting)
    doc = {"type": "Doc", "format": "lake",
           "body": '<p>正文标记Xy7 <img src="https://x/1.png"/></p>', "body_asl": ""}
    src = _write_doc(tmp_path, doc)
    LakeDocBackend().convert(src, tmp_path / "a.assets", _task(tmp_path))
    body_parses = [h for h in calls if isinstance(h, str) and "正文标记Xy7" in h]
    assert len(body_parses) == 1


def test_download_write_failure_branch(tmp_path, monkeypatch):
    # mar #19：写盘失败（OSError）走 write_fail 分支，正文给写入失败提示
    from xmd.backends.lake_doc import _download_image_to_file

    class FakeResp:
        content = b"PNG"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("xmd.backends.lake_doc._download_image_with_retry",
                        lambda src: FakeResp())
    assets = tmp_path / "a.assets"
    assets.mkdir()
    (assets / "img_001.png").mkdir()   # 同名目录占位 → write_bytes 必然 OSError
    outcome = _download_image_to_file(1, "https://x/1.png", assets)
    assert outcome[0] == "write_fail" and isinstance(outcome[2], OSError)


def test_table_cell_image_lifted_exact_syntax():
    # mar #22：原 or 弱断言拆分为精确图片语法断言
    html = ('<table><tbody><tr><td>a</td>'
            '<td><img src="https://x/1.png"/></td></tr></tbody></table>')
    md = html_to_markdown(html)
    assert "![](https://x/1.png)" in md   # 图片语法完整保留（非裸链接文本）


def test_heading_image_lifted():
    # mar #22：标题内图片同样提升（_HEADING_RE 分支）
    html = '<h2>章题<img src="https://x/2.png"/></h2><p>正文</p>'
    md = html_to_markdown(html)
    assert "## 章题" in md
    assert "![](https://x/2.png)" in md   # 图片不随标题行丢失


def test_download_write_failure_notice_in_body(tmp_path, monkeypatch):
    # mar #22：写盘 OSError 分支的正文文案
    class FakeResp:
        content = b"PNG"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", lambda url, timeout: FakeResp())
    assets = tmp_path / "标题.assets"
    assets.mkdir()
    (assets / "img_001.png").mkdir()   # 同名目录占位 → 写盘必 OSError
    doc = {"type": "Doc", "format": "lake",
           "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""}
    src = _write_doc(tmp_path, doc)
    r = LakeDocBackend().convert(src, assets, _task(tmp_path, {"download_image": True}))
    assert "[图片缺失：写入失败]" in r.body and "https://x/1.png" in r.body


def test_download_retry_succeeds_after_first_failure(tmp_path, monkeypatch):
    # mar #22：首失败次成功路径——重试后拿到响应；退避 sleep(1) 已被桩记录
    sleeps: list = []
    monkeypatch.setattr("xmd.backends.lake_doc.time.sleep",
                        lambda s: sleeps.append(s))
    state = {"n": 0}

    class FakeResp:
        content = b"PNG"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    def flaky(url, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("first attempt down")
        return FakeResp()

    monkeypatch.setattr("xmd.backends.lake_doc.http_get", flaky)
    doc = {"type": "Doc", "format": "lake",
           "body": '<p><img src="https://x/1.png"/></p>', "body_asl": ""}
    src = _write_doc(tmp_path, doc)
    assets = tmp_path / "标题.assets"
    r = LakeDocBackend().convert(src, assets, _task(tmp_path, {"download_image": True}))
    assert (assets / "img_001.png").read_bytes() == b"PNG"   # 重试成功落盘
    assert sleeps == [1]    # 第 1 次失败后退避 1s（桩记录，无真睡）


def test_lift_bare_tbody_fragment_anchor():
    # mar #23 PoC 回归：无 table 外壳的裸 tbody 片段，提升锚点应为 tbody
    # （片段末尾）而非单元格内（p 落进 tr 属非法结构）
    from bs4 import BeautifulSoup
    from xmd.backends.lake_doc import _lift_embedded_images_in
    html = '<tbody><tr><td>a</td><td><img src="https://x/1.png"/></td></tr></tbody>'
    soup = BeautifulSoup(html, "html.parser")
    _lift_embedded_images_in(soup)
    tr = soup.find("tr")
    p = soup.find("p")
    assert p is not None and p.parent is not tr          # p 不在 tr 内
    assert p.parent is soup or p.parent.name == "tbody"  # 锚定在片段层
