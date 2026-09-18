from shimeji_dl.utils import compress_numbers, normalize_asset_ref


def test_compress_numbers() -> None:
    assert compress_numbers([1, 2, 3, 5, 8, 9]) == ["1-3", "5", "8-9"]


def test_normalize_img_prefix() -> None:
    assert normalize_asset_ref("/img/foo/shime1.png") == ("foo/shime1.png", None)
