import asyncio
import json

from shimeji_dl.core.models import AssetRef
from shimeji_dl.sources.shimejis_xyz import (
    ShimejisXYZSource,
    extract_pack_urls_from_html,
    extract_slugs_from_html,
)


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
