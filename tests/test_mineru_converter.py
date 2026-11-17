import io
import time
import zipfile

import pytest
import requests

import xmd.backends.mineru as mmod
from xmd.model import ConvertError, ConvertResult
from xmd.backends.mineru import MinerUConverter


class FakeResp:
    def __init__(self, status=200, json_data=None, content=b"", text=""):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _pdf(path, pages=1):
    import pymupdf
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def _zip_md(md_text, images=None):
    images = images or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x/full.md", md_text)
        for name, data in images.items():
            z.writestr(f"x/images/{name}", data)
    return buf.getvalue()


# ---- Precision ----

def test_precision_success(tmp_path, monkeypatch):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    assets = tmp_path / "x.assets"
    zb = _zip_md("# 标题\n![](images/a.jpg)\n正文", {"a.jpg": b"IMG"})

    def post(url, headers=None, json=None, **k):
        assert "file-urls/batch" in url
        assert headers["Authorization"] == "Bearer t"
        return FakeResp(json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}})

    put_count = [0]

    def put(url, data=None, **k):
        put_count[0] += 1
        return FakeResp(status=200)

    def get(url, headers=None, **k):
        if "extract-results" in url:
            return FakeResp(json_data={"code": 0, "data": {"extract_result": [
                {"state": "done", "full_zip_url": "http://zip"}]}})
        if url == "http://zip":
            return FakeResp(content=zb)
        return FakeResp(status=404)

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", put)
    monkeypatch.setattr(requests, "get", get)

    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0)
    r = c.convert(pdf, assets)
    assert isinstance(r, ConvertResult)
    assert r.handled_images is True
    assert (assets / "a.jpg").exists()
    assert "./x.assets/a.jpg" in r.body
    assert "标题" in r.body
    assert put_count[0] == 1


# ---- Agent ----

def test_agent_success(tmp_path, monkeypatch):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)

    def post(url, headers=None, json=None, **k):
        assert "agent/parse/file" in url
        assert "Authorization" not in headers   # agent 无需 token
        return FakeResp(json_data={"code": 0, "data": {"task_id": "t1", "file_url": "http://up"}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))

    def get(url, headers=None, **k):
        if "agent/parse/t1" in url:
            return FakeResp(json_data={"code": 0, "data": {"state": "done", "markdown_url": "http://md"}})
        if url == "http://md":
            return FakeResp(text="# md 正文")
        return FakeResp(status=404)

    monkeypatch.setattr(requests, "get", get)

    c = MinerUConverter(token=None, api="agent", rate_per_min=0, poll_interval=0)
    r = c.convert(pdf, tmp_path / "x.assets")
    assert r.handled_images is False
    assert "正文" in r.body


def test_agent_needs_no_token(tmp_path, monkeypatch):
    # token=None + agent 不应在 _require_token 报错
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        json_data={"code": 0, "data": {"task_id": "t1", "file_url": "http://up"}}))
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))
    monkeypatch.setattr(requests, "get", lambda url, headers=None, **k: FakeResp(
        json_data={"code": 0, "data": {"state": "done", "markdown_url": "http://md"}})
        if "agent/parse" in url else FakeResp(text="ok"))
    c = MinerUConverter(token=None, api="agent", rate_per_min=0, poll_interval=0)
    c.convert(pdf, tmp_path / "x.assets")   # 不抛即通过


# ---- 错误码分级 ----

def test_daily_limit_raises_marked(tmp_path, monkeypatch):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}}))
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))
    monkeypatch.setattr(requests, "get", lambda url, headers=None, **k: FakeResp(
        json_data={"code": 0, "data": {"extract_result": [
            {"state": "failed", "err_code": -60018, "err_msg": "daily limit"}]}}))
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0)
    with pytest.raises(ConvertError) as ei:
        c.convert(pdf, tmp_path / "x.assets")
    assert "MINERU_DAILY_LIMIT" in str(ei.value)


def test_token_error_raises(tmp_path, monkeypatch):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        json_data={"code": "A0202", "msg": "token wrong"}))
    monkeypatch.setattr(mmod.time, "sleep", lambda s: None)
    c = MinerUConverter(token="bad", api="precision", rate_per_min=0, max_retries=2)
    with pytest.raises(ConvertError, match="Token"):
        c.convert(pdf, tmp_path / "x.assets")


# ---- 前置校验 ----

def test_precision_requires_token(tmp_path):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    c = MinerUConverter(token=None, api="precision")
    with pytest.raises(ConvertError, match="Token"):
        c.convert(pdf, tmp_path / "x.assets")


def test_precision_pages_exceed(tmp_path):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf, pages=3)
    c = MinerUConverter(token="t", api="precision", max_pages=2)
    with pytest.raises(ConvertError, match="页数超限"):
        c.convert(pdf, tmp_path / "x.assets")


# ---- 429 退避 ----

def test_post_429_then_success(tmp_path, monkeypatch):
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    zb = _zip_md("# t")
    calls = [0]

    def post(url, headers=None, json=None, **k):
        calls[0] += 1
        if calls[0] == 1:
            return FakeResp(status=429)
        return FakeResp(json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))
    monkeypatch.setattr(requests, "get", lambda url, headers=None, **k: FakeResp(
        json_data={"code": 0, "data": {"extract_result": [
            {"state": "done", "full_zip_url": "http://zip"}]}})
        if "extract-results" in url else FakeResp(content=zb))
    monkeypatch.setattr(mmod.time, "sleep", lambda s: None)

    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0, max_retries=3)
    c.convert(pdf, tmp_path / "x.assets")
    assert calls[0] == 2   # 429 后重试成功


# ---- 路由 ----

def test_resolve_api_explicit(tmp_path):
    assert MinerUConverter(api="precision")._resolve_api(tmp_path / "x") == "precision"
    assert MinerUConverter(api="agent")._resolve_api(tmp_path / "x") == "agent"


def test_resolve_api_auto(monkeypatch, tmp_path):
    monkeypatch.setattr(mmod, "mineru_api_for", lambda p: "precision")
    assert MinerUConverter(api="auto")._resolve_api(tmp_path / "x.pdf") == "precision"


# ---- 非结构化响应容错 ----

def test_post_non_json_raises(tmp_path, monkeypatch):
    # 提交返回非 JSON（网关错误页）→ ConvertError（不崩）
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        status=200, text="<html>gateway error</html>"))
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, max_retries=1)
    with pytest.raises(ConvertError, match="非 JSON"):
        c.convert(pdf, tmp_path / "x.assets")


def test_assemble_rewrites_any_image_path(tmp_path, monkeypatch):
    # md 中图片引用用非 images/ 前缀，验证按 basename 重写（不假定固定前缀）
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    assets = tmp_path / "x.assets"
    zb = _zip_md("![](some/deep/path/pic.png)\n正文", {"pic.png": b"IMG"})

    def post(url, **k):
        return FakeResp(json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))

    def get(url, headers=None, **k):
        if "extract-results" in url:
            return FakeResp(json_data={"code": 0, "data": {"extract_result": [
                {"state": "done", "full_zip_url": "http://zip"}]}})
        if url == "http://zip":
            return FakeResp(content=zb)
        return FakeResp(status=404)

    monkeypatch.setattr(requests, "get", get)
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0)
    r = c.convert(pdf, assets)
    assert "./x.assets/pic.png" in r.body
    assert "some/deep/path/pic.png" not in r.body
    assert (assets / "pic.png").exists()


def test_poll_top_level_daily_limit(tmp_path, monkeypatch):
    # 轮询响应顶层 code=-60018（非 extract_result 内 failed）→ 分级即停，非静默 continue
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}}))
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))
    monkeypatch.setattr(requests, "get", lambda url, headers=None, **k: FakeResp(
        json_data={"code": -60018, "msg": "daily limit"}))
    c = MinerUConverter(token="t", api="precision", rate_per_min=0,
                        poll_interval=0, poll_timeout=2)
    with pytest.raises(ConvertError) as ei:
        c.convert(pdf, tmp_path / "x.assets")
    assert "MINERU_DAILY_LIMIT" in str(ei.value)


def test_poll_data_null_does_not_crash(tmp_path, monkeypatch):
    # agent 流程 data:null → extract 返回 None → isinstance 校验拦下，不崩 AttributeError
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        json_data={"code": 0, "data": {"task_id": "t1", "file_url": "http://up"}}))
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))
    monkeypatch.setattr(requests, "get", lambda url, headers=None, **k: FakeResp(
        json_data={"code": 0, "data": None}))
    c = MinerUConverter(token=None, api="agent", rate_per_min=0,
                        poll_interval=0, poll_timeout=1)
    with pytest.raises(ConvertError, match="轮询超限"):
        c.convert(pdf, tmp_path / "x.assets")   # 容错重试至超时，而非 AttributeError 崩溃


def test_assemble_image_name_with_regex_chars(tmp_path, monkeypatch):
    # 文件名含正则元字符(括号/空格)，验证 re.escape 模式侧 + lambda 替换侧都不出错
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    assets = tmp_path / "x.assets"
    zb = _zip_md("![](deep/img (1).png)\n正文", {"img (1).png": b"IMG"})

    def post(url, **k):
        return FakeResp(json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))

    def get(url, headers=None, **k):
        if "extract-results" in url:
            return FakeResp(json_data={"code": 0, "data": {"extract_result": [
                {"state": "done", "full_zip_url": "http://zip"}]}})
        if url == "http://zip":
            return FakeResp(content=zb)
        return FakeResp(status=404)

    monkeypatch.setattr(requests, "get", get)
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0)
    r = c.convert(pdf, assets)
    assert "./x.assets/img (1).png" in r.body
    assert "deep/img (1).png" not in r.body
    assert (assets / "img (1).png").exists()


def test_assemble_image_name_with_backslash(tmp_path, monkeypatch):
    # 文件名含反斜杠：lambda 替换不做组引用展开（旧版 r"\1"+name 替换串会把 \1 当组引用出错）
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    assets = tmp_path / "x.assets"
    zb = _zip_md("![](p/img\\1.png)\n正文", {"img\\1.png": b"IMG"})

    def post(url, **k):
        return FakeResp(json_data={"code": 0, "data": {"batch_id": "b1", "file_urls": ["http://up"]}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "put", lambda url, data=None, **k: FakeResp(200))

    def get(url, headers=None, **k):
        if "extract-results" in url:
            return FakeResp(json_data={"code": 0, "data": {"extract_result": [
                {"state": "done", "full_zip_url": "http://zip"}]}})
        if url == "http://zip":
            return FakeResp(content=zb)
        return FakeResp(status=404)

    monkeypatch.setattr(requests, "get", get)
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, poll_interval=0)
    r = c.convert(pdf, assets)
    assert "./x.assets/img\\1.png" in r.body
    assert "p/img\\1.png" not in r.body
    assert (assets / "img\\1.png").exists()


def test_post_top_level_non_dict_raises(tmp_path, monkeypatch):
    # 提交返回顶层非 dict JSON（"ok"/[1,2] 等）→ ConvertError（不崩 AttributeError）
    pdf = tmp_path / "x.note.pdf"
    _pdf(pdf)
    monkeypatch.setattr(requests, "post", lambda url, **k: FakeResp(
        status=200, json_data=[1, 2], text="[1,2]"))
    c = MinerUConverter(token="t", api="precision", rate_per_min=0, max_retries=1)
    with pytest.raises(ConvertError, match="非对象"):
        c.convert(pdf, tmp_path / "x.assets")


def test_extract_zip_rejects_bomb_total_size(tmp_path, monkeypatch):
    # mar #10：zip 成员 file_size 累计超限 → ConvertError，不进入解压
    import io as _io
    import zipfile as _zipfile
    import xmd.backends.mineru as mod
    monkeypatch.setattr(mod, "_MAX_ZIP_TOTAL_BYTES", 100)
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("full.md", "x" * 200)   # 单成员即超测试上限
    c = MinerUConverter(token="t", api="precision")
    monkeypatch.setattr(MinerUConverter, "_get_bytes", lambda self, url: buf.getvalue())
    with pytest.raises(ConvertError):
        c._extract_zip("http://zip", tmp_path)


def test_extract_zip_within_limit(tmp_path, monkeypatch):
    # mar #10 回归：限额内 zip 正常解压取 md
    import io as _io
    import zipfile as _zipfile
    import xmd.backends.mineru as mod
    monkeypatch.setattr(mod, "_MAX_ZIP_TOTAL_BYTES", 1024 * 1024)
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("full.md", "# ok")
    c = MinerUConverter(token="t", api="precision")
    monkeypatch.setattr(MinerUConverter, "_get_bytes", lambda self, url: buf.getvalue())
    md, _imgs = c._extract_zip("http://zip", tmp_path)
    assert md == "# ok"
