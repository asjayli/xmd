"""并发行为测试（mar #7/#8）：jobs=2 真实进程池冒烟 + BrokenProcessPool 重启。"""
import threading
import time
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import xmd.runner as rm
from xmd.classifier import Category
from xmd.model import FileEntry, Result
from xmd.runner import Ctx, run


def test_jobs2_real_process_pool(tmp_path, tcp_pdf):
    # mar #7：CLI 默认 --jobs 4 的真并发路径零覆盖——此处 jobs=2 真实进程池
    # （非 mock）跑 md/pdf 混合批量（无网络后端；docx 需 markitdown[docx]
    # extra 未安装，故用真实 note.pdf 替代），锁定 Task/FileEntry 可 pickle
    # 与多 worker 正确性；计数须与 jobs=1 完全一致
    import shutil
    src = tmp_path / "src"
    sub = src / "子目录"
    sub.mkdir(parents=True)
    (src / "a.md").write_text("alpha " * 20, encoding="utf-8")
    (src / "b.md").write_text("beta " * 20, encoding="utf-8")
    shutil.copy(tcp_pdf, sub / "c.note.pdf")
    shutil.copy(tcp_pdf, sub / "d.note.pdf")

    out1 = tmp_path / "out-j1"
    out2 = tmp_path / "out-j2"
    s1 = run(src, out1, jobs=1, min_chars=5, no_image=True)
    s2 = run(src, out2, jobs=2, min_chars=5, no_image=True)
    assert s1["total"] == s2["total"] == 4
    assert s1["ok"] == s2["ok"] == 4
    for out in (out1, out2):
        assert (out / "a.md").exists()
        assert (out / "b.md").exists()
        assert (out / "子目录" / "c.md").exists()
        assert (out / "子目录" / "d.md").exists()


def test_dispatch_broken_pool_restart(tmp_path, monkeypatch):
    # mar #8：首个池某任务 BrokenProcessPool → 该批记 1 条 crash、剩余任务
    # 重启新池完成、结果无重复无丢失（done_keys 去重）
    made = {"n": 0}

    class FlakyPool:
        """第 1 个池：boom 立即就绪且携带 BPP 异常，其余延迟就绪（保证 BPP
        先被消费 → 必然走重启分支）；第 2 个池起全部立即 ok。"""

        def __init__(self, *a, **k):
            made["n"] += 1

        def submit(self, fn, t):
            f = Future()
            rel = str(t.entry.rel_path)
            if made["n"] == 1 and "boom" in rel:
                f.set_exception(BrokenProcessPool("worker died"))
            elif made["n"] == 1:
                def resolve():
                    time.sleep(0.05)
                    f.set_result(Result(rel, "ok", 10, 0, None))
                threading.Thread(target=resolve, daemon=True).start()
            else:
                f.set_result(Result(rel, "ok", 10, 0, None))
            return f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rm, "ProcessPoolExecutor", FlakyPool)
    root = tmp_path / "src"
    root.mkdir()
    names = ["a.note.pdf", "boom.note.pdf", "c.note.pdf"]
    files = []
    for n in names:
        p = root / n
        p.write_bytes(b"")
        files.append(FileEntry(Path(n), p, Category.NOTE_PDF))
    tasks = rm.preprocess(files, tmp_path / "out")
    out = tmp_path / "out"
    out.mkdir()
    results = rm._dispatch(tasks, Ctx(force=True, min_chars=1), jobs=1, output_root=out)
    assert len(results) == len(tasks) == 3        # 无丢失
    rels = [r.rel_path for r in results]
    assert len(set(rels)) == 3                    # 无重复
    crashes = [r for r in results if r.status == "crash"]
    assert len(crashes) == 1                      # 恰 1 条 crash
    assert made["n"] >= 2                         # 池已重启
    assert all(r.status == "ok" for r in results if r.status != "crash")
