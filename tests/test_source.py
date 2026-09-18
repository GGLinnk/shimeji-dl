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
