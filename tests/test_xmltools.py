from shimeji_dl.xmltools import image_references, is_probable_config


def test_extract_image_references_and_dedupe():
    xml = b'''<?xml version="1.0"?>
    <Mascot>
      <ActionList>
        <Action Name="Walk"><Animation>
          <Pose Image="/shime1.png" />
          <Pose Image="/sub/custom.png" />
          <Pose Image="/shime1.png" />
        </Animation></Action>
      </ActionList>
    </Mascot>'''
    assert image_references(xml) == ["shime1.png", "sub/custom.png"]
    assert is_probable_config(xml, "actions")


def test_unsafe_image_path_is_rejected():
    xml = b'<Mascot><Action Image="../../evil.png"/><Action Image="/ok.png"/></Mascot>'
    assert image_references(xml) == ["ok.png"]


def test_regex_fallback_for_malformed_old_xml():
    xml = b'<Mascot><Action><Pose Image="/shime99.png"></Mascot>'
    assert image_references(xml) == ["shime99.png"]
