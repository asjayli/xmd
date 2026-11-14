import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def make_lakebook(path, docs, toc, *, with_uuid=True, repo_id="123"):
    """构造最小 .lakebook tar（expander/runner 测试共用）。

    docs: [{"url": "abc", "doc": {...}}]；toc: TOC 条目列表（dict）。
    """
    if not with_uuid:
        toc = [{k: v for k, v in t.items() if k not in ("uuid", "parent_uuid")} for t in toc]
    meta_inner = {"book": {"name": "测试库", "path": "https://y.com/u/test",
                           "tocYml": yaml.safe_dump(toc, allow_unicode=True)}}
    entries = [(f"{repo_id}/$meta.json", json.dumps({"meta": json.dumps(meta_inner)}))]
    for d in docs:
        entries.append((f"{repo_id}/{d['url']}.json", json.dumps({"doc": d["doc"]})))
    with tarfile.open(path, "w") as tf:
        for name, data in entries:
            b = data.encode("utf-8")
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tf.addfile(ti, io.BytesIO(b))


@pytest.fixture
def tcp_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "tcp-handshake.note.pdf"


@pytest.fixture
def blinko_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "blinko.note.pdf"


@pytest.fixture
def finance_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "finance.note.pdf"
