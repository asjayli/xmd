import json
import shutil

import pytest

from xmd.cli import main


def test_cli_ok(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    out = tmp_path / "out"
    rc = main([str(src), "-o", str(out),
               "--jobs", "1", "--min-chars", "10"])
    assert rc == 0
    assert (out / "summary.json").exists()


def test_cli_missing_input(tmp_path):
    rc = main([str(tmp_path / "nope"), "-o", str(tmp_path / "o")])
    assert rc == 3


def test_cli_bad_args():
    # 缺 inputs/-o → argparse SystemExit(2)
    with pytest.raises(SystemExit) as ei:
        main([])
    assert ei.value.code == 2


def test_cli_backend_markitdown(tmp_path, tcp_pdf):
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    out = tmp_path / "o"
    rc = main([str(src), "-o", str(out),
               "--backend", "markitdown", "--jobs", "1", "--min-chars", "10"])
    assert rc == 0
    assert (out / "summary.json").exists()


def test_cli_mineru_opts_parsed(tmp_path, tcp_pdf, monkeypatch):
    # 验证 --backend mineru 时 backend_opts 正确透传给 run()
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured.update(kwargs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    main([str(src), "-o", str(tmp_path / "o"),
          "--backend", "mineru", "--mineru-api", "precision",
          "--mineru-model", "vlm", "--mineru-rate", "10",
          "--mineru-max-pages", "150"])
    assert captured["backend"] == "mineru"
    assert captured["backend_opts"]["api"] == "precision"
    assert captured["backend_opts"]["model_version"] == "vlm"
    assert captured["backend_opts"]["rate_per_min"] == 10
    assert captured["backend_opts"]["max_pages"] == 150


def test_cli_max_pdf_mb_passed(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured.update(kwargs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    main([str(src), "-o", str(tmp_path / "o"), "--max-pdf-mb", "5"])
    assert captured["max_pdf_mb"] == 5


def test_cli_retry_review_filters_only(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured.update(kwargs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()
    # 造 need-review.csv（utf-8-sig）
    (out / "need-review.csv").write_text(
        "﻿rel_path,chars,status\nn/t.note.pdf,5,need_review\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    main([str(src), "-o", str(out), "--retry-review"])
    assert captured["force"] is True              # retry-review 隐含 force
    assert captured["only"] == {"n/t.note.pdf"}   # 仅重转 need-review 子集


def test_cli_retry_review_no_csv_returns_zero(tmp_path, monkeypatch, capsys):
    # 缺 need-review.csv → return 0，不调 run（不烧额度、不全量 force）
    called = {"n": 0}

    def fake_run(*a, **k):
        called["n"] += 1
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()   # 无 need-review.csv
    src = tmp_path / "src"
    src.mkdir()
    rc = main([str(src), "-o", str(out), "--retry-review"])
    assert rc == 0
    assert called["n"] == 0
    assert "无 need-review.csv" in capsys.readouterr().err


def test_cli_retry_review_empty_csv_returns_zero(tmp_path, monkeypatch, capsys):
    # need-review.csv 仅表头（无记录）→ return 0，不调 run
    called = {"n": 0}

    def fake_run(*a, **k):
        called["n"] += 1
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()
    (out / "need-review.csv").write_text("﻿rel_path,chars,status\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    rc = main([str(src), "-o", str(out), "--retry-review"])
    assert rc == 0
    assert called["n"] == 0
    assert "无记录" in capsys.readouterr().err


def test_cli_retry_review_warns_missing_source(tmp_path, monkeypatch, capsys, tcp_pdf):
    # only 中源文件已不存在的条目 → stderr 提示
    captured = {}

    def fake_run(*a, **k):
        captured.update(k)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()
    (out / "need-review.csv").write_text(
        "﻿rel_path,chars,status\nmissing/t.note.pdf,5,need_review\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")   # 源是 n/t.note.pdf，CSV 记 missing/t.note.pdf
    main([str(src), "-o", str(out), "--retry-review"])
    assert "missing/t.note.pdf" in capsys.readouterr().err


def test_cli_retry_review_malformed_csv_filters_none(tmp_path, monkeypatch, tcp_pdf):
    # 异构 CSV（rel_path 非首列 + 短行 restval=None）→ None 被滤，不 TypeError
    captured = {}

    def fake_run(*a, **k):
        captured.update(k)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()
    (out / "need-review.csv").write_text(
        "﻿chars,rel_path,status\n5,n/t.note.pdf,need_review\n5\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    rc = main([str(src), "-o", str(out), "--retry-review"])
    assert rc == 0
    assert captured["only"] == {"n/t.note.pdf"}   # 短行 rel_path=None 被滤，不崩


def test_cli_no_image_no_sheet_passed(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured.update(kwargs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    main([str(src), "-o", str(tmp_path / "o"),
          "--no-image", "--no-sheet", "--sheet-format", "sheet"])
    assert captured["no_image"] is True
    assert captured["convert_sheets"] is False
    assert captured["sheet_format"] == "sheet"


def test_cli_mixed_file_and_dir_inputs(tmp_path, tcp_pdf, monkeypatch):
    captured = {}

    def fake_run(inputs, output, **kwargs):
        captured["inputs"] = list(inputs)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    main([str(src), str(tcp_pdf), "-o", str(tmp_path / "o")])
    assert captured["inputs"] == [src, tcp_pdf]


def test_cli_retry_review_no_false_warning_for_virtual_paths(tmp_path, monkeypatch, capsys):
    # mar #24：lakebook 虚拟路径 retry 不误报「源文件已不存在」；真实缺失仍提示
    from conftest import make_lakebook
    captured = {}

    def fake_run(*a, **k):
        captured.update(k)
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    out = tmp_path / "o"
    out.mkdir()
    (out / "need-review.csv").write_text(
        "﻿rel_path,chars,status\nbook/文档,5,need_review\nghost/x.md,5,need_review\n",
        encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook", [],
                  [{"title": "文档", "type": "DOC", "url": "d1", "level": 0}])
    main([str(src), "-o", str(out), "--retry-review"])
    err = capsys.readouterr().err
    assert "源文件已不存在" in err and "ghost/x.md" in err   # 真实缺失仍预警
    assert "book/文档" not in err   # 归档虚拟路径不误报


def test_cli_verbose_enables_debug_logging(tmp_path, monkeypatch):
    # mar #26：--verbose 接线 DEBUG 日志（原为悬空参数）
    import logging
    calls = {}
    real_basicConfig = logging.basicConfig

    def spy_basicConfig(*a, **k):
        calls.update(k)
        return real_basicConfig(*a, **k)

    monkeypatch.setattr(logging, "basicConfig", spy_basicConfig)

    def fake_run(*a, **k):
        return {"total": 0}

    monkeypatch.setattr("xmd.cli.run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    main([str(src), "-o", str(tmp_path / "o"), "--verbose"])
    assert calls.get("level") == logging.DEBUG
