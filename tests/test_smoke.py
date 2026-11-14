def test_package_importable():
    import xmd

    assert xmd.__version__ == "0.1.0"
