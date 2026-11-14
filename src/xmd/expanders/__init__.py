"""容器展开器：容器归档 → 虚拟 FileEntry 列表（主进程执行）。

ExpandError 为全部展开器的统一异常；当前注册 .lakebook。
"""
from xmd.expanders.lakebook import ExpandError, expand_lakebook

__all__ = ["ExpandError", "expand_lakebook"]
