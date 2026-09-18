from shimeji_dl.sources.shimejis_xyz import ShimejisXYZSource, extract_slugs_from_html


def test_extract_slugs_uses_html_parser() -> None:
    html = '''<a href="/directory/shimeji/undertale-sans">Sans</a><a href="https://shimejis.xyz/directory/shimeji/undertale-frisk">Frisk</a><a href="/directory/shimeji/undertale-sans">Duplicate</a>'''
    assert extract_slugs_from_html(html) == ["undertale-sans", "undertale-frisk"]


def test_source_suitable() -> None:
    assert ShimejisXYZSource.suitable("undertale-sans")
    assert ShimejisXYZSource.suitable("https://shimejis.xyz/directory/undertale-shimeji-pack")
    assert not ShimejisXYZSource.suitable("https://example.com/foo")
