import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shimeji_dl.core.asset_path_escapes_destination import AssetPathEscapesDestination
from shimeji_dl.core.storage import (
    RESOURCE_HEAD_BYTES,
    atomic_write,
    confined_asset_path,
    is_valid_local_resource,
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


@pytest.mark.parametrize(
    "value",
    [
        "x/C:evil.png",
        "a/evil.bat:x.png",
        "a/../b.png",
        "CON.png",
        "x/NUL.png",
        "a//b.png",
        "C:/evil.png",
    ],
)
def test_normalize_resource_ref_rejects_hostile_paths(value: str) -> None:
    assert normalize_resource_ref(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("sound/x.wav", ("sound/x.wav", None)),
        ("sub/x.png", ("sub/x.png", None)),
        ("画像/しめじ.png", ("画像/しめじ.png", None)),
    ],
)
def test_normalize_resource_ref_accepts_valid_paths(value: str, expected: tuple[str, None]) -> None:
    assert normalize_resource_ref(value) == expected


def test_confined_asset_path_resolves_within_destination(tmp_path: Path) -> None:
    resolved = confined_asset_path(tmp_path, "sub/foo.png")
    assert resolved == (tmp_path / "sub" / "foo.png").resolve()
    assert resolved.is_relative_to(tmp_path.resolve())


def test_confined_asset_path_rejects_parent_traversal(tmp_path: Path) -> None:
    dest = tmp_path / "character"
    dest.mkdir()
    with pytest.raises(AssetPathEscapesDestination):
        confined_asset_path(dest, "../evil.png")


@pytest.mark.skipif(sys.platform != "win32", reason="drive-relative join only escapes on Windows")
def test_confined_asset_path_rejects_drive_relative_escape(tmp_path: Path) -> None:
    dest = tmp_path / "character"
    dest.mkdir()
    other_drive = "D" if dest.drive.upper() != "D:" else "E"
    with pytest.raises(AssetPathEscapesDestination):
        confined_asset_path(dest, f"{other_drive}:evil.png")


def test_atomic_write_leaves_no_part_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic_write(target, b"payload")
    assert target.read_bytes() == b"payload"
    assert list(tmp_path.glob("*.part")) == []


def test_atomic_write_cleans_up_on_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "out.bin"

    def _raise_disk_full(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.fsync", _raise_disk_full)

    with pytest.raises(OSError):
        atomic_write(target, b"payload")

    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


def _bmp_bytes(mode: str) -> bytes:
    buf = BytesIO()
    Image.new(mode, (2, 2)).save(buf, format="BMP")
    return buf.getvalue()


@pytest.mark.parametrize("mode", ["1", "P", "RGB", "RGBA"])
def test_bmp_signature_accepts_every_bit_depth(mode: str) -> None:
    assert looks_like_resource(_bmp_bytes(mode), "sprite.bmp")


def test_bmp_signature_rejects_html_with_bm_prefix() -> None:
    html = b"BM" + b"<html>this looks like a page, not a bitmap</html>"
    assert not looks_like_resource(html, "sprite.bmp")


def test_wav_signature_rejects_avi_container() -> None:
    avi = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"LIST"
    assert not looks_like_resource(avi, "clip.wav")


def test_aif_signature_rejects_djvu_container() -> None:
    djvu = b"FORM" + b"\x00\x00\x00\x00" + b"DJVU" + b"INFO"
    assert not looks_like_resource(djvu, "clip.aif")


def test_aif_signature_accepts_aifc_variant() -> None:
    aifc = b"FORM" + b"\x00\x00\x00\x00" + b"AIFC" + b"COMM"
    assert looks_like_resource(aifc, "clip.aif")


def test_ogg_signature_rejects_bare_four_byte_marker() -> None:
    assert not looks_like_resource(b"OggS", "clip.ogg")


def test_ogg_signature_accepts_full_page_header() -> None:
    opus = b"OggS" + bytes([0]) + bytes([0x02]) + b"XX"
    assert looks_like_resource(opus, "clip.ogg")


def test_mp3_signature_accepts_bare_frame_sync() -> None:
    assert looks_like_resource(b"\xff\xfb\x90", "clip.mp3")


def test_mp3_signature_rejects_reserved_version_bits() -> None:
    assert not looks_like_resource(b"\xff\xeb\x90", "clip.mp3")


def test_mp3_signature_rejects_reserved_layer_bits() -> None:
    assert not looks_like_resource(b"\xff\xf9\x90", "clip.mp3")


def test_mp3_signature_rejects_invalid_bitrate_index() -> None:
    assert not looks_like_resource(b"\xff\xfb\xf0", "clip.mp3")


def test_mp3_signature_accepts_free_format_bitrate() -> None:
    assert looks_like_resource(b"\xff\xfb\x00", "clip.mp3")


def test_ogg_signature_rejects_unsupported_stream_structure_version() -> None:
    assert not looks_like_resource(b"OggS\x01\x02XX", "clip.ogg")


def test_ogg_signature_rejects_header_type_above_defined_bits() -> None:
    assert not looks_like_resource(b"OggS\x00\x08XX", "clip.ogg")


def test_au_signature_accepts_little_endian_variant() -> None:
    """The byte-swapped "dns." magic is a required, supported AU variant.

    Real encoders emit it; accepting it is a format requirement, not an
    incidental widening of an unrelated tightening.
    """
    assert looks_like_resource(b"dns.", "clip.au")


def test_unknown_content_is_rejected_for_every_suffix() -> None:
    for name in ("clip.mp3", "clip.ogg", "sprite.bmp", "sprite.png"):
        assert not looks_like_resource(b"<html></html>", name)
        assert not looks_like_resource(b'{"not": "media"}', name)
        assert not looks_like_resource(b"", name)


def test_png_content_is_rejected_for_jpg_suffix() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert not looks_like_resource(png, "sprite.jpg")


def test_is_valid_local_resource_accepts_valid_head_with_garbage_tail(tmp_path: Path) -> None:
    path = tmp_path / "sprite.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (RESOURCE_HEAD_BYTES * 4))
    assert is_valid_local_resource(path)
