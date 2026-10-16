"""MinerU 在线 API 后端：视觉版面理解，恢复标题/代码块/表格/公式/图片。

走 https://mineru.net 在线 API（非本地子进程，依赖仅 requests）。两档：
- Agent（/api/v1/agent，免费免登录，IP 限频）：仅 md、≤20 页/≤10MB（HTML 文档 TABLE 0/11）。
- Precision（/api/v4，消耗账户额度，需 Token）：zip 含 md+images、≤200MB/≤200 页（TABLE 1）、vlm/pipeline。

api=auto 时按 router.mineru_api_for 智能选档（复杂或超 Agent 限制 → precision）。
本地文件走预签名 PUT 上传 → 轮询 → 下载。限速 + 429 退避 + 错误码分级（-60018 即停）。

错误码对照 docs/MinerU 文档解析接口文档.html TABLE 10（Precision）/ TABLE 17（Agent）。
"""
from __future__ import annotations

import hashlib
import io
import os
import random
import re
import shutil
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from xmd.model import ConvertError, ConvertResult, Task
from xmd.normalizer import normalize
from xmd.router import mineru_api_for

_BASE = "https://mineru.net"

# 错误码分级（HTML 文档 TABLE 10 / TABLE 17）
_DAILY_LIMIT = {-60018, -60019}          # 每日上限 → 即停
_RETRYABLE = {-60009, -10001, -60007, -60010}    # 队列满/服务异常/模型暂不可用/解析失败(请稍后再试) → 退避重试
_TOKEN_ERR = {"A0202", "A0211"}          # Token 错误/过期
DAILY_LIMIT_MARK = "MINERU_DAILY_LIMIT"  # runner 识别此标记即停


class MinerUConverter:
    def __init__(self, token: str | None = None, api: str = "auto", model_version: str = "vlm",
                 language: str = "ch", is_ocr: bool = True, poll_interval: int = 3,
                 poll_timeout: int = 600, max_pages: int = 200, rate_per_min: int = 20,
                 max_retries: int = 3) -> None:
        self.token = token or os.environ.get("MINERU_TOKEN")
        self.api = api
        self.model_version = model_version
        self.language = language
        self.is_ocr = is_ocr
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.max_pages = max_pages
        self.rate_per_min = rate_per_min
        self.max_retries = max_retries
        self._last_request = 0.0

    # ---- 主入口 ----
    def convert(self, abs_path: Path, assets_dir: Path, task: Task | None = None) -> ConvertResult:
        api = self._resolve_api(abs_path)
        if api == "precision":
            self._require_token()
            self._check_pages(abs_path)                       # >200 页 → ConvertError（-60006 省）
            with TemporaryDirectory() as td:
                md, images_dir = self._precision(abs_path, Path(td))
                return self._assemble(md, images_dir, assets_dir, handled=True)
        md = self._agent(abs_path)                            # agent（免费，≤20 页/≤10MB）
        return ConvertResult(body=normalize(md), handled_images=False)

    def _resolve_api(self, pdf: Path) -> str:
        if self.api != "auto":
            return self.api
        return mineru_api_for(pdf)

    # ---- 前置校验 ----
    def _require_token(self) -> None:
        if not self.token:
            raise ConvertError("MinerU precision 需 Token：设 MINERU_TOKEN 或 --mineru-token")

    def _check_pages(self, pdf: Path) -> None:
        import pymupdf
        try:
            doc = pymupdf.open(str(pdf))
            try:
                pages = len(doc)
            finally:
                doc.close()
        except Exception as e:
            raise ConvertError(f"MinerU 页数探测失败: {e}") from e
        if pages > self.max_pages:
            raise ConvertError(f"MinerU 页数超限({pages}>{self.max_pages})，skip 省额度")

    # ---- 限速 ----
    def _throttle(self) -> None:
        if self.rate_per_min <= 0:
            return
        min_gap = 60.0 / self.rate_per_min
        wait = min_gap - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        """指数退避 + 抖动（封顶 60s），避免雷同重试撞同时点。"""
        return min(float(2 ** attempt), 60.0) + random.uniform(0, 1)

    # ---- Precision 流程 ----
    def _precision(self, pdf: Path, work_dir: Path) -> tuple[str, Path]:
        h = {"Authorization": f"Bearer {self.token}"}
        data_id = hashlib.sha1(str(pdf).encode()).hexdigest()[:32]   # ASCII（TABLE 5 约束）
        body = {
            "files": [{"name": pdf.name, "data_id": data_id, "is_ocr": self.is_ocr}],
            "model_version": self.model_version,                      # 顶层（TABLE 5）
            "enable_table": True, "enable_formula": True, "language": self.language,
        }
        r = self._post_json("/api/v4/file-urls/batch", h, body)
        batch_id = r["data"]["batch_id"]
        upload_url = r["data"]["file_urls"][0]
        self._put_file(upload_url, pdf)
        sub = self._poll(f"/api/v4/extract-results/batch/{batch_id}", h,
                         lambda d: d["data"]["extract_result"][0])    # TABLE 9
        return self._extract_zip(sub["full_zip_url"], work_dir)

    # ---- Agent 流程 ----
    def _agent(self, pdf: Path) -> str:
        body = {
            "file_name": pdf.name, "language": self.language, "is_ocr": self.is_ocr,
            "enable_table": True, "enable_formula": True,             # TABLE 14（page_range 单数）
        }
        r = self._post_json("/api/v1/agent/parse/file", {}, body)     # 无 Authorization
        task_id = r["data"]["task_id"]
        file_url = r["data"]["file_url"]
        self._put_file(file_url, pdf)
        sub = self._poll(f"/api/v1/agent/parse/{task_id}", {}, lambda d: d["data"])  # TABLE 16
        return self._get_text(sub["markdown_url"])

    # ---- HTTP（限速 + 退避 + 错误码分级）----
    def _post_json(self, path: str, headers: dict, body: dict) -> dict:
        url = _BASE + path
        all_h = {**headers, "Content-Type": "application/json"}
        last = "未知错误"
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.post(url, headers=all_h, json=body, timeout=60)
            except requests.RequestException as e:
                last = str(e); time.sleep(self._backoff(attempt)); continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"; time.sleep(self._backoff(attempt)); continue
            try:
                data = resp.json()
            except ValueError as e:
                raise ConvertError(f"MinerU 响应非 JSON({path}): {resp.text[:200]}") from e
            if not isinstance(data, dict):
                raise ConvertError(f"MinerU 响应非对象({path}): {resp.text[:200]}")
            if data.get("code") == 0:
                return data
            # 非 0：分级（daily/token 立即抛；retryable 可重试则退避）
            self._raise_for_code(data.get("code"), data.get("msg", ""), attempt < self.max_retries)
            last = f"code {data.get('code')}: {data.get('msg')}"   # retryable 且可重试 → 退避
            time.sleep(self._backoff(attempt))
        raise ConvertError(f"MinerU 提交失败({path}): {last}")

    def _put_file(self, url: str, pdf: Path) -> None:
        last = "未知错误"
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with open(pdf, "rb") as f:
                    resp = requests.put(url, data=f, timeout=120)
            except requests.RequestException as e:
                last = str(e); time.sleep(self._backoff(attempt)); continue
            if resp.status_code in (200, 201):
                return
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"; time.sleep(self._backoff(attempt)); continue
            raise ConvertError(f"MinerU 上传失败: HTTP {resp.status_code}")
        raise ConvertError(f"MinerU 上传失败: {last}")

    def _get_text(self, url: str) -> str:
        return self._get(url).text

    def _get_bytes(self, url: str) -> bytes:
        return self._get(url).content

    def _get(self, url: str):
        self._throttle()
        try:
            resp = requests.get(url, timeout=180)
        except requests.RequestException as e:
            raise ConvertError(f"MinerU 下载失败: {e}") from e
        if resp.status_code != 200:
            raise ConvertError(f"MinerU 下载失败: HTTP {resp.status_code}")
        return resp

    def _poll(self, path: str, headers: dict, extract):
        """轮询至 state==done，返回 extract(data) 的子 dict。failed→错误码分级；超时→ConvertError。"""
        url = _BASE + path
        t0 = time.monotonic()
        retry = 0
        while time.monotonic() - t0 < self.poll_timeout:
            self._throttle()
            try:
                resp = requests.get(url, headers=headers or None, timeout=30)
            except requests.RequestException:
                time.sleep(self.poll_interval); continue
            if resp.status_code != 200:
                time.sleep(self.poll_interval); continue
            try:
                d = resp.json()
            except ValueError:
                time.sleep(self.poll_interval); continue   # 临时非 JSON（错误页）→ 重试轮询
            if not isinstance(d, dict):
                time.sleep(self.poll_interval); continue   # 顶层非对象（"ok"/[1,2] 等）→ 重试轮询
            if d.get("code") != 0:
                # 顶层非 0：分级（daily/token 立即抛；retryable 指数退避重试）
                self._raise_for_code(d.get("code"), d.get("msg", ""), True)
                time.sleep(self._backoff(retry)); retry += 1; continue
            try:
                sub = extract(d)
            except (KeyError, IndexError, TypeError, AttributeError):
                time.sleep(self.poll_interval); continue   # 响应结构异常（含 data:null）→ 重试轮询
            if not isinstance(sub, dict):
                time.sleep(self.poll_interval); continue   # extract 返回非 dict → 重试轮询
            state = sub.get("state")
            if state == "done":
                return sub
            if state == "failed":
                # 失败必抛（_raise_for_code retryable_ok=False 无 return 路径，必落到末尾 raise）
                self._raise_for_code(sub.get("err_code"), sub.get("err_msg", "解析失败"), False)
            time.sleep(self.poll_interval)
        raise ConvertError(f"MinerU 轮询超限({self.poll_timeout}s): {path}")

    def _raise_for_code(self, code, msg: str, retryable_ok: bool) -> None:
        """错误码分级：daily→即停；token→提示；retryable 且可重试→return 退避；其余→ConvertError。"""
        cs = "" if code is None else str(code)
        try:
            ci = int(code)
        except (TypeError, ValueError):
            ci = None
        if cs in _TOKEN_ERR:
            raise ConvertError(f"MinerU Token 错误({code}): {msg}，请更换 Token")
        if ci in _DAILY_LIMIT:
            raise ConvertError(f"{DAILY_LIMIT_MARK}: 每日额度上限({code}) {msg}")
        if ci in _RETRYABLE and retryable_ok:
            return   # 退避重试
        raise ConvertError(f"MinerU 错误({code}): {msg}")

    # ---- zip 解析 ----
    def _extract_zip(self, zip_url: str, work_dir: Path) -> tuple[str, Path]:
        z = zipfile.ZipFile(io.BytesIO(self._get_bytes(zip_url)))
        z.extractall(str(work_dir))
        md_files = list(work_dir.rglob("full.md")) or list(work_dir.rglob("*.md"))
        if not md_files:
            raise ConvertError("MinerU zip 内无 md")
        md_file = md_files[0]
        return md_file.read_text(encoding="utf-8"), md_file.parent / "images"

    # ---- 图片整合 ----
    def _assemble(self, md: str, images_dir: Path | None, assets_dir: Path, handled: bool) -> ConvertResult:
        image_refs: list[str] = []
        if images_dir and images_dir.exists():
            assets_dir.mkdir(parents=True, exist_ok=True)
            new_prefix = f"./{assets_dir.name}/"
            for img in sorted(images_dir.iterdir()):
                if not img.is_file():
                    continue
                try:
                    shutil.copy2(img, assets_dir / img.name)
                except OSError:
                    continue   # 单图复制失败 → 跳过，不影响整体
                # 按 basename 重写 md 中任意路径的图片引用（不假定固定 images/ 前缀）
                pat = re.compile(r"(!\[[^\]]*\]\()[^)]*?" + re.escape(img.name) + r"(\))")
                md = pat.sub(lambda m: m.group(1) + new_prefix + img.name + m.group(2), md)
                image_refs.append(new_prefix + img.name)
        return ConvertResult(body=normalize(md), image_refs=image_refs, handled_images=handled)
