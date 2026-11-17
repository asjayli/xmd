"""可插拔转换后端集合。

- PDF 族（markitdown / pdf-inspector / mineru / auto）：由 runner._build_converter
  按 ctx.backend 实例化（worker 单例）。
- 语雀族（lake_doc / lake_sheet）：runner._converter_for 按任务类别惰性创建
  （Task 11/12 引入，见 runner 集成任务）。
"""


def read_doc_json(source) -> dict:
    """读取语雀导出的 doc json，返回内层 doc 字典。

    损坏 json 统一抛 ConvertError（error 粒度，runner 记 error 而非 crash），
    lake_doc 与 lake_sheet 两个姊妹后端共用（mar #13 对齐）。
    """
    import json
    from xmd.model import ConvertError
    try:
        return json.loads(source.read_text(encoding="utf-8")).get("doc", {})
    except json.JSONDecodeError as e:
        raise ConvertError(f"文档 json 解析失败: {source.name}: {e}") from e
