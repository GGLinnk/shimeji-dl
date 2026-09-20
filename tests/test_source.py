import asyncio
import json

from shimeji_dl.core.http_error import HttpError
from shimeji_dl.core.models import AssetRef
from shimeji_dl.core.storage import MAX_ASSET_PATH_LENGTH
from shimeji_dl.sources.shimejis_xyz.adapter import (
    ShimejisXYZSource,
    _asset_url,
    _origin,
    extract_pack_urls_from_html,
    extract_slugs_from_html,
)


class _RecordingClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def get(self, *args, **kwargs):
        class Response:
            url = "https://shimejis.xyz/api/shimeji/example/configuration"
            content = json.dumps(self._payload).encode()

        return Response()


def _fetch(payload: dict) -> tuple[object, list[str]]:
    rejections: list[str] = []
    source = ShimejisXYZSource()
    manifest = asyncio.run(
        source.fetch_manifest(
            _RecordingClient(payload),
            source._character("example"),
            report_rejection=rejections.append,
        )
    )
    return manifest, rejections


def test_extract_slugs_uses_html_parser() -> None:
    document = '''<a href="/directory/shimeji/undertale-sans">Sans</a><a href="https://shimejis.xyz/directory/shimeji/undertale-frisk">Frisk</a><a href="/directory/shimeji/undertale-sans">Duplicate</a>'''
    assert extract_slugs_from_html(document) == ["undertale-sans", "undertale-frisk"]


def test_extract_pack_urls_uses_directory_links_only() -> None:
    document = '''
    <a href="/directory/undertale-shimeji-pack">Undertale</a>
    <a href="https://shimejis.xyz/directory/sonic-shimeji-pack">Sonic</a>
    <a href="/directory/shimeji/undertale-sans">Sans</a>
    <a href="https://example.com/directory/nope">Nope</a>
    <a href="/directory/undertale-shimeji-pack">Duplicate</a>
    '''
    assert extract_pack_urls_from_html(document) == [
        "https://shimejis.xyz/directory/undertale-shimeji-pack",
        "https://shimejis.xyz/directory/sonic-shimeji-pack",
    ]


def test_source_suitable() -> None:
    assert ShimejisXYZSource.suitable("undertale-sans")
    assert ShimejisXYZSource.suitable("https://shimejis.xyz/directory/undertale-shimeji-pack")
    assert ShimejisXYZSource.suitable("https://shimejis.xyz")
    assert ShimejisXYZSource.suitable("https://shimejis.xyz/directory")
    assert not ShimejisXYZSource.suitable("https://example.com/foo")


def test_whole_site_requires_confirmation() -> None:
    source = ShimejisXYZSource()
    assert source.confirmation_message("https://shimejis.xyz")
    assert source.confirmation_message("https://shimejis.xyz/directory")
    assert source.confirmation_message("https://shimejis.xyz/directory/undertale-shimeji-pack") is None


def test_whole_site_extracts_and_deduplicates_characters() -> None:
    import asyncio

    class Client:
        async def get_text(self, url: str, *, headers=None) -> str:
            if url == "https://shimejis.xyz/directory":
                return '''
                <a href="/directory/undertale-shimeji-pack">Undertale</a>
                <a href="/directory/sonic-shimeji-pack">Sonic</a>
                '''
            if url.endswith("undertale-shimeji-pack"):
                return '''
                <a href="/directory/shimeji/shared-character">Shared</a>
                <a href="/directory/shimeji/undertale-sans">Sans</a>
                '''
            if url.endswith("sonic-shimeji-pack"):
                return '''
                <a href="/directory/shimeji/shared-character">Shared</a>
                <a href="/directory/shimeji/sonic">Sonic</a>
                '''
            raise AssertionError(url)

    characters = asyncio.run(ShimejisXYZSource().extract(Client(), "https://shimejis.xyz"))
    assert [character.id for character in characters] == ["shared-character", "undertale-sans", "sonic"]


def test_whole_site_scan_skips_one_malformed_pack_page_but_keeps_others() -> None:
    """A single pack page that fails to decode must cost only that pack.

    Before this fix, get_text's strict decode raising HttpError inside the
    TaskGroup driving the whole-catalogue scan cancelled every sibling pack
    and aborted the entire directory extraction.
    """

    class Client:
        async def get_text(self, url: str, *, headers=None) -> str:
            if url == "https://shimejis.xyz/directory":
                return '''
                <a href="/directory/undertale-shimeji-pack">Undertale</a>
                <a href="/directory/broken-shimeji-pack">Broken</a>
                <a href="/directory/sonic-shimeji-pack">Sonic</a>
                '''
            if url.endswith("undertale-shimeji-pack"):
                return '<a href="/directory/shimeji/undertale-sans">Sans</a>'
            if url.endswith("broken-shimeji-pack"):
                raise HttpError(url, 200, "could not decode response as utf-8")
            if url.endswith("sonic-shimeji-pack"):
                return '<a href="/directory/shimeji/sonic">Sonic</a>'
            raise AssertionError(url)

    characters = asyncio.run(ShimejisXYZSource().extract(Client(), "https://shimejis.xyz"))
    assert [character.id for character in characters] == ["undertale-sans", "sonic"]


def test_source_exposes_desktop_compatible_optional_info_config() -> None:
    assert ShimejisXYZSource.config_names == ("actions.xml", "behaviors.xml", "info.xml")


def test_sound_candidates_cover_known_shimeji_package_locations() -> None:
    source = ShimejisXYZSource()
    character = source._character("undertale-sans")
    urls = source.asset_candidates(character, AssetRef("step.wav", "sound/step.wav"))
    assert urls == [
        "https://sprites.shimejis.xyz/directory/undertale-sans/sound/step.wav",
        "https://sprites.shimejis.xyz/directory/undertale-sans/img/sound/step.wav",
        "https://sprite.shimejis.xyz/directory/undertale-sans/sound/step.wav",
        "https://sprite.shimejis.xyz/directory/undertale-sans/img/sound/step.wav",
    ]


def test_configuration_api_is_parsed_as_an_authoritative_sprite_manifest() -> None:
    payload = {
        "actions": "<Mascot><Pose Image='/shime1.png'/></Mascot>",
        "behaviors": "<Mascot/>",
        "sprites": {
            "/shime1.png": {"x": 1, "y": 2, "width": 3, "height": 4},
            "/nested/shime2.png": {"x": 5, "y": 6, "width": 7, "height": 8},
            "/invalid.jpg": {"x": 0, "y": 0, "width": 1, "height": 1},
            "../escape.png": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
        "spritesheet": "https://sprites.shimejis.xyz/directory/example/spritesheet.png",
        "metadata": {"shimejiName": "Example"},
    }

    class Response:
        url = "https://shimejis.xyz/api/shimeji/example/configuration"
        content = json.dumps(payload).encode()

    class Client:
        async def get(self, *args, **kwargs):
            return Response()

    source = ShimejisXYZSource()
    manifest = asyncio.run(source.fetch_manifest(Client(), source._character("example")))

    assert manifest is not None
    assert manifest.authoritative
    assert set(manifest.configs) == {"actions.xml", "behaviors.xml"}
    assert list(manifest.sprites) == ["shime1.png", "nested/shime2.png"]
    assert manifest.sprites["shime1.png"].width == 3
    assert manifest.spritesheet_url == payload["spritesheet"]
    assert manifest.metadata == {"shimejiName": "Example"}


def test_manifest_ignores_unknown_metadata_key_but_keeps_known_fields() -> None:
    """An unknown metadata key must not void the whole metadata block.

    Unlike a sprite entry, there is no single malformed item to drop here;
    the only correct outcome is ignoring the unknown key and keeping every
    known field the site actually sent.
    """
    payload = {
        "actions": "<Mascot/>",
        "metadata": {"shimejiName": "Example", "futureKeyNotYetKnown": "value"},
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert manifest.metadata == {"shimejiName": "Example"}
    assert not rejections


def test_configuration_api_rejects_untrusted_spritesheet_origin() -> None:
    payload = {
        "actions": "<Mascot/>",
        "sprites": {"/shime1.png": {"x": 0, "y": 0, "width": 1, "height": 1}},
        "spritesheet": "https://example.com/spritesheet.png",
    }

    class Response:
        url = "https://shimejis.xyz/api/shimeji/example/configuration"
        content = json.dumps(payload).encode()

    class Client:
        async def get(self, *args, **kwargs):
            return Response()

    source = ShimejisXYZSource()
    manifest = asyncio.run(source.fetch_manifest(Client(), source._character("example")))

    assert manifest is not None
    assert manifest.spritesheet_url is None


def test_manifest_drops_sprite_with_over_long_key_but_keeps_siblings() -> None:
    over_long_key = "/" + ("a" * (MAX_ASSET_PATH_LENGTH + 10)) + ".png"
    payload = {
        "actions": "<Mascot/>",
        "sprites": {
            over_long_key: {"x": 0, "y": 0, "width": 1, "height": 1},
            "/shime1.png": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert list(manifest.sprites) == ["shime1.png"]
    assert rejections


def test_manifest_drops_over_long_spritesheet_url_but_keeps_configs() -> None:
    over_long_url = "https://sprites.shimejis.xyz/" + ("a" * 2100) + ".png"
    payload = {
        "actions": "<Mascot/>",
        "spritesheet": over_long_url,
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert manifest.spritesheet_url is None
    assert manifest.configs
    assert rejections


def test_manifest_drops_sprite_with_unknown_region_field_but_keeps_siblings() -> None:
    payload = {
        "actions": "<Mascot/>",
        "sprites": {
            "/shime1.png": {"x": 0, "y": 0, "width": 1, "height": 1, "extra": True},
            "/shime2.png": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert list(manifest.sprites) == ["shime2.png"]
    assert rejections


def test_manifest_drops_sprite_with_string_coordinate_but_keeps_siblings() -> None:
    payload = {
        "actions": "<Mascot/>",
        "sprites": {
            "/shime1.png": {"x": "5", "y": 0, "width": 1, "height": 1},
            "/shime2.png": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert list(manifest.sprites) == ["shime2.png"]
    assert rejections


def test_manifest_survives_non_dict_sprites_field() -> None:
    payload = {
        "actions": "<Mascot/>",
        "sprites": ["not", "a", "dict"],
    }

    manifest, rejections = _fetch(payload)

    assert manifest is not None
    assert manifest.sprites == {}
    assert manifest.configs
    assert rejections


def test_origin_normalizes_explicit_default_port_and_case() -> None:
    assert _origin("https://Sprites.Shimejis.xyz:443/x") == "https://sprites.shimejis.xyz"


def test_origin_keeps_non_default_port() -> None:
    assert _origin("https://sprites.shimejis.xyz:8443/x") == "https://sprites.shimejis.xyz:8443"


def test_asset_url_accepts_trusted_host_with_explicit_default_port() -> None:
    url = "https://Sprites.Shimejis.xyz:443/directory/example/shime1.png"
    assert _asset_url(url) == url


def test_asset_url_rejects_embedded_credentials() -> None:
    assert _asset_url("https://user:pw@sprites.shimejis.xyz/shime1.png") is None


def test_asset_candidates_reject_untrusted_absolute_url() -> None:
    source = ShimejisXYZSource()
    character = source._character("undertale-sans")
    ref = AssetRef("shime1.png", "shime1.png", absolute_url="https://evil.example/shime1.png")
    assert source.asset_candidates(character, ref) == []


def test_asset_candidates_accept_trusted_absolute_url_with_default_port() -> None:
    source = ShimejisXYZSource()
    character = source._character("undertale-sans")
    url = "https://Sprites.Shimejis.xyz:443/directory/undertale-sans/shime1.png"
    ref = AssetRef("shime1.png", "shime1.png", absolute_url=url)
    assert source.asset_candidates(character, ref) == [url]
