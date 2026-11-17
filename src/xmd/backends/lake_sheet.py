"""语雀表格文档后端：lakesheet → CSV / Obsidian Sheet Plus。

自 LakebookConverter sheet_converter 迁移：解析函数逐字保留；新增
LakeSheetBackend 适配 Converter 协议——后端自行落盘完整输出
（ConvertResult.handled_output=True，runner 跳过 write_markdown 与
empty/min_chars 判定，见设计文档 5.3）。
"""
from __future__ import annotations

import csv
import json
import random
import string
import zlib
from pathlib import Path
from typing import List, Optional

from xmd.model import ConvertError, ConvertResult, Task
from xmd.writer import csv_safe

# 单文档解压大小上限（mar #10：解压炸弹防御；测试可 monkeypatch 调小）
_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024


def _bounded_decompress(data: bytes, wbits: int, max_length: int) -> bytes:
    """限长解压：展开结果超过 max_length 字节即抛 ConvertError（mar #10）。

    用 decompressobj 的 max_length 截断输出——超限时 unconsumed_tail 非空且
    输出已达上限，不会把炸弹数据全量解进内存。
    """
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, max_length + 1)
    if len(out) > max_length or d.unconsumed_tail:
        raise ConvertError(f"表格解压数据超限（>{max_length // (1024 * 1024)}MB，疑似解压炸弹）")
    return out

# —— 以下解析函数逐字迁自 sheet_converter（parse_lakesheet 内 print 改为
#    静默返回 None，失败信息由 ConvertError 在 Backend 层统一报告）——
# parse_lakesheet / _decompress_sheet / _extract_rows_from_sheet_json /
# rows_to_sheet_plus_format / _make_cell_style


# ── lakesheet 解析 ────────────────────────────────────────────────────────────

def parse_lakesheet(body: str) -> Optional[List[List[str]]]:
    """
    解析 lakesheet 格式的表格数据，返回二维字符串列表。

    解析步骤：
    1. 解析 body JSON，验证 format 字段为 "lakesheet"
    2. 获取 sheet 字段（压缩数据字符串）
    3. 依次尝试 zlib → gzip → 直接 JSON 解析
    4. 从解压后的 JSON 中提取 data 字段，构建行列矩阵
    5. 过滤全空行，返回二维字符串列表

    Args:
        body: 文档 JSON 中的 "body" 字段值（字符串形式的 JSON）

    Returns:
        二维字符串列表（行 × 列），解析失败返回 None
    """
    try:
        sheet_data = json.loads(body)

        # 验证格式标识
        if sheet_data.get("format") != "lakesheet":
            return None

        sheet_str = sheet_data.get("sheet", "")
        if not sheet_str:
            return None

        # 压缩数据以字符串形式存储，需先用 latin-1 编码还原字节序列
        # （latin-1 是唯一与 0x00-0xFF 一一对应的编码，不会丢失字节）
        sheet_bytes = sheet_str.encode("latin-1") if isinstance(sheet_str, str) else sheet_str

        # 按顺序尝试三种解压方式
        sheet_json = _decompress_sheet(sheet_bytes, sheet_str)
        if sheet_json is None:
            return None

        # 取第一个工作表（语雀导出通常只有一个）
        if isinstance(sheet_json, list):
            if not sheet_json:
                return None
            sheet_json = sheet_json[0]

        if not isinstance(sheet_json, dict):
            return None

        return _extract_rows_from_sheet_json(sheet_json)

    except ConvertError:
        raise   # 解压超限（mar #10）等明确错误上抛，error 粒度报告
    except Exception:
        return None


def _decompress_sheet(sheet_bytes: bytes, sheet_str: str) -> Optional[dict]:
    """
    尝试三种方式解压 sheet 压缩数据，返回解析后的 JSON 对象。

    语雀不同版本可能使用不同压缩方式，因此依次尝试：
      zlib → gzip → 原始 JSON 字符串

    Args:
        sheet_bytes: 用 latin-1 编码得到的字节序列
        sheet_str:   原始字符串（作为最后的 JSON 解析兜底）

    Returns:
        解析后的 Python 对象，失败返回 None
    """
    # 方案一：zlib 解压（lakesheet 最常见的压缩方式）；限长防解压炸弹（mar #10）
    try:
        decompressed = _bounded_decompress(sheet_bytes, zlib.MAX_WBITS,
                                           _MAX_DECOMPRESSED_BYTES)
        return json.loads(decompressed.decode("utf-8"))
    except ConvertError:
        raise   # 解压超限是明确错误，不静默降级到后续方案
    except Exception:
        pass

    # 方案二：gzip 解压（同样限长）
    try:
        decompressed = _bounded_decompress(sheet_bytes, 16 + zlib.MAX_WBITS,
                                           _MAX_DECOMPRESSED_BYTES)
        return json.loads(decompressed.decode("utf-8"))
    except ConvertError:
        raise
    except Exception:
        pass

    # 方案三：数据本身就是 JSON 字符串（未压缩）
    try:
        return json.loads(sheet_str)
    except Exception:
        pass

    return None


def _extract_rows_from_sheet_json(sheet_json: dict) -> Optional[List[List[str]]]:
    """
    从解压后的单个工作表 JSON 中提取行列数据。

    数据格式（data 字段）：
      "data": {
        "行号(str)": {
          "列号(str)": {"v": 值, ...},
          ...
        },
        ...
      }

    Args:
        sheet_json: 解压并解析后的单个工作表 JSON 对象

    Returns:
        二维字符串列表，过滤掉全空行；无数据返回 None
    """
    data = sheet_json.get("data", {})
    if not data:
        return None

    # 收集所有数字行号并排序，保证行顺序正确
    row_indices = sorted(int(k) for k in data if k.isdigit())
    if not row_indices:
        return None

    # 找出最大列号，以便统一所有行的列数
    max_col = 0
    for row_idx in row_indices:
        row_data = data.get(str(row_idx), {})
        col_indices = [int(k) for k in row_data if k.isdigit()]
        if col_indices:
            max_col = max(max_col, max(col_indices))

    # 构建二维列表
    all_rows: List[List[str]] = []
    for row_idx in row_indices:
        row_data = data.get(str(row_idx), {})
        row: List[str] = []
        for col_idx in range(max_col + 1):
            cell = row_data.get(str(col_idx), {})
            value = cell.get("v", "")
            # 部分单元格的值是字典（如超链接），优先取 text，其次 url
            if isinstance(value, dict):
                value = value.get("text", value.get("url", ""))
            # 字符串化规范（CSV 与 Sheet Plus 两条路径共用，保证呈现一致）：
            #   - None → 空串。注意不能用 `if value` 判空，否则 0 / 0.0 / False
            #     会被误判为空而丢失（此即旧版零值丢失 bug）。
            #   - bool → TRUE/FALSE。Python 的 "True"/"False" 不被 Excel/CSV
            #     识别为布尔，统一用大写形式。
            #   - 整数浮点（如 0.0 / 12.0）→ 整数形式，避免无意义的 ".0"。
            if value is None:
                cell_str = ""
            elif isinstance(value, bool):
                cell_str = "TRUE" if value else "FALSE"
            elif isinstance(value, float) and value.is_integer():
                cell_str = str(int(value))
            else:
                cell_str = str(value)
            row.append(cell_str)

        # 仅保留非全空行
        if any(cell.strip() for cell in row):
            all_rows.append(row)

    # 剪去所有行均为空的尾随列：语雀数据偶有孤立的远端单元格（如 r0c500），
    # 若按全局最大列号补齐，会让每行末尾拖一长串空逗号。此处仅剪尾部全空列，
    # 中间的空列保留（其右侧可能仍有数据）。此规则同时作用于 CSV 与 Sheet Plus。
    if all_rows:
        width = max(len(r) for r in all_rows)
        last_used_col = -1
        for col in range(width):
            if any(col < len(r) and r[col].strip() for r in all_rows):
                last_used_col = col
        if last_used_col + 1 < width:
            all_rows = [r[: last_used_col + 1] for r in all_rows]

    return all_rows if all_rows else None


# ── Obsidian Sheet Plus 格式生成 ──────────────────────────────────────────────

def rows_to_sheet_plus_format(
    rows: List[List[str]],
    title: str,
    file_path: str = "",
) -> str:
    """
    将二维字符串列表转换为 Obsidian Sheet Plus 插件格式。

    输出结果是一个 Markdown 文件，包含：
    1. YAML frontmatter（声明此文件由 excel-pro-plugin 解析）
    2. ```sheet``` 代码块，内含符合 Univer 格式的完整 JSON 数据
    3. ```multiSheet``` 代码块（多工作表导航，目前固定为单工作表）

    Univer JSON 结构（简化）：
    {
      "id":         "随机6位ID",
      "sheetOrder": ["随机16位工作表key"],
      "name":       "文件名",
      "styles":     {样式字典},
      "sheets": {
        "工作表key": {
          "cellData": {
            "行号": {"列号": {"s": "样式ID", "v": "值", "t": 类型}}
          },
          ...其他工作表属性
        }
      },
      "resources": [...]    // Univer 插件资源声明
    }

    Args:
        rows:      二维字符串列表，第一行视为表头（使用不同样式）
        title:     文档标题（用于 Univer JSON 的 name 字段）
        file_path: 输出文件路径（可选，用于从路径中提取更简洁的名称）

    Returns:
        完整的 Markdown 字符串，包含 frontmatter 和 sheet/multiSheet 代码块
    """
    if not rows:
        return ""

    # 补齐所有行到相同列数（确保矩形结构）
    max_cols = max(len(row) for row in rows)
    if max_cols == 0:
        return ""
    normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]

    # ── 生成随机 ID ──────────────────────────────────────────────────────────
    # sheet_id:  工作簿 ID（6位字母数字）
    # sheet_key: 工作表 Key（16位字母数字，用作 sheetOrder 和 sheets 的键）
    chars = string.ascii_letters + string.digits
    sheet_id  = "".join(random.choices(chars, k=6))
    sheet_key = "".join(random.choices(chars, k=16))

    # ── 构建样式 ─────────────────────────────────────────────────────────────
    # 表头样式：Arial 9pt 加粗，带四边细框线
    # 数据样式：Calibri 11pt 普通，无框线
    header_style_id = "".join(random.choices(chars, k=6))
    data_style_id   = "".join(random.choices(chars, k=6))

    styles = {
        header_style_id: _make_cell_style(is_header=True),
        data_style_id:   _make_cell_style(is_header=False),
    }

    # ── 构建 cellData ────────────────────────────────────────────────────────
    cell_data: dict = {}
    for row_idx, row in enumerate(normalized_rows):
        row_cells: dict = {}
        for col_idx, raw_value in enumerate(row):
            cell_str = str(raw_value).strip() if raw_value else ""

            # 第一行使用表头样式，其余使用数据样式。
            # 单元格值原样写入，不做日期还原：语雀 lakesheet 的日期格式标记
            # 未被 parse 链路保留，没有可靠依据判断某个数字原本是否为日期，
            # 按数值范围猜测（旧逻辑）会把年龄、金额等普通数字误转成日期，
            # 造成不可逆的数据损坏。故与 CSV 路径一致，原值原样展示。
            style_id = header_style_id if row_idx == 0 else data_style_id

            row_cells[str(col_idx)] = {
                "s": style_id,  # style ID
                "v": cell_str,  # value（原样展示值）
                "t": 1,         # type：1 = 文本
            }

        if row_cells:
            cell_data[str(row_idx)] = row_cells

    # ── 构建完整工作表 JSON ───────────────────────────────────────────────────
    sheet_data = {
        "id":              sheet_key,
        "name":            "Sheet1",
        "tabColor":        "",
        "hidden":          0,
        # rowCount/columnCount 至少为实际行列数，填充至常见的默认值
        "rowCount":        max(len(normalized_rows), 1000),
        "columnCount":     max(max_cols, 20),
        "zoomRatio":       1,
        "freeze":          {"xSplit": 0, "ySplit": 0, "startRow": -1, "startColumn": -1},
        "scrollTop":       0,
        "scrollLeft":      0,
        "defaultColumnWidth":  88,
        "defaultRowHeight":    24,
        "mergeData":       [],
        "cellData":        cell_data,
        "rowData":         {},
        "columnData":      {},
        "showGridlines":   1,
        "rowHeader":       {"width": 46, "hidden": 0},
        "columnHeader":    {"height": 20, "hidden": 0},
        "rightToLeft":     0,
    }

    # ── 从文件路径中提取简洁名称 ──────────────────────────────────────────────
    name = file_path if file_path else title
    # 取路径最后一段（去目录前缀）
    if "/" in name or "\\" in name:
        name = name.replace("\\", "/").split("/")[-1]
    # 去掉 .md 后缀
    if name.endswith(".md"):
        name = name[:-3]

    # ── 组装顶层 JSON ────────────────────────────────────────────────────────
    sheet_json = {
        "id":         sheet_id,
        "sheetOrder": [sheet_key],
        "name":       name,
        "appVersion": "0.15.0",
        "locale":     "enUS",
        "styles":     styles,
        "sheets":     {sheet_key: sheet_data},
        # resources 列表是 Univer 各插件的资源声明，按规范固定填写
        "resources": [
            {"name": "SHEET_UNIVER_THREAD_COMMENT_PLUGIN",      "data": "{}"},
            {"name": "SHEET_RANGE_PROTECTION_PLUGIN",           "data": ""},
            {"name": "SHEET_AuthzIoMockService_PLUGIN",         "data": "{}"},
            {"name": "SHEET_WORKSHEET_PROTECTION_PLUGIN",       "data": "{}"},
            {"name": "SHEET_WORKSHEET_PROTECTION_POINT_PLUGIN", "data": "{}"},
            {"name": "SHEET_DRAWING_PLUGIN",                    "data": "{}"},
            {"name": "SHEET_HYPER_LINK_PLUGIN",                 "data": f'{{\"{sheet_key}\":[]}}'},
            {"name": "SHEET_CONDITIONAL_FORMATTING_PLUGIN",     "data": ""},
            {"name": "SHEET_OUTGOING_LINK_PLUGIN",              "data": f'{{\"{sheet_key}\":[]}}'},
            {"name": "SHEET_NOTE_PLUGIN",                       "data": "{}"},
            {"name": "SHEET_DEFINED_NAME_PLUGIN",               "data": "{}"},
            {"name": "SHEET_RANGE_THEME_MODEL_PLUGIN",          "data": "{}"},
            {"name": "SHEET_DATA_VALIDATION_PLUGIN",            "data": f'{{\"{sheet_key}\":[]}}'},
            {"name": "SHEET_FILTER_PLUGIN",                     "data": "{}"},
            {"name": "SHEET_TABLE_PLUGIN",                      "data": "{}"},
        ],
    }

    # ── 拼接最终 Markdown 内容 ───────────────────────────────────────────────
    json_str   = json.dumps(sheet_json, ensure_ascii=False, separators=(",", ":"))
    frontmatter     = "---\n\nexcel-pro-plugin: parsed\n\n---"
    sheet_block     = f"```sheet\n{json_str}\n```"
    multisheet_block = (
        '```multiSheet\n'
        '{"tabs":[{"key":"sheet","type":"sheet","label":"Sheet"}],'
        '"defaultActiveKey":"sheet"}\n'
        '```'
    )

    return f"{frontmatter}\n{sheet_block}\n\n{multisheet_block}\n"


def _make_cell_style(is_header: bool) -> dict:
    """
    创建单元格样式字典，符合 Univer 电子表格的样式规范。

    表头样式（is_header=True）：
      - 字体：Arial 9pt 加粗
      - 四边细灰框线（rgb(204,204,204)，线型 1）

    数据样式（is_header=False）：
      - 字体：Calibri 11pt 普通
      - 无框线

    字段说明（Univer 内部格式）：
      ff  font-family     it  italic（0/1）     bl  bold（0/1）
      fs  font-size       ul  underline         st  strikethrough
      cl  color           ht  horizontal-align  vt  vertical-align
      tb  text-wrap       pd  padding           bd  border
      tr  text-rotation   td  text-direction    n   number-format

    Args:
        is_header: True 表示表头样式，False 表示普通数据样式

    Returns:
        符合 Univer 格式的样式字典
    """
    style: dict = {
        "ff": "Arial" if is_header else "Calibri",
        "fs": 9 if is_header else 11,
        "it": 0,                                          # 非斜体
        "bl": 1 if is_header else 0,                     # 表头加粗
        "ul": {"s": 0, "cl": {"rgb": "rgb(0,0,0)"}},     # 无下划线
        "st": {"s": 0, "cl": {"rgb": "rgb(0,0,0)"}},     # 无删除线
        "ol": {"s": 0, "cl": {"rgb": "rgb(0,0,0)"}},     # 无轮廓线
        "tr": {"a": 0, "v": 0},                           # 无文字旋转
        "td": 0,                                          # 从左到右方向
        "cl": {"rgb": "rgb(0,0,0)"},                      # 黑色文字
        "ht": 0,                                          # 左对齐
        "vt": 2,                                          # 垂直居中
        "tb": 1,                                          # 自动换行
        "pd": {"t": 0, "b": 2, "l": 2, "r": 2},          # 内边距
    }

    # 表头行加灰色细框线，增强视觉分隔
    if is_header:
        border = {"cl": {"rgb": "rgb(204,204,204)"}, "s": 1}
        style["bd"] = {"l": border, "r": border, "t": border, "b": border}

    return style


class LakeSheetBackend:
    """语雀表格 → CSV / Sheet Plus 后端（自行落盘）。"""

    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult:
        from xmd.backends import read_doc_json   # 延迟 import 避免包循环
        body = read_doc_json(source).get("body", "")
        if not body:
            raise ConvertError("表格文档 body 为空")
        rows = parse_lakesheet(body)
        if not rows:
            raise ConvertError("表格数据解析失败或为空")
        out = task.output_md
        out.parent.mkdir(parents=True, exist_ok=True)
        if task.entry.meta.get("sheet_format", "csv") == "sheet":
            # file_path 不传：Univer name 用文档标题（meta.title），而非输出文件
            # 基名——两者在 runner 场景通常一致，但 title 是权威来源（见测试规格）
            content = rows_to_sheet_plus_format(rows, task.entry.meta.get("title", ""))
            out.write_text(content, encoding="utf-8")
        else:
            # 默认格式为 CSV：原值原样输出（无样式、无日期猜测转换）；
            # = + - @ 开头单元格前缀 ' 防公式注入（mar #2），普通值逐字节不变
            with out.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerows([[csv_safe(c) for c in row] for row in rows])
        return ConvertResult(body="", handled_images=True, handled_output=True)
