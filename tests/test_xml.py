from shimeji_dl.formats.shimeji_xml import ShimejiXmlFormat


def test_extracts_image_attributes_with_lxml() -> None:
    data = b'''<Mascot><ActionList><Pose Image="/shime1.png" ImageAnchor="1,2"/><Pose Image="nested/custom.png"/></ActionList></Mascot>'''
    refs = ShimejiXmlFormat().extract_asset_refs(data)
    assert [ref.path for ref in refs] == ["shime1.png", "nested/custom.png"]


def test_rejects_external_entity_document() -> None:
    data = b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]><Mascot>&ext;</Mascot>'
    parser = ShimejiXmlFormat()
    assert parser.is_valid(data)
    assert parser.extract_asset_refs(data) == []
