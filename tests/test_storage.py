from shimeji_dl.core.storage import normalize_asset_ref


def test_normalize_asset_ref() -> None:
    assert normalize_asset_ref("/img/foo.png") == ("foo.png", None)
    assert normalize_asset_ref("../evil.png") is None
