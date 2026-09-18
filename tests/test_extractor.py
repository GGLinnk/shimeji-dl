from shimeji_dl.extractors.shimejis_xyz import ShimejisXYZExtractor


def test_parse_pack_html():
    html = '''
    <a href="/directory/shimeji/undertale-sans">Sans</a>
    <a href="/directory/shimeji/undertale-nightmare-sans-by-niuniu-nuko">Nightmare Sans</a>
    <a href="/directory/shimeji/undertale-sans">duplicate</a>
    '''
    chars = ShimejisXYZExtractor.parse_pack_html(
        html, pack_url="https://shimejis.xyz/directory/undertale-shimeji-pack"
    )
    assert [c.slug for c in chars] == [
        "undertale-sans",
        "undertale-nightmare-sans-by-niuniu-nuko",
    ]
    assert chars[1].artist == "Niuniu Nuko"
