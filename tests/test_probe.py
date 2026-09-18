import asyncio

from shimeji_dl.core.probing import AdaptiveNumericProber, adaptive_quiet_span, numeric_index


def test_numeric_index() -> None:
    assert numeric_index("shime55.png") == 55
    assert numeric_index("nested/shime55.png") is None
    assert numeric_index("foo.png") is None


def test_quiet_span_grows_for_sparse_hits() -> None:
    assert adaptive_quiet_span([1, 2, 3], "auto") < adaptive_quiet_span([1, 2, 100], "auto")


def test_adaptive_probe_discovers_dense_tail() -> None:
    async def run():
        existing = set(range(1, 56))
        return await AdaptiveNumericProber(mode="auto", batch_size=16).run(
            lambda index: asyncio.sleep(0, result=index in existing),
            known_hits={1},
        )

    report = asyncio.run(run())
    assert report.highest_hit == 55
    assert set(range(1, 56)).issubset(report.hits)
    assert report.stop_reason == "quiescent-tail"
