"""lake_sheet 后端测试：解压/行列提取/字符串化/尾列裁剪/CSV/Sheet Plus。"""
import json
import zlib
from pathlib import Path

from xmd.backends.lake_sheet import LakeSheetBackend, parse_lakesheet, rows_to_sheet_plus_format
from xmd.model import Category, FileEntry, Task


def _body(data: dict) -> str:
    """构造 lakesheet body：JSON 壳 + zlib 压缩（latin-1 还原为字符串）。"""
    return json.dumps({"format": "lakesheet",
                       "sheet": zlib.compress(json.dumps(data).encode()).decode("latin-1")})


def _write_sheet(tmp_path, data, name="s.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"doc": {"type": "Sheet", "format": "lakesheet",
                                     "body": _body(data)}}), encoding="utf-8")
    return p


def _task(src, output, fmt="csv", title="表"):
    """构造 lake_sheet 任务（后端读 task.output_md 与 task.entry.meta）。"""
    entry = FileEntry(Path("b/表"), src, Category.LAKE_SHEET,
                      meta={"title": title, "sheet_format": fmt})
    return Task(entry, output, output.parent / (output.stem + ".assets"), False)


DATA = {"data": {
    "0": {"0": {"v": "姓名"}, "1": {"v": "年龄"}},
    "1": {"0": {"v": "张三"}, "1": {"v": 28}},
    "2": {"0": {"v": "李四"}, "1": {"v": 0.0}},
}}


def test_parse_zlib_roundtrip():
    rows = parse_lakesheet(_body(DATA))
    assert rows == [["姓名", "年龄"], ["张三", "28"], ["李四", "0"]]   # 0.0 → "0"


def test_parse_plain_json_fallback():
    body = json.dumps({"format": "lakesheet", "sheet": json.dumps(DATA)})
    assert parse_lakesheet(body) == [["姓名", "年龄"], ["张三", "28"], ["李四", "0"]]


def test_parse_bool_and_none_and_dict_cell():
    data = {"data": {
        "0": {"0": {"v": "b"}, "1": {"v": "n"}, "2": {"v": "link"}},
        "1": {"0": {"v": True}, "1": {"v": None},
              "2": {"v": {"text": "点击", "url": "https://x"}}},
    }}
    rows = parse_lakesheet(_body(data))
    assert rows[1] == ["TRUE", "", "点击"]


def test_parse_trailing_empty_cols_trimmed():
    data = {"data": {"0": {"0": {"v": "a"}, "500": {"v": ""}}}}
    rows = parse_lakesheet(_body(data))
    assert rows == [["a"]]


def test_parse_bad_format_returns_none():
    assert parse_lakesheet(json.dumps({"format": "other"})) is None


def test_backend_csv(tmp_path):
    src = _write_sheet(tmp_path, DATA)
    out = tmp_path / "表.csv"
    task = _task(src, out, "csv")
    r = LakeSheetBackend().convert(src, tmp_path / "a.assets", task)
    assert r.handled_output is True and r.body == ""
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "姓名,年龄"
    assert lines[1] == "张三,28"


def test_backend_sheet_plus(tmp_path):
    src = _write_sheet(tmp_path, DATA)
    out = tmp_path / "表.md"
    task = _task(src, out, "sheet", title="数据表")
    LakeSheetBackend().convert(src, tmp_path / "a.assets", task)
    text = out.read_text(encoding="utf-8")
    assert "excel-pro-plugin: parsed" in text
    assert "```sheet" in text and "```multiSheet" in text
    j = json.loads(text.split("```sheet")[1].split("```")[0])
    assert j["name"] == "数据表"
    assert j["sheets"][j["sheetOrder"][0]]["cellData"]["0"]["0"]["v"] == "姓名"


def test_backend_empty_body_raises(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"doc": {"type": "Sheet", "body": ""}}), encoding="utf-8")
    import pytest
    from xmd.model import ConvertError
    with pytest.raises(ConvertError):
        LakeSheetBackend().convert(p, tmp_path / "a.assets",
                                   _task(p, tmp_path / "t.csv"))


def test_rows_to_sheet_plus_random_ids():
    md = rows_to_sheet_plus_format([["a", "b"], ["1", "2"]], "T", "")
    assert md.startswith("---")


def test_backend_csv_formula_injection_neutralized(tmp_path):
    # mar #2 PoC 回归：= + - @ 开头单元格落盘为 '=… 前缀；普通单元格逐字节不变
    import json, zlib
    from pathlib import Path
    data = {"data": {"0": {"0": {"v": "名称"}, "1": {"v": "值"}},
                     "1": {"0": {"v": "=WEBSERVICE(\"http://evil/\")"},
                           "1": {"v": "1+1 结果"}},
                     "2": {"0": {"v": "+100"}, "1": {"v": "-200"}},
                     "3": {"0": {"v": "@cmd"}, "1": {"v": "普通"}}}}
    body = json.dumps({"format": "lakesheet",
                       "sheet": zlib.compress(json.dumps(data).encode()).decode("latin-1")})
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"doc": {"type": "Sheet", "format": "lakesheet", "body": body}}),
                 encoding="utf-8")
    entry = FileEntry(Path("书/表"), p, Category.LAKE_SHEET, meta={"sheet_format": "csv"})
    task = Task(entry, tmp_path / "表.csv", tmp_path / "表.assets", False)
    LakeSheetBackend().convert(p, tmp_path / "表.assets", task)
    import csv as _csv
    with (tmp_path / "表.csv").open(encoding="utf-8-sig") as f:
        rows = list(_csv.reader(f))
    assert rows[1][0] == "'=WEBSERVICE(\"http://evil/\")"   # CSV 读回：前缀 ' 生效
    assert rows[2] == ["'+100", "'-200"]
    assert rows[3] == ["'@cmd", "普通"]   # 普通单元格无前缀、逐字节不变
    assert rows[1][1] == "1+1 结果"   # 非开头的 + 不受影响
