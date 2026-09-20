import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image

from shimeji_dl.core.engine import (
    DownloadEngine,
    DownloadOptions,
    _extract_sprite_regions,
)
from shimeji_dl.core.models import (
    AssetRef,
    CharacterRef,
    SourceManifest,
    SpriteRegion,
)
from shimeji_dl.formats.shimeji_xml import ShimejiXmlFormat

PNG_A = b"\x89PNG\r\n\x1a\nA"
PNG_B = b"\x89PNG\r\n\x1a\nB"
WAV = b"RIFF\x00\x00\x00\x00WAVE"


class Response:
    url = "https://example/shime1.png"
    content = PNG_B
    content_type = "image/png"


class Client:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        return Response()


class Source:
    key = "source"
    config_names = ()

    def request_headers(self):
        return {}

    def asset_candidates(self, character, ref):
        return ["https://example/shime1.png"]


class Config:
    def is_valid(self, data):
        return True

    def extract_asset_refs(self, data):
        return []


class Reporter:
    pass


def make_engine(tmp_path: Path, client: Client, *, overwrite: bool) -> DownloadEngine:
    return DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, overwrite=overwrite),
        sources={"source": Source()},
        config_format=Config(),
        reporter=Reporter(),
    )


def test_existing_valid_asset_is_reused_by_default(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")
    destination = tmp_path / character.id
    destination.mkdir()
    (destination / "shime1.png").write_bytes(PNG_A)
    client = Client()
    engine = make_engine(tmp_path, client, overwrite=False)

    _, success, tried = asyncio.run(
        engine._download_ref(Source(), character, AssetRef("shime1.png", "shime1.png"), destination)
    )

    assert success
    assert tried == []
    assert client.calls == 0
    assert (destination / "shime1.png").read_bytes() == PNG_A


def test_existing_valid_sound_is_reused_by_default(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")
    destination = tmp_path / character.id
    sound = destination / "sound" / "step.wav"
    sound.parent.mkdir(parents=True)
    sound.write_bytes(WAV)
    client = Client()
    engine = make_engine(tmp_path, client, overwrite=False)

    _, success, tried = asyncio.run(
        engine._download_ref(Source(), character, AssetRef("step.wav", "sound/step.wav"), destination)
    )

    assert success
    assert tried == []
    assert client.calls == 0
    assert sound.read_bytes() == WAV


def test_overwrite_refetches_existing_valid_asset(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")
    destination = tmp_path / character.id
    destination.mkdir()
    (destination / "shime1.png").write_bytes(PNG_A)
    client = Client()
    engine = make_engine(tmp_path, client, overwrite=True)

    _, success, tried = asyncio.run(
        engine._download_ref(Source(), character, AssetRef("shime1.png", "shime1.png"), destination)
    )

    assert success
    assert tried == ["https://example/shime1.png"]
    assert client.calls == 1
    assert (destination / "shime1.png").read_bytes() == PNG_B


class WarningReporter:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def test_download_ref_rejects_escaping_path_without_aborting(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")
    destination = tmp_path / character.id
    destination.mkdir()
    client = Client()
    reporter = WarningReporter()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, overwrite=False),
        sources={"source": Source()},
        config_format=Config(),
        reporter=reporter,
    )

    ref, success, tried = asyncio.run(
        engine._download_ref(Source(), character, AssetRef("evil.png", "../evil.png"), destination)
    )

    assert not success
    assert tried == []
    assert client.calls == 0
    assert reporter.warnings and "../evil.png" in reporter.warnings[0]
    assert not (tmp_path / "evil.png").exists()


def test_extract_sprite_regions_skips_hostile_region_and_keeps_siblings(tmp_path: Path) -> None:
    atlas = Image.new("RGBA", (4, 2))
    atlas.paste((255, 0, 0, 255), (0, 0, 2, 2))
    atlas.paste((0, 0, 255, 255), (2, 0, 4, 2))
    buf = BytesIO()
    atlas.save(buf, format="PNG")

    dest = tmp_path / "character"
    dest.mkdir()
    regions = {
        "../evil.png": SpriteRegion("../evil.png", 0, 0, 2, 2),
        "sound/effect.png": SpriteRegion("sound/effect.png", 2, 0, 2, 2),
    }

    extracted, rejected = _extract_sprite_regions(buf.getvalue(), regions, dest)

    assert extracted == {"sound/effect.png"}
    assert rejected == ["../evil.png"]
    assert (dest / "sound" / "effect.png").exists()
    assert not (tmp_path / "evil.png").exists()


class AtlasResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.url = "https://example/spritesheet.png"
        self.content_type = "image/png"


class SpritesheetClient:
    def __init__(self, atlas_bytes: bytes) -> None:
        self.atlas_bytes = atlas_bytes
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        return AtlasResponse(self.atlas_bytes)


def test_materialize_spritesheet_warns_on_rejected_region_without_aborting(tmp_path: Path) -> None:
    atlas = Image.new("RGBA", (4, 2))
    atlas.paste((255, 0, 0, 255), (0, 0, 2, 2))
    atlas.paste((0, 0, 255, 255), (2, 0, 4, 2))
    buf = BytesIO()
    atlas.save(buf, format="PNG")

    dest = tmp_path / "character"
    dest.mkdir()
    manifest = SourceManifest(
        source_url="https://example/character",
        authoritative=True,
        spritesheet_url="https://example/spritesheet.png",
        sprites={
            "../evil.png": SpriteRegion("../evil.png", 0, 0, 2, 2),
            "sound/effect.png": SpriteRegion("sound/effect.png", 2, 0, 2, 2),
        },
    )
    client = SpritesheetClient(buf.getvalue())
    reporter = WarningReporter()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, overwrite=False),
        sources={"source": Source()},
        config_format=Config(),
        reporter=reporter,
    )

    present = asyncio.run(engine._materialize_spritesheet(Source(), manifest, dest))

    assert present == {"sound/effect.png"}
    assert client.calls == 1
    assert reporter.warnings and "../evil.png" in reporter.warnings[0]
    assert (dest / "sound" / "effect.png").exists()
    assert not (tmp_path / "evil.png").exists()


class FailingSpritesheetClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        return None


def test_materialize_spritesheet_reports_escaping_key_even_when_fetch_fails(tmp_path: Path) -> None:
    """The already-valid-paths pre-check must report a confinement rejection too.

    When the spritesheet fetch fails, _extract_sprite_regions's own
    rejection-reporting loop never runs, so _valid_manifest_paths is the
    only site that ever sees this manifest's escaping key.
    """
    dest = tmp_path / "character"
    dest.mkdir()
    manifest = SourceManifest(
        source_url="https://example/character",
        authoritative=True,
        spritesheet_url="https://example/spritesheet.png",
        sprites={"../evil.png": SpriteRegion("../evil.png", 0, 0, 2, 2)},
    )
    client = FailingSpritesheetClient()
    reporter = WarningReporter()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, overwrite=False),
        sources={"source": Source()},
        config_format=Config(),
        reporter=reporter,
    )

    present = asyncio.run(engine._materialize_spritesheet(Source(), manifest, dest))

    assert present == set()
    assert client.calls == 1
    assert reporter.warnings and "../evil.png" in reporter.warnings[0]


class ProbeSource(Source):
    def numeric_asset(self, character, index):
        return AssetRef(f"shime{index}.png", f"shime{index}.png")

    def asset_candidates(self, character, ref):
        return [f"https://example/{ref.path}"]


class MissingClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get(self, url, *args, **kwargs):
        self.urls.append(url)
        return None


def test_probe_reuses_hits_but_rechecks_misses_on_every_scan(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")
    destination = tmp_path / character.id
    destination.mkdir()
    (destination / "shime1.png").write_bytes(PNG_A)
    client = MissingClient()
    source = ProbeSource()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, overwrite=False),
        sources={"source": source},
        config_format=Config(),
        reporter=Reporter(),
    )

    first = asyncio.run(engine._probe(source, character, destination, set(), set()))
    first_urls = list(client.urls)
    client.urls.clear()
    second = asyncio.run(engine._probe(source, character, destination, set(), set()))
    second_urls = list(client.urls)

    assert first.requests > 0
    assert second.requests == first.requests
    assert first_urls == second_urls
    assert "https://example/shime1.png" not in first_urls
    assert "https://example/shime1.png" not in second_urls
    assert "https://example/shime2.png" in first_urls
    assert "https://example/shime2.png" in second_urls


def test_source_manifest_capability_is_optional(tmp_path: Path) -> None:
    client = Client()
    engine = make_engine(tmp_path, client, overwrite=False)
    character = CharacterRef("source", "character", "https://example/character")

    manifest = asyncio.run(engine._get_manifest(Source(), character))

    assert manifest is None


def test_source_manifest_materializes_atlas_and_classifies_source_misses(tmp_path: Path) -> None:
    atlas = Image.new("RGBA", (4, 2))
    atlas.paste((255, 0, 0, 255), (0, 0, 2, 2))
    atlas.paste((0, 0, 255, 255), (2, 0, 4, 2))
    atlas_bytes = BytesIO()
    atlas.save(atlas_bytes, format="PNG")

    manifest = SourceManifest(
        source_url="https://example/api/configuration",
        authoritative=True,
        configs={
            "actions.xml": b'''<Mascot><Pose Image="/shime1.png" Sound="missing.wav"/></Mascot>''',
            "behaviors.xml": b"<Mascot/>",
        },
        spritesheet_url="https://example/spritesheet.png",
        sprites={
            "shime1.png": SpriteRegion("shime1.png", 0, 0, 2, 2),
            "shime2.png": SpriteRegion("shime2.png", 2, 0, 2, 2),
        },
        metadata={"shimejiName": "Example"},
    )

    class AtlasResponse:
        url = "https://example/spritesheet.png"
        content = atlas_bytes.getvalue()
        content_type = "image/png"

    class ManifestClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get(self, url, *args, **kwargs):
            self.urls.append(url)
            return AtlasResponse() if url.endswith("spritesheet.png") else None

    class ManifestSource:
        key = "source"
        config_names = ("actions.xml", "behaviors.xml", "info.xml")

        async def fetch_manifest(self, client, character, *, report_rejection=lambda message: None):
            return manifest

        def config_candidates(self, character, name):
            return []

        def request_headers(self):
            return {}

        def prioritize(self, character, configs):
            pass

        def asset_candidates(self, character, ref):
            return [f"https://example/{ref.path}"]

        def numeric_asset(self, character, index):
            return AssetRef(f"shime{index}.png", f"shime{index}.png")

    class NullReporter:
        def character_started(self, character):
            pass

        def character_phase(self, character, phase, detail=""):
            pass

        def character_finished(self, result):
            pass

        def verbose(self, message):
            pass

        def warning(self, message):
            pass

    client = ManifestClient()
    source = ManifestSource()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, probe_mode="auto"),
        sources={"source": source},
        config_format=ShimejiXmlFormat(),
        reporter=NullReporter(),
    )
    character = CharacterRef("source", "character", "https://example/character")
    result = asyncio.run(engine.download_character(character))

    assert result.asset_paths == ["shime1.png", "shime2.png"]
    assert result.atlas_paths == ["shime1.png", "shime2.png"]
    assert result.discovery == "xml+source-manifest"
    assert result.probe.requests == 0
    assert result.probe.stop_reason == "source-manifest"
    assert [(item.path, item.kind) for item in result.referenced_missing] == [
        ("sound/missing.wav", "source-missing")
    ]
    assert not result.complete
    assert not result.retryable
    assert client.urls == [
        "https://example/spritesheet.png",
        "https://example/sound/missing.wav",
    ]

    with Image.open(tmp_path / "character" / "shime1.png") as red:
        assert red.size == (2, 2)
        assert red.getpixel((0, 0)) == (255, 0, 0, 255)
    with Image.open(tmp_path / "character" / "shime2.png") as blue:
        assert blue.getpixel((0, 0)) == (0, 0, 255, 255)


def test_failing_config_fetch_cancels_its_slow_sibling(tmp_path: Path) -> None:
    character = CharacterRef("source", "character", "https://example/character")

    class SlowClient:
        def __init__(self) -> None:
            self.cancelled = False

        async def get(self, url, *args, **kwargs):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return None

    class TwoConfigSource(Source):
        config_names = ("slow.xml", "fail.xml")

        def config_candidates(self, character, name):
            if name == "fail.xml":
                raise RuntimeError("boom")
            return ["https://example/slow.xml"]

    class NullReporter:
        def character_started(self, character):
            pass

        def character_phase(self, character, phase, detail=""):
            pass

        def character_finished(self, result):
            pass

        def warning(self, message):
            pass

    client = SlowClient()
    engine = DownloadEngine(
        client,
        DownloadOptions(output=tmp_path, probe_mode="off"),
        sources={"source": TwoConfigSource()},
        config_format=Config(),
        reporter=NullReporter(),
    )

    async def scenario():
        async with asyncio.timeout(5):
            return await engine._limited_download(character)

    result = asyncio.run(scenario())

    assert client.cancelled
    assert not result.usable
    assert result.error is not None
    assert "boom" in result.error
