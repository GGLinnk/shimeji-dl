from shimeji_dl.xmlutil import extract_image_refs


def test_extracts_and_deduplicates_image_references() -> None:
    xml = b'''<?xml version="1.0"?>
    <Mascot>
      <Pose Image="/shime1.png" ImageAnchor="64,128" />
      <Pose Image="img/custom/walk 2.png" />
      <Pose Image="/shime1.png" />
      <Thing Whatever="not-an-image" />
    </Mascot>'''

    refs = extract_image_refs(xml)
    assert [ref.path for ref in refs] == ["shime1.png", "custom/walk 2.png"]


def test_rejects_parent_traversal() -> None:
    xml = b'<Mascot><Pose Image="../secret.png" /></Mascot>'
    assert extract_image_refs(xml) == []


def test_supports_absolute_image_url() -> None:
    xml = b'<Mascot><Pose Image="https://cdn.example.test/assets/foo.png" /></Mascot>'
    refs = extract_image_refs(xml)
    assert refs[0].path == "foo.png"
    assert refs[0].absolute_url == "https://cdn.example.test/assets/foo.png"
