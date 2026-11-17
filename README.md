# xmd

任意源 → Markdown 批量转换：散文件目录（有道云笔记导出等）与容器归档（语雀
.lakebook）统一为一种任务模型，共享并行、断点续传与质量报告。

## 支持的输入

| 类别 | 扩展名 | 转换方式 |
|---|---|---|
| 有道笔记 | .note.pdf / .clip.pdf | 后端可插拔（下表） |
| PDF 附件 | .pdf | 同上 |
| Office | .docx/.xlsx/.pptx | markitdown |
| 语雀知识库 | .lakebook | 展开为虚拟任务：Doc→md（LaTeX 还原/图片下载）、Sheet→csv 或 Obsidian Sheet Plus |
| Markdown | .md | 转换（归一） |
| 其他 | .mp3/.rar/... | 原样复制（保留原名） |

## 转换后端（PDF 族，--backend）

| 后端 | 定位 | 成本 | 图片 |
|---|---|---|---|
| markitdown（默认） | 文本提取 | 免费/本地/快 | extract_images 补 |
| pdf-inspector | 纯 Rust 轻量纯文本 | 免费/本地/快 | extract_images 补 |
| mineru | 在线 API 视觉结构恢复 | 在线额度 | Precision zip 自带 |
| auto | 智能路由（pymupdf 探测 Type3/扫描/光栅图） | 默认免费 | 按路由 |

## 安装与用法

（Python ≥3.11）
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

```bash
# 目录批量（镜像目录树，含空目录）
xmd <导出目录> -o <输出目录> [--jobs 4]

# 混合输入（文件与目录任意组合）
xmd a.lakebook b.pdf <目录> -o out/

# 智能路由 + 语雀表格转 Sheet Plus + 不下载图片
xmd <目录> -o out/ --backend auto --sheet-format sheet --no-image
export MINERU_TOKEN=<token>   # backend=mineru|auto 的复杂文件需要

# 续传与重试
xmd <目录> -o out/ --force | --retry-review

# 详细日志（DEBUG 级：含展开跳过的损坏文档、限流等）
xmd <目录> -o out/ --verbose
```

## 输出布局

```
<output>/
  ├── <镜像源目录树>/
  │     ├── 笔记A.md
  │     ├── 笔记A.assets/img_001.png     # 配图（PDF 抽取 / 语雀下载）
  │     └── 表格B.csv                     # 语雀表格（--sheet-format csv）
  ├── <lakebook名>/<TOC目录树>/文档.md     # 容器展开
  ├── convert.log / need-review.csv / summary.json
```

## 状态分类（summary.json）
ok · skipped（续传跳过）· error · need_review · copied · collision · empty · crash

## 已知限制
- markitdown 对 Type3 视觉 PDF 只出平铺文本 → 用 --backend auto 或 mineru 恢复结构
- MinerU 每日免费额度有限：额度即停 + 跨天续传（--retry-review）
- 不转音频、不解压普通压缩包：原样复制
- 跳过隐藏文件（. 开头）
- CSV 公式注入防御：`= + - @` 开头的单元格落盘加 `'` 前缀，纯文本消费方会看到该前缀
- MinerU `--mineru-rate` 为全局速率按 worker 均分（`rate//jobs`，向下取整），实际总速率可能略低于设定
- 表格解压上限 64MB/文档、zip 累计 1GB：超限记 error 不转换
- 展开期 doc/sheet 分类为正则轻量探测（后端 json 解析为权威），极端构造内容可能先按错误类别路由再由后端记 error

## 开发
```bash
.venv/bin/pytest -q
```

设计文档：[docs/specs/2026-10-16-xmd-unified-converter-design.md](docs/specs/2026-10-16-xmd-unified-converter-design.md)
格式参考：[docs/lakebook-format.md](docs/lakebook-format.md)；MinerU API：[docs/MinerU文档解析接口文档.html](docs/MinerU文档解析接口文档.html)
