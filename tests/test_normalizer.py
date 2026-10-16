from xmd.normalizer import normalize


def test_kangxi_radicals_normalized():
    assert normalize("⼿⽹⼀⽅⽂") == "手网一方文"


def test_cjk_radical_supplement_via_extra_map():
    # ⻬ U+2EEC NFKC 不变，需 EXTRA_MAP
    assert normalize("⻬") == "齐"


def test_nfkc_traditional_residual_fixed():
    # ⼾ NFKC → 戶（繁体），EXTRA_MAP 再 → 户
    assert normalize("⼾") == "户"


def test_fullwidth_asterisk_preserved():  # 禁止误转为强调语法
    assert normalize("＊重点＊") == "＊重点＊"


def test_fullwidth_pipe_preserved():  # 禁止误转为表格语法
    assert normalize("｜表头｜") == "｜表头｜"


def test_circled_numbers_preserved():
    assert normalize("①②③") == "①②③"


def test_collapse_blank_lines():
    assert normalize("a\n\n\n\nb") == "a\n\nb"


def test_rstrip_trailing_whitespace():
    assert normalize("a   \n") == "a"


def test_empty_string():
    assert normalize("") == ""


def test_placeholder_note_text():
    assert normalize("\xa0\n").strip() == ""
