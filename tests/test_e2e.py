"""端到端：CLI 混合输入（散文件 + lakebook）→ 输出树/报告/续传。"""
import json
import shutil

from conftest import make_lakebook

from xmd.cli import main

DOC = {"type": "Doc", "format": "lake",
       "body": "<h1>标题</h1><p>内容文字足够长</p>", "body_asl": ""}
TOC = [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"}]


def test_cli_mixed_inputs_end_to_end(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "附件").mkdir()
    shutil.copy(tcp_pdf, src / "附件" / "t.note.pdf")
    (src / "附件" / "a.mp3").write_bytes(b"audio")
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], TOC)

    out = tmp_path / "out"
    rc = main([str(src), str(tcp_pdf), "-o", str(out),
               "--jobs", "1", "--min-chars", "5"])
    assert rc == 0
    # 散文件目录镜像 + SKIP 保名
    assert (out / "附件" / "t.md").exists()
    assert (out / "附件" / "a.mp3").read_bytes() == b"audio"
    # 单文件输入（rel=文件名 → 输出根）
    assert (out / "tcp-handshake.md").exists()
    # 容器展开树
    assert (out / "book" / "文档.md").exists()
    # 报告三件套
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["total"] >= 4
    assert (out / "convert.log").exists() and (out / "need-review.csv").exists()


def test_cli_resume_second_run_all_skipped(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(tcp_pdf, src / "t.note.pdf")
    make_lakebook(src / "book.lakebook", [{"url": "d1", "doc": DOC}], TOC)
    out = tmp_path / "out"
    main([str(src), "-o", str(out), "--jobs", "1", "--min-chars", "5"])
    rc = main([str(src), "-o", str(out), "--jobs", "1", "--min-chars", "5"])
    assert rc == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["skipped"] == s["total"]
    assert s["ok"] == 0
