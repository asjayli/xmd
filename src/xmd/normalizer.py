"""精准 CJK 归一：仅对部首/兼容区做 NFKC，保留全角 ASCII 与 markdown 语法字符。"""
from __future__ import annotations

import re
import unicodedata

# 仅这些区段做 NFKC 归一（康熙部首 + CJK 部首补充 + 扩展A + 兼容表意）
_TARGET_RANGES = (
    (0x2E80, 0x2FFF),   # CJK 部首补充 + 康熙部首
    (0x3400, 0x4DBF),   # CJK 扩展 A
    (0xF900, 0xFAFF),   # CJK 兼容表意
)

# NFKC 不覆盖 / NFKC 产生繁体 的补充修正；随实测扩展
EXTRA_MAP: dict[str, str] = {
    "⻬": "齐",   # U+2EEC，NFKC 不变
    "⻝": "食",
    "⻢": "驿",
    "戶": "户",   # NFKC 残留繁体
    "里": "里",
}


def _in_target(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _TARGET_RANGES)


def normalize(text: str) -> str:
    if not text:
        return ""
    out: list[str] = []
    for c in text:
        if c in EXTRA_MAP:
            out.append(EXTRA_MAP[c])
            continue
        cp = ord(c)
        if _in_target(cp):
            nk = unicodedata.normalize("NFKC", c)
            out.append(EXTRA_MAP.get(nk, nk))  # NFKC 后再兜底（如戶）
        else:
            out.append(c)  # 全角 ASCII / markdown 语法字符原样保留
    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip()
    return text
