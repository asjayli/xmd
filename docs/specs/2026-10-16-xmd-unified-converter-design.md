# xmd 统一文件转 Markdown 工程 — 设计文档

日期：2026-10-16
状态：已评审（方案 A：统一任务流水线）
来源工程：
- `/data/repository/YoudaoNoteData/youdao-note-convert`（有道云笔记导出 → Markdown，~1,100 行）
- `/data/repository/yuque/LakebookConverter`（语雀 .lakebook → Markdown/CSV，~2,000 行）

两个源仓库保持不动，xmd 为合并后的唯一后续维护处。

## 1. 背景与目标

两个源工程本质是同一件事：**批量"源 → Markdown 树"转换**，差异仅在输入侧形态：

| 维度 | youdao-note-convert | LakebookConverter |
|---|---|---|
| 输入形态 | 目录树散文件（.note.pdf/.clip.pdf/.pdf/docx/xlsx/pptx/md/其他） | 容器归档（.lakebook = tar + 私有 JSON + TOC 元数据） |
| 转换核心 | 可插拔后端：markitdown / pdf-inspector / MinerU 在线 / auto 智能路由 | HTML→MD（LaTeX 还原、代码块语言、图片提升）+ lakesheet→CSV/Sheet Plus |
| 编排能力 | 进程池并行、断点续传（mtime）、need-review.csv、summary.json、额度即停 | 串行、print 日志、无续传无汇总 |
| 图片处理 | pymupdf 抽 PDF 内嵌图 → {stem}.assets/ | 外链图片并发下载 → attachments/ |
| 测试 | 14 个测试文件，覆盖完整 | 无 |

**目标**：合并为通用工程 xmd，散文件与容器归档统一为一种任务模型，共享并行/续传/报告能力；未来新格式（notion 导出、epub、html…）只需注册 expander 或 backend。

**非目标**：
- 不改动两个源仓库
- 不做本地 OCR、不转音频、不解压普通压缩包（.rar/.zip 原样复制，维持 youdao 现状）
- 不做 GUI/Web 界面

## 2. 总体架构

```
输入（目录/文件混合，CLI 位置参数）
  │
  ▼ walker：递归扫描 + classifier 分类（隐藏文件过滤，空目录镜像）
  │
  ├─ 散文件 → FileTask（1 源文件 → 1 输出）
  └─ .lakebook → expanders/lakebook（主进程）：
        tar 安全解压 → tmp 目录 → $meta.json → TOC 建树
        → N 个虚拟 LakeTask（source=tmp 内 json，输出路径来自 TOC 树）
  │
  ▼ runner.preprocess：镜像目录创建 + 输出路径冲突确定性去重
  │
  ▼ runner._dispatch：ProcessPoolExecutor（worker 单例后端工厂）
        process_one：
          续传判定（output.mtime >= source.mtime → skipped）
          → SKIP 类复制 → 按 category 路由后端 convert()
          → PDF 族补图（extract_images）→ writer 落盘
  │
  ▼ 报告：convert.log / need-review.csv / summary.json
```

MinerU 额度即停（-60018 → 停止提交剩余、未跑标 need_review 待续传）、BrokenProcessPool 自动重启重跑等 runner 机制原样保留并惠及全部任务类型。

## 3. 包结构

```
xmd/
├── pyproject.toml            # setuptools + src 布局；Python >= 3.11
├── README.md                 # 重写：通用文件 → Markdown 批量转换
├── docs/
│   ├── specs/                # 本设计文档
│   ├── lakebook-format.md    # 迁移自 LakebookConverter README 第 7 节格式解析
│   └── MinerU 文档解析接口文档.html   # 迁移自 youdao docs/
├── src/xmd/
│   ├── __init__.py           # 版本 + 公开 API
│   ├── __main__.py           # python -m xmd
│   ├── cli.py                # 统一 CLI（argparse）
│   ├── model.py              # Category / Task / Result / ConvertResult / Converter 协议
│   ├── classifier.py         # 扩展名 → 分类
│   ├── walker.py             # 递归扫描（FileEntry + 空目录清单）
│   ├── runner.py             # 统一编排（自 youdao runner 扩展容器展开）
│   ├── writer.py             # 文件名清理 + 输出路径 + md 落盘 + 复制
│   ├── normalizer.py         # CJK 归一（自 youdao）
│   ├── router.py             # PDF 复杂度探测（自 youdao，pymupdf）
│   ├── image_extractor.py    # PDF 抽图（自 youdao）
│   ├── logging_setup.py      # pdfminer 静音（自 youdao）
│   ├── expanders/
│   │   ├── __init__.py       # 注册表 {扩展名: Expander}
│   │   └── lakebook.py       # tar 安全解压 + metadata 解析 + TOC 建树
│   └── backends/
│       ├── __init__.py       # category(+backend 参数) → Converter 工厂
│       ├── markitdown_backend.py   # markitdown 文本提取（默认）
│       ├── pdf_inspector.py        # pdf-inspector 轻量纯文本（optional extra）
│       ├── mineru.py               # MinerU 在线 API（agent/precision/限流/额度即停）
│       ├── auto.py                 # 智能路由（router 探测 → markitdown|mineru）
│       ├── lake_doc.py             # 语雀 HTML→MD（LaTeX 还原/代码块语言/图片提升/图片下载）
│       └── lake_sheet.py           # lakesheet 解压解析 → CSV / Obsidian Sheet Plus
└── tests/
    ├── conftest.py + fixtures/    # 含构造的最小 .lakebook tar 样本
    └── test_*.py              # 两源测试全量迁移 + lakebook 补建
```

## 4. 统一数据模型（model.py）

```python
class Category(StrEnum):
    NOTE_PDF = "note_pdf"     # .note.pdf / .clip.pdf
    PDF = "pdf"               # .pdf
    DOC = "doc"               # .docx/.xlsx/.pptx
    MD = "md"                 # .md
    LAKEBOOK = "lakebook"     # .lakebook（容器，仅 walker 产出，展开后消失）
    LAKE_DOC = "lake_doc"     # 展开后：语雀普通文档
    LAKE_SHEET = "lake_sheet" # 展开后：语雀表格文档
    SKIP = "skip"             # .ppt/.mp3/.rar/.zip/.7z/其他

@dataclass(frozen=True)
class Task:
    source: Path        # 物理源（散文件 或 tmp 内 doc json）
    rel_path: str       # 报告/日志/续传键（lake 任务: "<归档名>/<TOC目录…>/<标题>"）
    output_path: Path   # 输出文件（.md；lake_sheet+csv 格式为 .csv）
    assets_dir: Path    # {stem}.assets/
    category: Category
    src_mtime: float    # 续传基准（散文件=自身 mtime；lake 任务=归档 mtime）
    meta: dict          # lake: {title, download_image, sheet_format}；散文件 {}
    collision: bool

@dataclass
class ConvertResult:
    body: str                       # markdown 正文（sheet 任务为 ""）
    image_refs: list[str] = []      # 附录引用（仅后端不产图时补抽场景）
    handled_images: bool = False    # True=后端已落图；False=runner 需 PDF 补抽
    handled_output: bool = False    # True=后端已自行落盘完整输出（lake_sheet 的
                                    # csv/sheet 格式），runner 跳过 write_markdown
                                    # 与 empty/min_chars 判定，直接记 ok

class Converter(Protocol):
    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult: ...

class Expander(Protocol):
    def expand(self, archive: Path, output_root: Path, opts: dict) -> list[Task]: ...
```

`Result`（状态上报）沿用 youdao：`ok|skipped|error|need_review|copied|collision|empty|crash`，不新增状态。

## 5. 模块设计要点

### 5.1 classifier + walker
- 分类规则 = youdao 分类 + `.lakebook → LAKEBOOK`
- walker 逻辑照搬 youdao（rglob 排序、隐藏文件过滤、空目录清单），`FileEntry.category` 增加容器类

### 5.2 expanders/lakebook（自 LakebookConverter converter/metadata/utils 重构）
- `extract_tar` 安全解压（路径穿越校验、拒绝链接成员）照搬
- `$meta.json` 双层 JSON + tocYml YAML 解析照搬（metadata.py）
- TOC 建树：parent_uuid 精确算法优先，level 栈启发式回退（含跳级多帧压栈），照搬
- 展开产出 Task 列表；doc json 判型（type=="Sheet" 或 format=="lakesheet" → LAKE_SHEET，否则 LAKE_DOC）
- 输出根 = `<output>/<归档名去后缀>/`；同名去重交给 runner.preprocess 统一确定性后缀（见 5.4）
- 损坏归档：expander 抛 `ExpandError` → runner 记一条 `error` 结果（rel_path=归档路径），不中断批量
- tmp 目录 `tempfile`（pid+随机），runner `finally` 统一清理

### 5.3 backends
- **markitdown/pdf_inspector/mineru/auto**：自 youdao 原样迁移，仅命名与 import 调整；`ConvertError` 消息含 `MINERU_DAILY_LIMIT` 标记的即停协议不变
- **lake_doc**（自 doc_converter 改造）：
  - 步骤：body_asl 提取 LaTeX 字典 → 公式图片替换 `$...$`/`$$...$$` → 外链图片下载到 `assets_dir`（并发 8 线程、重试 3 次、Content-Type 定扩展名、失败写缺失提示+原 URL）→ 受限容器（td/th/h1-h6）内图片提升 → markdownify 转换（代码块语言提取回调）→ pretty_md 美化
  - 改造点：图片落点从 `attachments/{title}_NNN.ext` 改为 `assets_dir/img_NNN.ext`，src 相对引用 `./{assets名}/img_NNN.ext`；函数签名适配 Converter 协议（不自行写 md 文件，返回 body）；删除可选依赖降级路径（bs4/markdownify/requests 已必装）
  - 正文内联图保留原位，`handled_images=True`，`image_refs=[]`（不进"笔记配图"附录）
- **lake_sheet**（自 sheet_converter 迁移）：
  - zlib→gzip→明文三级解压、行列矩阵提取（行号排序、列补齐、字典单元格取 text/url、尾随全空列裁剪）；**不做日期数值猜测转换**（源码已移除：lakesheet 未保留格式标记，按数值范围猜测会把年龄/金额误转日期，造成不可逆损坏），CSV 与 Sheet Plus 均原值原样展示
  - csv 格式：后端自行写 `.csv` 文件（task.output_path），返回 `ConvertResult(body="", handled_output=True)`；sheet 格式：写 Obsidian Sheet Plus `.md`（excel-pro 插件），同样 `handled_output=True`
  - runner 见 `handled_output=True` 跳过 write_markdown 与 empty/min_chars 判定，status 直接 `ok`

### 5.4 writer（两套 sanitize 合一）
- 非法字符并集：`\ / : * ? " < > |` + `（）[] {}`（半角+全角）→ `_`；**空格保留**
- 输出路径：剥离源后缀（.note.pdf/.clip.pdf 双扩展整体剥离）补 .md；镜像目录
- `build_output_path` 支持展开任务直接指定输出路径（TOC 树）
- preprocess 冲突去重统一为确定性后缀：`__<category>` → `__<category>__N`（兼容原 youdao 语义；展开任务间同名冲突同样适用，取代 lakebook 原随机后缀）
- `write_markdown(title, body, image_refs)`："# title" + body + （仅 image_refs 非空时）"## 笔记配图" 附录

### 5.5 runner（自 youdao 扩展）
- `run(inputs, output, ...)`：inputs 支持文件与目录混合
- walk 后：LAKEBOOK 条目逐个交给 expander（主进程串行，IO 型），散文件任务与展开任务合并进 preprocess
- worker 进程内按 category 选择后端（`_build_converter` 扩展为注册表查找；LAKE_DOC/LAKE_SHEET 后端从 `task.meta` 取下载/格式选项）
- 续传判定统一用 `task.src_mtime`；`--force`/`--retry-review` 语义不变
- tmp 清理纳入 finally；报告三件套不变

### 5.6 CLI
```
xmd <input...> -o/--output <dir>
  --jobs N（默认 4）
  --force | --retry-review
  --backend markitdown|pdf-inspector|mineru|auto（默认 markitdown）
  --no-image            # PDF 不抽图 + 语雀不下载（保留外链）
  --no-sheet            # 跳过表格文档转换
  --sheet-format csv|sheet（默认 csv）
  --min-chars 50 / --max-pdf-mb 20
  --mineru-token/-api/-model/-lang/-poll-timeout/-max-pages/-rate（全套照搬）
  --verbose
```
console script `xmd`；`python -m xmd` 等价；返回码语义照搬 youdao（0 正常 / 2 运行失败 / 3 输入不存在）。

## 6. 行为统一决策（相对两源的变化点）

| # | 决策点 | 统一策略 | 理由 |
|---|---|---|---|
| D1 | 文件名清理 | 并集非法字符 → `_`，空格保留 | 括号致 md 图片链接断裂是真实 bug；替换空格理由（命令行歧义）不成立；youdao 存量输出含空格不受影响 |
| D2 | 图片资产目录 | 统一 `{stem}.assets/`，命名 `img_NNN.ext` | Typora 习惯，与 PDF 抽图一致；废止语雀 `attachments/` 布局 |
| D3 | 语雀正文内联图 | 保留正文原位 | 附录机制仅用于 markitdown 无图补抽场景 |
| D4 | 可选依赖 | bs4/markdownify/pyyaml/requests 必装；pdf-inspector 保持 extra | DIY 降级路径维护面大、收益低 |
| D5 | 同名去重 | 统一确定性后缀 `__<category>[__N]` | 可复现、幂等、git diff 友好（取代 lakebook 随机后缀） |
| D6 | PDF 后端默认 | markitdown | 零成本默认，行为兼容 |

## 7. 错误处理

- 单文件转换失败 → `error` 结果，不阻塞批量（youdao 现状）
- 原生崩溃 → `crash` + BrokenProcessPool 自动重启重跑剩余（youdao 现状）
- 损坏/恶意 lakebook → 该归档 `error`，tmp 清理，不中断
- MinerU 每日额度（-60018）→ 即停提交，剩余标 `need_review`，跨天续传（youdao 现状）
- 语雀图片下载失败 → 重试 3 次后写 `[图片缺失：原因] URL` 文本占位（Lakebook 现状）

## 8. 测试策略

- youdao 14 个测试文件全量迁入，适配新包名/模型（runner/router/mineru/cli/converter/walker/writer/normalizer/image_extractor/auto_converter/pdf_inspector/integration/smoke）
- lakebook 补建：
  - test_lakebook_expander：最小 tar fixtures（含 $meta.json + doc/sheet json）；uuid 建树、level 回退（含跳级）、损坏归档 ExpandError、链接成员拒绝
  - test_lake_doc_backend：LaTeX 提取与行内/块级替换、代码块语言（data-language/class/父链 codeblock）、td/th/h1 内图片提升、图片下载（mock http）与失败占位
  - test_lake_sheet_backend：zlib/gzip/明文解压、行列提取与补齐、字典单元格、零值/布尔字符串化、尾随空列裁剪、CSV 输出、Sheet Plus JSON 结构
- 集成测试：混合目录（散 pdf + lakebook）端到端，校验输出树/续传/summary

## 9. 实施阶段划分（供实施计划展开）

1. 骨架：pyproject/包结构/model/classifier/walker/writer/normalizer + youdao 侧平移（runner/backends）+ 测试迁移
2. lakebook 迁移：expander + lake_doc/lake_sheet 后端改造 + writer/去重统一
3. CLI 合并 + 集成测试 + 文档（README/lakebook-format/MinerU docs）
