import asyncio
from pathlib import Path

from shimeji_dl.core.engine import DownloadEngine, DownloadOptions
from shimeji_dl.core.models import AssetRef, CharacterRef

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
