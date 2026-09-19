from shimeji_dl.formats.shimeji_xml import ShimejiXmlFormat


def test_extracts_images_sounds_and_info_assets_with_lxml() -> None:
    data = b'''<Mascot><ActionList><Pose Image="/shime1.png" ImageAnchor="1,2" Sound="step.wav"/><Pose Image="nested/custom.png"/></ActionList><Information><PreviewImage>preview.png</PreviewImage></Information></Mascot>'''
    refs = ShimejiXmlFormat().extract_asset_refs(data)
    assert [ref.path for ref in refs] == [
        "shime1.png",
        "sound/step.wav",
        "nested/custom.png",
        "preview.png",
    ]


def test_rejects_external_entity_document() -> None:
    data = b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]><Mascot>&ext;</Mascot>'
    parser = ShimejiXmlFormat()
    assert parser.is_valid(data)
    assert parser.extract_asset_refs(data) == []
