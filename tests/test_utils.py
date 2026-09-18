import pytest

from shimeji_dl.utils import sanitize_asset_path, title_from_slug


def test_slug_title():
    assert title_from_slug("undertale-nightmare-sans-by-niuniu-nuko") == (
        "Nightmare Sans",
        "Niuniu Nuko",
    )


def test_asset_paths():
    assert sanitize_asset_path("/foo/bar.png") == "foo/bar.png"
    with pytest.raises(ValueError):
        sanitize_asset_path("../evil.png")
