from dataclasses import fields

from shimeji_dl.core.probe_tuning import (
    AUTO_PROBE_TUNING,
    DEEP_PROBE_TUNING,
    probe_tuning_for_mode,
)


def test_probe_tuning_for_mode_selects_deep() -> None:
    assert probe_tuning_for_mode("deep") is DEEP_PROBE_TUNING


def test_probe_tuning_for_mode_defaults_to_auto() -> None:
    assert probe_tuning_for_mode("auto") is AUTO_PROBE_TUNING
    assert probe_tuning_for_mode("off") is AUTO_PROBE_TUNING


def test_deep_tuning_searches_more_broadly_than_auto_in_every_dimension() -> None:
    """Deep mode's entire purpose is to search more broadly than auto.

    The exact numbers are unspecified and free to retune, but a "deep"
    tuning that is not strictly broader than "auto" in every knob would no
    longer deserve the name.
    """
    for field in fields(DEEP_PROBE_TUNING):
        deep_value = getattr(DEEP_PROBE_TUNING, field.name)
        auto_value = getattr(AUTO_PROBE_TUNING, field.name)
        assert deep_value > auto_value, field.name
