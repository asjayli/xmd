"""语雀普通文档后端：HTML → Markdown（LaTeX 还原 + 外链图片下载）。

自 LakebookConverter doc_converter 重构：
- 适配 Converter 协议：读取 doc json → 返回 body，不自行落盘 md（writer 统一写）
- 图片落点从 attachments/{title}_NNN 改为 assets_dir/img_NNN（设计文档 D2）
- 删除可选依赖降级路径（bs4/markdownify/requests 必装，设计文档 D4）
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert
from requests import get as http_get

from xmd.model import ConvertError, ConvertResult, Task
from xmd.writer import asset_ref, pretty_md

IMAGE_DOWNLOAD_TIMEOUT = 10
IMAGE_DOWNLOAD_MAX_ATTEMPTS = 3
IMAGE_DOWNLOAD_MAX_WORKERS = 8  # 图片并发下载线程数

DEFAULT_HEADING_STYLE = "ATX"

# 图片 Content-Type → 扩展名（迁自 lakebook.constants）
CONTENT_TYPE_TO_EXTENSION: dict[str, str] = {
    "image/gif":     ".gif",
    "image/jpeg":    ".jpg",
    "image/svg+xml": ".svg",
    "image/png":     ".png",
}


# ── HTML → Markdown ───────────────────────────────────────────────────────────

# 视作"无语言"的标记：语雀导出里这些值等价于普通文本，带上反而干扰
# 渲染器（如生成 ```plain），统一归一化为空，生成不带语言的裸代码围栏。
_NO_LANGUAGE = {"", "plain", "text", "plaintext", "txt"}


def _extract_code_language(pre_tag) -> str:
    """
    从语雀导出的 <pre> 代码块中提取语言标记。

    语雀在 body HTML 中通常以下列方式之一保存代码块语言：
      - 外层 <div data-lake-card="codeblock" data-language="bash"> 包裹内层 <pre>
      - <pre> 自身 data-language="bash"
      - <pre class="language-bash">

    关键点：data-language 常位于外层 codeblock 卡片 div 上，而内层 <pre> 的
    class 是 CodeMirror 的样式名（如 cm-s-default），自身并不携带语言信息。
    因此本函数在 <pre> 自身找不到语言时，会沿父链向上查找最近的 codeblock
    卡片节点，取其 data-language。

    plain/text 等无意义标记归一化为空字符串，生成裸代码围栏。

    Args:
        pre_tag: markdownify 传入的 <pre> 标签对象

    Returns:
        代码块语言名；若缺失或为无意义值则返回空字符串
    """
    def _normalize(lang: str) -> str:
        lang = (lang or "").strip()
        return "" if lang.lower() in _NO_LANGUAGE else lang

    # 1) <pre> 自身的 data-language
    language = _normalize(str(pre_tag.get("data-language", "")))
    if language:
        return language

    # 2) <pre> 自身的 class="language-xxx"
    class_names = pre_tag.get("class", [])
    if isinstance(class_names, str):
        class_names = [class_names]

    for class_name in class_names:
        if class_name.startswith("language-") and len(class_name) > len("language-"):
            language = _normalize(class_name[len("language-"):])
            if language:
                return language

    # 3) 沿父链向上查找最近的 codeblock 卡片，取其 data-language
    #    （markdownify 基于 BeautifulSoup 解析，节点保留完整的 parent 链）
    node = getattr(pre_tag, "parent", None)
    while node is not None:
        get_attr = getattr(node, "get", None)
        if callable(get_attr) and get_attr("data-lake-card") == "codeblock":
            return _normalize(str(get_attr("data-language", "")))
        node = getattr(node, "parent", None)

    return ""

# 受限容器：GFM 表格单元格与标题行内不支持内嵌图片，markdownify 转换时
# 会静默丢弃其中的 <img>。此类容器内的图片需在转换前提升到容器之外。
_BLOCKING_CELL = ("td", "th")
_HEADING_RE = re.compile(r"^h[1-6]$")
# 表格块根：用于定位单元格内图片的提升锚点（插到整个表格块之后）
_TABLE_ROOT = ("table", "tbody", "thead", "tfoot")


def _lift_embedded_images_in(soup) -> None:
    """
    将表格单元格（td/th）与标题（h1-h6）内的 <img> 提取到容器之外，
    作为独立段落紧随其后插入（soup 原位修改，mar #6 单次解析 core）。

    GFM 表格单元格与标题行不支持内嵌图片：markdownify 转换这些容器时会
    丢弃其中的 <img>，造成图片静默丢失。本函数在交给 markdownify 之前做
    一次结构重排，把这类图片"提升"到受限容器之后的普通段落中，使其能被
    正常渲染为 ![](...)。图片位置会从"嵌在单元格/标题里"变为"紧随其后"，
    但内容不再丢失。

    Args:
        soup: 已完成图片下载与 src 本地化的 body 树
    """
    lifts = []  # [(img, anchor_node), ...]  按文档顺序
    for img in soup.find_all("img"):
        # 沿父链找最近的受限容器（单元格或标题）
        blocker = None
        node = img.parent
        while node is not None and getattr(node, "name", None) not in (None, "[document]"):
            name = node.name
            if name in _BLOCKING_CELL or _HEADING_RE.match(name):
                blocker = node
                break
            node = node.parent
        if blocker is None:
            continue

        # 单元格 → 向上找表格块根作为插入锚点，使图片落到整个表格之后：
        # 优先最外层 table（p 成为 table 的兄弟，结构最规范）；若片段无
        # table 外壳则回落到 tbody/thead/tfoot；都没有则用单元格自身。
        # 标题直接以其自身为锚点，图片插到标题之后。
        if blocker.name in _BLOCKING_CELL:
            anchor = blocker
            fallback = None
            found_table = False
            node = blocker
            for _ in range(16):  # 防御性深度上限
                parent = node.parent
                if parent is None or getattr(parent, "name", None) in (None, "[document]"):
                    break
                if parent.name == "table":
                    anchor = parent
                    found_table = True
                    break
                if fallback is None and parent.name in _TABLE_ROOT:
                    fallback = parent
                node = parent
            # 未找到 table 根（含到达文档根的退出路径）→ 回落到最近的
            # tbody/thead/tfoot，再退到单元格自身。mar #23：原 for-else 只在
            # 耗尽深度上限时应用回落，文档根 break 路径漏掉 → 锚点退化为
            # 单元格，p 落入 tr 形成非法结构
            if not found_table:
                anchor = fallback or anchor
        else:
            anchor = blocker

        lifts.append((img, anchor))

    # 同一锚点下按文档顺序依次追加：用尾指针链式 insert_after，避免后插
    # 节点插到前面（insert_after 总是紧贴锚点）导致顺序颠倒。
    tails: dict[object, object] = {}
    for img, anchor in lifts:
        p = soup.new_tag("p")
        p.append(img.extract())
        key = id(anchor)
        tail = tails.get(key)
        if tail is not None:
            tail.insert_after(p)
        else:
            anchor.insert_after(p)
        tails[key] = p


def _lift_embedded_images(html: str) -> str:
    """str 包装（兼容既有调用/测试）：parse → core → 序列化。"""
    soup = BeautifulSoup(html, "html.parser")
    _lift_embedded_images_in(soup)
    return str(soup)


def _soup_to_markdown(soup) -> str:
    """soup → Markdown（先提升受限容器图片，再交 markdownify 一次转换）。"""
    _lift_embedded_images_in(soup)
    return md_convert(
        str(soup),
        heading_style=DEFAULT_HEADING_STYLE,
        code_language_callback=_extract_code_language,
        bullets="-",
    )


def html_to_markdown(html: str) -> str:
    """
    将 HTML 字符串转换为 Markdown 格式。

    使用 markdownify 库（能正确处理表格、列表、链接等结构）。

    Args:
        html: 输入 HTML 字符串

    Returns:
        Markdown 格式字符串
    """
    return _soup_to_markdown(BeautifulSoup(html, "html.parser"))


# ── LaTeX 公式处理 ────────────────────────────────────────────────────────────

def extract_latex_from_asl(body_asl: str) -> dict[str, str]:
    """
    从语雀文档的 AST（body_asl 字段）中提取 LaTeX 公式源码。

    语雀在导出 body_asl 时，每个数学公式以如下节点表示：
      <card name="math" value="data:{URL编码的JSON}" />

    value 属性中 JSON 的结构：
      {
        "src":  "https://cdn.nlark.com/.../math-formula.png",  // 公式图片 URL
        "code": "E = mc^2"                                      // LaTeX 源码
      }

    src 与 body HTML 中 <img src="..."> 的 src 属性一一对应，
    因此可以用此字典将图片替换回 LaTeX 源码。

    Args:
        body_asl: 语雀文档的 AST 表示（HTML-like 格式字符串）

    Returns:
        img_src → latex_code 的映射字典。
        若 body_asl 为空，返回空字典。
    """
    if not body_asl:
        return {}

    latex_dict: dict[str, str] = {}
    asl_soup = BeautifulSoup(body_asl, "html.parser")

    for card in asl_soup.find_all("card", {"name": "math"}):
        val = card.get("value", "")
        # value 属性格式为 "data:{URL编码的JSON字符串}"
        if not val.startswith("data:"):
            continue
        try:
            # 去掉 "data:" 前缀，URL 解码后再解析 JSON
            json_str = urllib.parse.unquote(val[5:])
            card_data = json.loads(json_str)
            src  = card_data.get("src", "")
            code = card_data.get("code", "")
            if src and code:
                latex_dict[src] = code
        except Exception:
            # 个别格式异常的节点跳过，不影响整体转换
            pass

    return latex_dict


def replace_latex_images(html: str, latex_dict: dict[str, str]) -> str:
    """
    将 body HTML 中表示 LaTeX 公式的 <img> 标签替换为 Markdown 数学公式语法。

    替换规则：
    - 行内公式（$...$）：单行 LaTeX 代码 且 父元素为行内元素（span、a 等）
    - 块级公式（$$...$$）：LaTeX 代码含换行符，或父元素为块级元素（p、div、center）

    Args:
        html:        原始 body HTML 字符串
        latex_dict:  由 extract_latex_from_asl() 生成的 img_src → latex_code 字典

    Returns:
        替换后的 HTML 字符串。若字典为空，原样返回。
    """
    if not latex_dict:
        return html

    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        img_src = img.get("src", "")
        if img_src not in latex_dict:
            continue

        raw_latex = latex_dict[img_src]
        parent_tag = img.parent.name if img.parent else ""

        # 判断块级 vs 行内：
        #   含换行符的 LaTeX 通常是多行公式（align、matrix 等） → 块级
        #   父元素是块级 HTML 元素 → 块级
        is_block = ("\n" in raw_latex.strip()) or (parent_tag in ("p", "div", "center"))

        if is_block:
            replacement = soup.new_string(f"\n$$\n{raw_latex.strip()}\n$$\n")
        else:
            replacement = soup.new_string(f"${raw_latex.strip()}$")

        img.replace_with(replacement)

    return str(soup)


# ── 图片下载 ──────────────────────────────────────────────────────────────────

def _ip_is_internal(ip) -> bool:
    """环回/私网/链路本地地址一律视为内网（mar #9）。"""
    return ip.is_loopback or ip.is_private or ip.is_link_local


def is_forbidden_src(src: str) -> bool:
    """图片地址 SSRF 校验（mar #9）：img src 完全来自不可信归档。

    仅放行 http(s)；主机为 IP 字面量或域名解析出的任一 IP 命中
    环回/私网/链路本地段即拒绝。域名解析失败（离线/不存在）不在此
    拦截——交由下载流程按普通网络失败处理，保持公网路径不回归。
    """
    try:
        parsed = urllib.parse.urlparse(src)
    except ValueError:
        return True
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return True
    host = parsed.hostname
    try:
        ips = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False   # 无法解析 → 不拦截，下载自然失败
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    return any(_ip_is_internal(ip) for ip in ips)


def _download_image_with_retry(src: str):
    """
    下载单张图片，失败时做有限次数重试。

    仅对网络请求阶段重试；若最终仍失败，由调用方决定如何处理。
    """
    last_error: Exception | None = None

    for attempt in range(1, IMAGE_DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            resp = http_get(src, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if attempt < IMAGE_DOWNLOAD_MAX_ATTEMPTS:
                time.sleep(attempt)

    if last_error is None:
        # 理论不可达：循环至少执行一次，末次 attempt 失败必然已赋值
        # last_error。不使用 assert，避免 python -O 剥离断言后掩盖异常。
        raise RuntimeError("未知下载失败：未捕获到具体异常")
    raise last_error


def _download_image_to_file(no: int, src: str, assets_dir: Path) -> tuple:
    """下载单图并立即写盘（mar #19：字节不进聚合容器，单图峰值）。

    返回 ("ok", fname) | ("write_fail", src, OSError)——下载失败异常由
    调用方统一捕获。编号 no 预知，扩展名取响应 Content-Type。
    """
    resp = _download_image_with_retry(src)
    ext = CONTENT_TYPE_TO_EXTENSION.get(resp.headers.get("Content-Type", ""), ".jpg")
    fname = f"img_{no:03d}{ext}"
    try:
        (assets_dir / fname).write_bytes(resp.content)
    except OSError as e:
        return ("write_fail", src, e)
    return ("ok", fname)


def download_images_to_soup(soup, assets_dir: Path) -> None:
    """下载 soup 中所有外链图片到 assets_dir（img_NNN.ext），src 原位改相对引用。

    失败（重试 IMAGE_DOWNLOAD_MAX_ATTEMPTS 次）→ 原位写 [图片缺失：原因] URL 文本。
    即下即写：future 内直接落盘（mar #19，百图文档不再全部字节驻留内存）；
    HTML 改写在全部 future 完成后串行进行（编号/文件名稳定）。
    soup 原位修改（mar #6：body 只解析一次，本函数不再独立 parse）。
    """
    img_tags = soup.find_all("img")
    tasks = [(no, image, image.get("src", ""))
             for no, image in enumerate(img_tags, start=1) if image.get("src")]
    if not tasks:
        return
    assets_dir.mkdir(parents=True, exist_ok=True)

    # results[no] -> ("ok", fname) | ("write_fail", src, err) | ("fail", src, err)
    # 不含图片字节（mar #19）
    results: dict[int, tuple] = {}
    # SSRF 预检（mar #9）：内网/非法协议地址不进入下载线程，按失败路径提示
    downloadable = []
    for no, image, src in tasks:
        if is_forbidden_src(src):
            results[no] = ("fail", src, ValueError("内网或非法地址，禁止下载"))
        else:
            downloadable.append((no, image, src))
    with ThreadPoolExecutor(max_workers=IMAGE_DOWNLOAD_MAX_WORKERS) as executor:
        future_to_no = {
            executor.submit(_download_image_to_file, no, src, assets_dir): (no, src)
            for no, _image, src in downloadable
        }
        for future in as_completed(future_to_no):
            no, src = future_to_no[future]
            try:
                results[no] = future.result()
            except Exception as e:
                results[no] = ("fail", src, e)

    for no, image, src in tasks:
        outcome = results.get(no)
        if outcome and outcome[0] == "ok":
            image["src"] = asset_ref(assets_dir, outcome[1])
            # 清理语雀默认的无意义图片 alt/title（恒为 "image"，无语义价值）
            if (image.get("alt") or "").strip() == "image":
                image["alt"] = ""
            if (image.get("title") or "").strip() == "image":
                del image["title"]
        elif outcome and outcome[0] == "write_fail":
            image.replace_with(soup.new_string(f"\n[图片缺失：写入失败] {src}\n"))
        else:
            reason = f"下载失败：{outcome[2]}" if outcome else "下载失败，请手动处理"
            image.replace_with(soup.new_string(f"\n[图片缺失：{reason}] {src}\n"))


def download_images_to_assets(html: str, assets_dir: Path) -> str:
    """str 包装（兼容既有调用/测试）：parse → core → 序列化。"""
    soup = BeautifulSoup(html, "html.parser")
    download_images_to_soup(soup, assets_dir)
    return str(soup)


class LakeDocBackend:
    """语雀普通文档 → Markdown 后端。"""

    def convert(self, source: Path, assets_dir: Path, task: Task) -> ConvertResult:
        from xmd.backends import read_doc_json   # 延迟 import 避免包循环
        # 损坏 json → ConvertError（error 粒度），与 lake_sheet 共用（mar #13）
        doc = read_doc_json(source)
        # 用 `or ""` 兜底：键存在但值为 None 时，dict.get 的默认值不会生效
        body_asl = doc.get("body_asl") or ""
        latex_dict = extract_latex_from_asl(body_asl)
        # body 是完整的渲染 HTML；若 body 为空（极少数情况），回退到 body_asl
        html = doc.get("body") or body_asl
        if latex_dict:
            # 迁移函数签名只收 str（保真约束）：其内部对 body 解析 1 次
            html = replace_latex_images(html, latex_dict)
        # mar #6：body 此后只主动解析 1 次，下载与图片提升均在该树上原位完成
        soup = BeautifulSoup(html, "html.parser")
        if task.entry.meta.get("download_image", True):
            download_images_to_soup(soup, assets_dir)
        markdown_content = pretty_md(_soup_to_markdown(soup))
        return ConvertResult(body=markdown_content, handled_images=True)
