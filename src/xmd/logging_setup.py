"""静默 pdfminer 的 FontBBox 等噪声日志。"""
import logging


def silence_pdfminer() -> None:
    for name in ("pdfminer", "pdfminer.pdfinterp", "pdfminer.cmapdb", "pdfminer.pdfpage"):
        logging.getLogger(name).setLevel(logging.ERROR)
