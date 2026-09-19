from shimeji_dl.core.storage import (
    looks_like_resource,
    normalize_asset_ref,
    normalize_resource_ref,
)


def test_normalize_asset_ref() -> None:
    assert normalize_asset_ref("/img/foo.png") == ("foo.png", None)
    assert normalize_asset_ref("../evil.png") is None
    assert normalize_asset_ref("sound/foo.wav") is None


def test_normalize_resource_ref_supports_shimeji_sounds() -> None:
    assert normalize_resource_ref("foo.wav") == ("sound/foo.wav", None)
    assert normalize_resource_ref("sound/effect.wav") == ("sound/effect.wav", None)
    assert normalize_resource_ref("/img/nested/foo.png") == ("nested/foo.png", None)


def test_resource_validation_handles_images_and_audio() -> None:
    assert looks_like_resource(b"\x89PNG\r\n\x1a\n", "shime1.png")
    assert looks_like_resource(b"RIFF\x00\x00\x00\x00WAVE", "sound/effect.wav")
    assert not looks_like_resource(b"<html>not an asset</html>", "sound/effect.wav")
