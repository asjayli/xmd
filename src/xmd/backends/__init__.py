"""可插拔转换后端集合。

- PDF 族（markitdown / pdf-inspector / mineru / auto）：由 runner._build_converter
  按 ctx.backend 实例化（worker 单例）。
- 语雀族（lake_doc / lake_sheet）：runner._converter_for 按任务类别惰性创建
  （Task 11/12 引入，见 runner 集成任务）。
"""
