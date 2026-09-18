from shimeji_dl.extractors.shimejis_xyz import extract_slugs_from_html


def test_pack_link_extraction_is_ordered_and_deduplicated() -> None:
    html = '''
    <a href="/directory/shimeji/undertale-napstablook">Napstablook</a>
    <a href="https://shimejis.xyz/directory/shimeji/undertale-asriel">Asriel</a>
    <a href="/directory/shimeji/undertale-napstablook">duplicate</a>
    <a href="/directory/other">ignore</a>
    '''
    assert extract_slugs_from_html(html) == ["undertale-napstablook", "undertale-asriel"]
