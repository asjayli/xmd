from pathlib import Path

from xmd.classifier import Category
from xmd.model import ConvertResult, Task
from xmd.runner import (
    Ctx,
    Result,
    _is_daily_limit,
    _worker_init,
    preprocess,
    process_one,
)
from xmd.walker import FileEntry


def _entry(root: Path, name: str, cat: Category) -> FileEntry:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return FileEntry(Path(name), p, cat)


def _ctx(force=False, min_chars=50):
    return Ctx(force=force, min_chars=min_chars)


# ---- preprocess ----

def test_no_conflict(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    files = [_entry(root, "a.note.pdf", Category.NOTE_PDF)]
    tasks = preprocess(files, tmp_path / "out")
    assert len(tasks) == 1
    assert tasks[0].output_md == tmp_path / "out" / "a.md"
    assert tasks[0].collision is False


def test_same_name_note_vs_pdf_disambiguated(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    files = [
        _entry(root, "IO设计模式之Reactor和Proactor.note.pdf", Category.NOTE_PDF),
        _entry(root, "IO设计模式之Reactor和Proactor.pdf", Category.PDF),
    ]
    tasks = preprocess(files, tmp_path / "out")
    outs = {t.entry.abs_path.name: t for t in tasks}
    note_md = outs["IO设计模式之Reactor和Proactor.note.pdf"].output_md
    pdf_md = outs["IO设计模式之Reactor和Proactor.pdf"].output_md
    assert note_md != pdf_md
    assert pdf_md.stem != "IO设计模式之Reactor和Proactor"
    assert outs["IO设计模式之Reactor和Proactor.pdf"].collision is True
    assert (outs["IO设计模式之Reactor和Proactor.note.pdf"].assets_dir
            != outs["IO设计模式之Reactor和Proactor.pdf"].assets_dir)


def test_same_source_same_path_not_collision(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    e = _entry(root, "a.note.pdf", Category.NOTE_PDF)
    tasks = preprocess([e, e], tmp_path / "out")
    assert all(not t.collision for t in tasks)


# ---- process_one ----

def test_process_one_note_pdf_ok(tmp_path, tcp_pdf):
    _worker_init(_ctx())
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "out" / "tcp.md",
                tmp_path / "out" / "tcp.assets", False)
    r = process_one(task)
    assert r.status == "ok"
    assert (tmp_path / "out" / "tcp.md").exists()
    assert r.images >= 1   # 绑定 pymupdf 对 fixture 的抽图行为（升级预期复核点）


def test_process_one_empty_body_marks_empty(tmp_path, monkeypatch):
    _worker_init(_ctx())
    pdf = tmp_path / "x.note.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    import xmd.runner as rm
    monkeypatch.setattr(
        rm, "_get_converter",
        lambda: type("C", (), {"convert": lambda self, p, a, t=None: ConvertResult(body="\xa0\n")})())
    entry = FileEntry(Path("x.note.pdf"), pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "x.md", tmp_path / "x.assets", False)
    r = process_one(task)
    assert r.status == "empty"


def test_process_one_skip_is_copied(tmp_path):
    _worker_init(_ctx())
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"audio")
    entry = FileEntry(Path("a.mp3"), mp3, Category.SKIP)
    task = Task(entry, tmp_path / "out" / "a.mp3",
                tmp_path / "out" / "a.assets", False)
    r = process_one(task)
    assert r.status == "copied"
    assert (tmp_path / "out" / "a.mp3").read_bytes() == b"audio"


def test_resume_skips_existing(tmp_path, tcp_pdf):
    _worker_init(_ctx())
    out_md = tmp_path / "out" / "tcp.md"
    out_md.parent.mkdir(parents=True)
    out_md.write_text("# done", encoding="utf-8")
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, out_md, tmp_path / "out" / "tcp.assets", False)
    r = process_one(task)
    assert r.status == "skipped"


def test_force_overwrites_existing(tmp_path, tcp_pdf):
    _worker_init(_ctx(force=True))
    out_md = tmp_path / "out" / "tcp.md"
    out_md.parent.mkdir(parents=True)
    out_md.write_text("old", encoding="utf-8")
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, out_md, tmp_path / "out" / "tcp.assets", False)
    r = process_one(task)
    assert r.status == "ok"
    assert "old" not in out_md.read_text(encoding="utf-8")


# ---- run 编排（Phase 7）----

import json  # noqa: E402

from xmd.runner import run  # noqa: E402


def test_run_end_to_end(tmp_path, tcp_pdf):
    import shutil
    src = tmp_path / "src"
    src.mkdir()
    (src / "笔记本").mkdir()
    shutil.copy(tcp_pdf, src / "笔记本" / "tcp.note.pdf")
    (src / "空笔记本").mkdir()
    out = tmp_path / "out"
    summary = run(src, out, jobs=1, min_chars=10)
    assert summary["total"] == 1
    assert summary["ok"] == 1
    assert (out / "空笔记本").is_dir()
    assert (out / "笔记本" / "tcp.md").exists()
    assert (out / "convert.log").exists()
    assert (out / "need-review.csv").exists()
    assert (out / "summary.json").exists()
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["total"] == 1


def test_resume_second_run_all_skipped(tmp_path, tcp_pdf):
    import shutil
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    shutil.copy(tcp_pdf, src / "n" / "t.note.pdf")
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=10)
    s2 = run(src, out, jobs=1, min_chars=10)
    assert s2["skipped"] == s2["total"]
    assert s2["ok"] == 0


def test_error_isolated(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "n").mkdir()
    bad = src / "n" / "bad.note.pdf"
    bad.write_bytes(b"")  # 0 字节 → markitdown 抛 PDFSyntaxError → ConvertError → error
    out = tmp_path / "out"
    summary = run(src, out, jobs=1, min_chars=10)
    assert summary["error"] == 1
    assert summary["total"] == 1


def test_need_review_csv_utf8sig(tmp_path, tcp_pdf):
    import shutil
    src = tmp_path / "src"
    src.mkdir()
    (src / "中文").mkdir()
    shutil.copy(tcp_pdf, src / "中文" / "t.note.pdf")
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=10**9)
    raw = (out / "need-review.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")


# ---- 后端可插拔（Phase 10）----

def test_handled_images_skips_extract(tmp_path, monkeypatch, tcp_pdf):
    _worker_init(_ctx())
    import xmd.runner as rm
    monkeypatch.setattr(rm, "_get_converter", lambda: type("C", (), {
        "convert": lambda self, p, a, t=None: ConvertResult(
            body="正文内容足够长" * 10,
            image_refs=["./tcp.assets/a.jpg"],
            handled_images=True,
        )
    })())
    called = {"n": 0}

    def fake_extract(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(rm, "extract_images", fake_extract)
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "tcp.md", tmp_path / "tcp.assets", False)
    r = process_one(task)
    assert called["n"] == 0          # handled_images=True → 不再 extract_images
    assert r.images == 1             # 沿用后端产出的图
    assert r.status == "ok"


def test_unhandled_calls_extract(tmp_path, monkeypatch, tcp_pdf):
    _worker_init(_ctx())
    import xmd.runner as rm
    monkeypatch.setattr(rm, "_get_converter", lambda: type("C", (), {
        "convert": lambda self, p, a, t=None: ConvertResult(body="正文内容足够长" * 10, handled_images=False)
    })())
    called = {"n": 0}

    def fake_extract(pdf, assets, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(rm, "extract_images", fake_extract)
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "tcp.md", tmp_path / "tcp.assets", False)
    process_one(task)
    assert called["n"] == 1          # handled_images=False → 调 extract_images


def test_is_daily_limit_detects_mark():
    assert _is_daily_limit(Result("x", "error", 0, 0, "MINERU_DAILY_LIMIT: 上限"))
    assert not _is_daily_limit(Result("x", "error", 0, 0, "其他错误"))
    assert not _is_daily_limit(Result("x", "ok", 0, 0, None))


# ---- Ctx pickle / max_pdf_mb 透传 ----

def test_ctx_is_picklable():
    # worker 跨进程需 pickleable（frozen dataclass + dict opts）
    import pickle
    ctx = Ctx(force=True, min_chars=10, max_pdf_mb=5, backend="mineru",
              backend_opts={"api": "precision", "rate_per_min": 10})
    assert pickle.loads(pickle.dumps(ctx)) == ctx


def test_max_pdf_mb_zero_skips_extract(tmp_path, monkeypatch, tcp_pdf):
    # max_pdf_mb=0 → _size_mb <= 0 恒假 → 即使 handled_images=False 也不抽图
    _worker_init(Ctx(force=False, min_chars=50, max_pdf_mb=0))
    import xmd.runner as rm
    monkeypatch.setattr(rm, "_get_converter", lambda: type("C", (), {
        "convert": lambda self, p, a, t=None: ConvertResult(body="正文内容足够长" * 10, handled_images=False)
    })())
    called = {"n": 0}

    def fake_extract(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(rm, "extract_images", fake_extract)
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "tcp.md", tmp_path / "tcp.assets", False)
    process_one(task)
    assert called["n"] == 0


# ---- daily_stop：已完成 future 不被覆盖成 need_review ----

def test_dispatch_daily_stop_keeps_completed(tmp_path, monkeypatch):
    # 用 FakePool（submit 即 set_result，模拟全部跑完）验证：
    # daily_limit 触发 daily_stop 后，已完成的 future 取真实结果，不被覆盖成 need_review
    from concurrent.futures import Future
    import xmd.runner as rm

    seq = [
        Result("ok1.note.pdf", "ok", 100, 1, None),
        Result("daily.note.pdf", "error", 0, 0, "MINERU_DAILY_LIMIT: 上限"),
        Result("ok2.note.pdf", "ok", 200, 2, None),
    ]

    class FakePool:
        def __init__(self, *a, **k):
            self._it = iter(seq)

        def submit(self, fn, *a):
            f = Future()
            f.set_result(next(self._it))   # seq 长度须等于任务数，超界抛 StopIteration
            return f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rm, "ProcessPoolExecutor", FakePool)
    root = tmp_path / "src"
    root.mkdir()
    files = [_entry(root, n, Category.NOTE_PDF)
             for n in ["ok1.note.pdf", "daily.note.pdf", "ok2.note.pdf"]]
    tasks = preprocess(files, tmp_path / "out")
    out = tmp_path / "out"
    out.mkdir()
    results = rm._dispatch(tasks, Ctx(force=True, min_chars=10), jobs=1, output_root=out)
    by_rel = {r.rel_path: r for r in results}
    assert len(results) == 3                          # 无丢失
    assert by_rel["daily.note.pdf"].status == "error"
    assert "MINERU_DAILY_LIMIT" in by_rel["daily.note.pdf"].error
    assert by_rel["ok1.note.pdf"].status == "ok"     # 已完成 → 真实结果保留
    assert by_rel["ok2.note.pdf"].status == "ok"
    assert all(r.status != "need_review" for r in results)   # 不覆盖


def test_dispatch_daily_stop_marks_cancelled(tmp_path, monkeypatch):
    # daily_stop 核心语义另一半：额度触发后被 cancel 的任务 → need_review 待续传。
    # 线程驱动 FakePool：ok1 先完成 → daily 完成触发 daily_stop → cancel ok2（pending）。
    from concurrent.futures import Future
    import threading
    import time as _time
    import xmd.runner as rm

    seq = [
        Result("ok1.note.pdf", "ok", 100, 1, None),
        Result("daily.note.pdf", "error", 0, 0, "MINERU_DAILY_LIMIT: 上限"),
    ]   # ok2 的 future 保持 pending，由主循环 cancel → cancelled → need_review

    class FakePool:
        def __init__(self, *a, **k):
            self.futs = []
            self._driven = False

        def submit(self, fn, *a):
            f = Future()
            self.futs.append(f)
            if not self._driven:
                self._driven = True
                threading.Thread(target=self._drive, daemon=True).start()
            return f

        def _drive(self):
            _time.sleep(0.05)
            self.futs[0].set_result(seq[0])   # ok1 先完成（主循环正常分支取真实结果）
            _time.sleep(0.05)
            self.futs[1].set_result(seq[1])   # daily 完成 → daily_stop → cancel futs[2]
            # 模拟 Executor worker 取到已取消任务：CANCELLED → CANCELLED_AND_NOTIFIED
            # 并通知 waiter（真实场景由 worker 调 set_running_or_notify_cancel 完成；
            # 裸 Future 缺这一环时 as_completed 的 waiter 不会被 cancel 唤醒而挂死）
            f3 = self.futs[2]
            while not f3.cancelled():
                _time.sleep(0.01)
            f3.set_running_or_notify_cancel()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rm, "ProcessPoolExecutor", FakePool)
    root = tmp_path / "src"
    root.mkdir()
    files = [_entry(root, n, Category.NOTE_PDF)
             for n in ["ok1.note.pdf", "daily.note.pdf", "ok2.note.pdf"]]
    tasks = preprocess(files, tmp_path / "out")
    out = tmp_path / "out"
    out.mkdir()
    results = rm._dispatch(tasks, Ctx(force=True, min_chars=10), jobs=1, output_root=out)
    by_rel = {r.rel_path: r for r in results}
    assert len(results) == 3                              # 无丢失
    assert by_rel["ok1.note.pdf"].status == "ok"          # 已完成 → 真实结果
    assert by_rel["daily.note.pdf"].status == "error"     # daily_limit
    assert by_rel["ok2.note.pdf"].status == "need_review" # 被 cancel → 待续传


def test_need_review_csv_formula_injection_neutralized(tmp_path):
    # mar #2 PoC 回归：need-review.csv 的 rel_path 同样做公式注入防御
    from xmd.runner import _write_need_review
    from xmd.model import Result
    _write_need_review(tmp_path, [
        Result("=HYPERLINK(\"http://evil\")", "need_review", 10, 0, None),
        Result("+x", "empty", 0, 0, None),
        Result("正常/路径.md", "need_review", 100, 0, None),
    ])
    text = (tmp_path / "need-review.csv").read_text(encoding="utf-8-sig")
    assert "'=HYPERLINK" in text and "'+x" in text
    assert "正常/路径.md" in text   # 普通路径逐字节不变


def test_run_overlapping_inputs_dedup(tmp_path):
    # mar #12：目录与其子文件重叠输入 → 同一源文件只生成一个任务（total 不重复）
    src = tmp_path / "src"
    sub = src / "sub"
    sub.mkdir(parents=True)
    (sub / "a.md").write_text("足够长的正文内容以超过阈值", encoding="utf-8")
    s = run([src, sub / "a.md"], tmp_path / "out", jobs=1, min_chars=5)
    assert s["total"] == 1   # 修复前：walk(dir)+scan(file) 各产一条 → total=2


def test_run_only_preserves_untouched_need_review_rows(tmp_path):
    # mar #5：only 子集重转不清空历史清单——未触及行逐字节保留，触及行按新结果更新
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("短", encoding="utf-8")
    (src / "b.md").write_text("短", encoding="utf-8")
    out = tmp_path / "out"
    s1 = run(src, out, jobs=1, min_chars=100)
    assert s1["need_review"] == 2
    csv1 = (out / "need-review.csv").read_text(encoding="utf-8-sig")
    b_line = next(ln for ln in csv1.splitlines() if ln.startswith("b.md,"))
    # 二轮：b 源改名消失，仅重转 a（阈值放宽 → ok）；b 行应原样保留，a 行移出
    (src / "b.md").rename(src / "bb.md")
    run(src, out, jobs=1, min_chars=1, only={"a.md"}, force=True)
    lines = (out / "need-review.csv").read_text(encoding="utf-8-sig").splitlines()
    assert b_line in lines                          # 未触及历史行逐字节保留
    assert not any(ln.startswith("a.md,") for ln in lines)   # 已修复 → 移出清单


def test_run_only_updates_touched_rows_in_place(tmp_path):
    # mar #5：触及行以新结果替换（仍需复核 → 行更新，不产生重复行）
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("短", encoding="utf-8")
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=100)
    (src / "a.md").write_text("依旧很短", encoding="utf-8")
    run(src, out, jobs=1, min_chars=100, only={"a.md"}, force=True)
    import csv as _csv
    with (out / "need-review.csv").open(encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    a_rows = [row for row in rows if row["rel_path"] == "a.md"]
    assert len(a_rows) == 1                       # 行唯一（替换而非追加）
    assert a_rows[0]["status"] == "need_review"   # 仍需复核 → 行更新保留


def test_run_mineru_rate_split_across_jobs(tmp_path, monkeypatch):
    # mar #15：rate_per_min 是全局速率语义，多 worker 时按 jobs 均分下发
    captured = {}

    def fake_dispatch(tasks, ctx, jobs, output_root):
        captured["ctx"] = ctx
        return []

    monkeypatch.setattr("xmd.runner._dispatch", fake_dispatch)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("x" * 80, encoding="utf-8")
    run(src, tmp_path / "o1", jobs=4, backend="mineru",
        backend_opts={"token": "t", "rate_per_min": 20})
    assert captured["ctx"].backend_opts["rate_per_min"] == 5
    assert captured["ctx"].backend_opts["token"] == "t"   # 其余 opts 原样下发
    run(src, tmp_path / "o2", jobs=1, backend="mineru",
        backend_opts={"token": "t", "rate_per_min": 20})
    assert captured["ctx"].backend_opts["rate_per_min"] == 20   # 单 worker 不变
    run(src, tmp_path / "o3", jobs=4, backend="auto",
        backend_opts={"token": "t", "rate_per_min": 8})
    assert captured["ctx"].backend_opts["rate_per_min"] == 2    # auto 同样均分
    run(src, tmp_path / "o4", jobs=4)                           # 非 mineru 后端不动
    assert captured["ctx"].backend_opts is None


# ---- mar #22 测试缺口补齐 ----

def test_preprocess_triple_conflict_chain(tmp_path):
    # __N 冲突链：a__pdf.pdf 先占 a__pdf.md 后，a.pdf 的同目标冲突需走到 __2
    root = tmp_path / "src"
    root.mkdir()
    files = [
        _entry(root, "a__pdf.pdf", Category.PDF),       # 先占 a__pdf.md
        _entry(root, "a.note.pdf", Category.NOTE_PDF),  # 占 a.md
        _entry(root, "a.pdf", Category.PDF),            # a.md✗ → a__pdf.md✗ → a__pdf__2.md
    ]
    tasks = preprocess(files, tmp_path / "out")
    outs = [t.output_md.name for t in tasks]
    assert outs == ["a__pdf.md", "a.md", "a__pdf__2.md"]   # 三路径互异
    assert tasks[2].collision is True


def test_run_only_full_chain(tmp_path):
    # run(only) 全链路：首轮极小阈值产 need-review → 二轮仅子集重转，
    # convert.log/summary/输出内容均只反映子集
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("短", encoding="utf-8")
    (src / "b.md").write_text("短", encoding="utf-8")
    out = tmp_path / "out"
    s1 = run(src, out, jobs=1, min_chars=10**9)
    assert s1["need_review"] == 2
    (src / "a.md").write_text("补长后的正文内容 a", encoding="utf-8")
    s2 = run(src, out, jobs=1, min_chars=5, only={"a.md"}, force=True)
    assert s2["total"] == 1 and s2["ok"] == 1     # 仅子集重转
    log2 = (out / "convert.log").read_text(encoding="utf-8")
    assert "a.md | ok |" in log2 and "b.md" not in log2
    assert "补长后的正文内容 a" in (out / "a.md").read_text(encoding="utf-8")


def test_no_image_execution_layer(tmp_path, tcp_pdf, monkeypatch):
    # --no-image 执行层：PDF 不补抽图（extract_images 计数 0）
    import xmd.runner as rm
    _worker_init(Ctx(force=True, min_chars=5, no_image=True))
    called = {"n": 0}

    def fake_extract(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(rm, "extract_images", fake_extract)
    entry = FileEntry(Path(tcp_pdf.name), tcp_pdf, Category.NOTE_PDF)
    task = Task(entry, tmp_path / "tcp.md", tmp_path / "tcp.assets", False)
    r = process_one(task)
    assert called["n"] == 0
    assert r.status == "ok" and r.images == 0


def test_no_image_lakebook_download_linkage(tmp_path, monkeypatch):
    # --no-image 联动：lakebook 任务 download_image=False → 不下载，正文保留外链
    import shutil
    from conftest import make_lakebook
    monkeypatch.setattr("xmd.backends.lake_doc.http_get",
                        lambda url, timeout: (_ for _ in ()).throw(AssertionError("不应下载")))
    src = tmp_path / "src"
    src.mkdir()
    make_lakebook(src / "book.lakebook",
                  [{"url": "d1", "doc": {"type": "Doc", "format": "lake",
                                         "body": '<p><img src="https://pub/1.png"/></p>',
                                         "body_asl": ""}}],
                  [{"title": "文档", "type": "DOC", "url": "d1", "level": 0, "uuid": "d1"}])
    out = tmp_path / "out"
    run(src, out, jobs=1, min_chars=1, no_image=True)
    text = (out / "book" / "文档.md").read_text(encoding="utf-8")
    assert "https://pub/1.png" in text and "[图片缺失" not in text


def test_dispatch_crash_status_enters_need_review(tmp_path, monkeypatch):
    # crash 状态（mar #22）：worker 抛非 ConvertError 异常由 _dispatch 兜底 →
    # status=crash 且进 need-review.csv
    from concurrent.futures import Future
    import xmd.runner as rm

    class CrashPool:
        def __init__(self, *a, **k):
            pass

        def submit(self, fn, t):
            f = Future()
            f.set_exception(RuntimeError("worker 内存崩坏"))
            return f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rm, "ProcessPoolExecutor", CrashPool)
    root = tmp_path / "src"
    root.mkdir()
    p = root / "x.note.pdf"
    p.write_bytes(b"")
    tasks = rm.preprocess([FileEntry(Path("x.note.pdf"), p, Category.NOTE_PDF)],
                          tmp_path / "out")
    out = tmp_path / "out"
    out.mkdir()
    results = rm._dispatch(tasks, Ctx(force=True, min_chars=1), jobs=1, output_root=out)
    assert len(results) == 1
    r = results[0]
    assert r.status == "crash" and "RuntimeError" in (r.error or "")
    rm._write_need_review(out, results)
    assert "crash" in (out / "need-review.csv").read_text(encoding="utf-8-sig")


# ---- mar #33 金样加固：库行为断言注记 + 纯工程不变量 ----

def test_pdf_fixtures_status_invariants(tmp_path, tcp_pdf, blinko_pdf, finance_pdf):
    # 工程自身不变量（不绑定 markitdown/pymupdf 外部行为，预期升级点无需复核）：
    # 任一 fixture 经 process_one 后状态属合法集合且输出文件落盘
    _worker_init(Ctx(force=True, min_chars=1))
    for pdf in (tcp_pdf, blinko_pdf, finance_pdf):
        entry = FileEntry(Path(pdf.name), pdf, Category.NOTE_PDF)
        out_md = tmp_path / "out" / f"{pdf.stem}.md"
        task = Task(entry, out_md, tmp_path / "out" / f"{pdf.stem}.assets", False)
        r = process_one(task)
        assert r.status in ("ok", "need_review", "empty")
        assert out_md.exists()
