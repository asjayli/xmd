from pathlib import Path

from xmd.image_extractor import extract_images


def test_tcp_has_images(tcp_pdf, tmp_path):
    assets = tmp_path / "tcp.assets"
    imgs = extract_images(tcp_pdf, assets)
    assert len(imgs) >= 1
    assert assets.is_dir()
    files = list(assets.iterdir())
    assert len(files) == len(imgs)
    assert all(r.rel_ref.startswith("./") for r in imgs)


def test_blinko_has_no_images(blinko_pdf, tmp_path):
    imgs = extract_images(blinko_pdf, tmp_path / "bl.assets")
    assert imgs == []


def test_force_clears_old_assets(tcp_pdf, tmp_path):
    assets = tmp_path / "tcp.assets"
    assets.mkdir()
    old = assets / "img_999.png"
    old.write_bytes(b"stale")
    extract_images(tcp_pdf, assets, force=True)
    assert not old.exists()


def test_dedup_by_xref(tcp_pdf, tmp_path):
    assets = tmp_path / "a"
    imgs = extract_images(tcp_pdf, assets)
    names = [Path(r.rel_ref).name for r in imgs]
    assert len(names) == len(set(names))
