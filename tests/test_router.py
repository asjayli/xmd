import pymupdf

from xmd.router import (
    AGENT_MAX_MB,
    AGENT_MAX_PAGES,
    classify_pdf,
    mineru_api_for,
)


def _make_text_pdf(path, text="hello world " * 30):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _make_image_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24))
    pix.set_rect(pymupdf.IRect(0, 0, 24, 24), (255, 0, 0))
    page.insert_image(pymupdf.Rect(0, 0, 60, 60), pixmap=pix)
    page.insert_text((72, 200), "caption " * 30)
    doc.save(str(path))
    doc.close()


def test_type3_pdf_routes_to_precision(tcp_pdf):
    # 真实有道 .note.pdf：全 Type3 → 复杂 → precision
    assert classify_pdf(tcp_pdf) == ("mineru", "precision")


def test_simple_text_pdf_routes_to_markitdown(tmp_path):
    p = tmp_path / "simple.pdf"
    _make_text_pdf(p)
    assert classify_pdf(p) == ("markitdown", "agent")


def test_image_pdf_routes_to_precision(tmp_path):
    p = tmp_path / "img.pdf"
    _make_image_pdf(p)
    assert classify_pdf(p) == ("mineru", "precision")


def test_agent_limits_constants():
    assert AGENT_MAX_PAGES == 20
    assert AGENT_MAX_MB == 10


def test_mineru_api_for_simple(tmp_path):
    p = tmp_path / "simple.pdf"
    _make_text_pdf(p)
    assert mineru_api_for(p) == "agent"


def test_mineru_api_for_complex(tcp_pdf):
    assert mineru_api_for(tcp_pdf) == "precision"


def test_classify_corrupt_pdf_falls_back(tmp_path):
    # 损坏/非 PDF → pymupdf 探测抛异常 → 安全降级 markitdown（不让 worker 崩）
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf")
    assert classify_pdf(p) == ("markitdown", "agent")


def test_mineru_api_for_corrupt_upgrades_precision(tmp_path):
    # 探测失败 → 安全升级 precision（容错侧）
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf")
    assert mineru_api_for(p) == "precision"


def _make_encrypted_pdf(path):
    # 加密 PDF：open 成功，但 get_fonts/get_text 需密码 → _probe 抛异常走 None 分支
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()


def test_encrypted_pdf_probe_falls_back(tmp_path):
    # 加密（open 成功、内容读取失败）子路径：classify 降级 markitdown，mineru 升级 precision
    p = tmp_path / "enc.pdf"
    _make_encrypted_pdf(p)
    assert classify_pdf(p) == ("markitdown", "agent")
    assert mineru_api_for(p) == "precision"
