import asyncio
import re
from pathlib import Path

from shimeji_dl.client import FetchResult
from shimeji_dl.downloader import DownloadOptions, Downloader
from shimeji_dl.probe import numeric_sprite_index, numeric_sprite_indices, quiescence_span

PNG = b"\x89PNG\r\n\x1a\nFAKE"


class FakeFetcher:
    def __init__(self, existing: set[int]) -> None:
        self.existing = existing

    async def get(self, url: str, *, optional: bool = False):
        match = re.search(r"/shime([0-9]+)\.png$", url)
        if match and int(match.group(1)) in self.existing:
            return FetchResult(url=url, status_code=200, content=PNG, content_type="image/png")
        return None


def test_numeric_sprite_helpers() -> None:
    assert numeric_sprite_index("shime55.png") == 55
    assert numeric_sprite_index("SHIME12.PNG") == 12
    assert numeric_sprite_index("nested/shime3.png") is None
    assert numeric_sprite_indices(["shime1.png", "foo.png", "shime9.png"]) == {1, 9}


def test_quiescence_expands_for_sparse_pack() -> None:
    dense = quiescence_span([1, 2, 3, 4, 5], "auto")
    sparse = quiescence_span([1, 2, 40], "auto")
    assert sparse > dense
    assert quiescence_span([1, 2, 40], "deep") > sparse


def test_adaptive_probe_has_no_numeric_ceiling(tmp_path: Path) -> None:
    async def run() -> None:
        # 257 deliberately exceeds the old default --probe-limit 128.
        fetcher = FakeFetcher(set(range(1, 258)))
        downloader = Downloader(fetcher, DownloadOptions(output=tmp_path, probe_mode="auto"))  # type: ignore[arg-type]
        dest = tmp_path / "character"
        dest.mkdir()

        report = await downloader._adaptive_numeric_probe(
            roots=["https://example.test/directory/character"],
            dest=dest,
            xml_paths=set(),
            referenced_present=set(),
        )

        assert report.highest_hit == 257
        assert 257 in report.hits
        assert (dest / "shime257.png").exists()
        assert report.stop_reason == "quiescent-tail"

    asyncio.run(run())


def test_xml_and_probe_are_combined(tmp_path: Path) -> None:
    async def run() -> None:
        fetcher = FakeFetcher(set(range(1, 56)) | {60})
        downloader = Downloader(fetcher, DownloadOptions(output=tmp_path, probe_mode="auto"))  # type: ignore[arg-type]
        dest = tmp_path / "character"
        dest.mkdir()
        (dest / "shime55.png").write_bytes(PNG)

        report = await downloader._adaptive_numeric_probe(
            roots=["https://example.test/directory/character"],
            dest=dest,
            xml_paths={"shime55.png"},
            referenced_present={"shime55.png"},
        )

        assert report.xml_anchors == [55]
        assert report.highest_hit == 60
        assert "shime60.png" in report.extra_hits
        assert (dest / "shime60.png").exists()

    asyncio.run(run())


def test_deep_finds_far_sparse_tail_that_auto_may_skip(tmp_path: Path) -> None:
    async def run() -> None:
        existing = set(range(1, 56)) | {120}
        fetcher = FakeFetcher(existing)
        dest = tmp_path / "character"
        dest.mkdir()
        (dest / "shime55.png").write_bytes(PNG)

        downloader = Downloader(fetcher, DownloadOptions(output=tmp_path, probe_mode="deep"))  # type: ignore[arg-type]
        report = await downloader._adaptive_numeric_probe(
            roots=["https://example.test/directory/character"],
            dest=dest,
            xml_paths={"shime55.png"},
            referenced_present={"shime55.png"},
        )

        assert report.highest_hit == 120
        assert "shime120.png" in report.extra_hits

    asyncio.run(run())
